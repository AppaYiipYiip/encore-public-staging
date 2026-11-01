import 'dart:async';

import 'package:drift/native.dart';
import 'package:encore/app/providers.dart';
import 'package:encore/core/clock.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/repos/downloads_repository.dart';
import 'package:encore/data/repos/release_store.dart';
import 'package:encore/domain/audio_quality.dart';
import 'package:encore/features/catalogue/catalogue_screens.dart';
import 'package:encore/features/detail/detail_screens.dart'
    show DownloadedScreen;
import 'package:encore/features/downloads/download_providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import '../support/test_app.dart';

/// D-35 (B2, second half): a release the person downloaded is ONE entry, in Library > Downloaded and in Settings > Downloads & storage, not
/// N loose "Song" entries; removing it takes all its songs off, also after a restart.
void main() {
  setUpAll(loadAppFonts);

  const release = PhoneRelease(
    refIds: ['sr_1', 'sr_2'],
    title: 'Weird Fishes Release',
    artist: 'Radiohead',
    download: true,
  );

  group('the entries', () {
    late AppDatabase db;
    late int serverId;
    late ProviderContainer container;
    late DownloadsRepository repo;

    setUp(() async {
      db = AppDatabase(NativeDatabase.memory());
      serverId = await db.into(db.servers).insert(ServersCompanion.insert(
            name: 'Home',
            username: 'marwa',
            endpointsJson: '[]',
            createdAtMs: 0,
          ));
      repo = DownloadsRepository(db, serverId,
          clock: FakeClock(DateTime.utc(2026, 10, 30, 22)));
      container = ProviderContainer(overrides: [
        databaseProvider.overrideWithValue(db),
        clockProvider
            .overrideWithValue(FakeClock(DateTime.utc(2026, 10, 30, 22))),
      ]);
      container.listen(activeServerProvider, (_, __) {});
      container.listen(pinsProvider, (_, __) {});
      container.listen(phoneReleasesProvider, (_, __) {});
    });

    tearDown(() async {
      container.dispose();
      await db.close();
    });

    Future<List<PinEntry>> entries() async {
      await Future<void>.delayed(Duration.zero);
      return container.read(pinEntriesProvider.future);
    }

    test(
        'the songs of a downloaded release are one entry with its own title and artist',
        () async {
      await ReleaseStore(db, serverId).put('cat:1', release);
      await repo.pin(PinTargetType.track, 'sr_1');
      await repo.pin(PinTargetType.track, 'sr_2');

      final all = await entries();

      expect(all, hasLength(1));
      expect(all.single.title, 'Weird Fishes Release');
      expect(all.single.artist, 'Radiohead');
      expect(all.single.kind, 'Album');
      expect(all.single.releaseId, 'cat:1');
      expect(all.single.releaseRefIds, ['sr_1', 'sr_2']);
    });

    test('a release that is half downloaded is still one entry', () async {
      await ReleaseStore(db, serverId).put('cat:1', release);
      await repo.pin(PinTargetType.track, 'sr_1');

      final all = await entries();

      expect(all, hasLength(1));
      expect(all.single.releaseId, 'cat:1');
    });

    test(
        'a song that two downloaded releases share belongs to both: neither loses its entry',
        () async {
      // A single and the album that holds the same song: the person downloaded both. The single is the older one, so the album is the one
      // that was written down last; the song must not be taken by the album alone, or the single would not be listed at all.
      const single = PhoneRelease(
        refIds: ['sr_1'],
        title: 'Weird Fishes (single)',
        artist: 'Radiohead',
        download: true,
      );
      await ReleaseStore(db, serverId).put('cat:1', single);
      await ReleaseStore(db, serverId).put('cat:2', release);
      await repo.pin(PinTargetType.track, 'sr_1');
      await repo.pin(PinTargetType.track, 'sr_2');

      final all = await entries();

      expect(all.map((e) => e.releaseId), unorderedEquals(['cat:1', 'cat:2']),
          reason: 'one entry for each downloaded release, once');
      expect(all.firstWhere((e) => e.releaseId == 'cat:1').releaseRefIds,
          ['sr_1']);
      expect(all.firstWhere((e) => e.releaseId == 'cat:2').releaseRefIds,
          ['sr_1', 'sr_2']);
    });

    test('a song downloaded on its own stays a song', () async {
      await ReleaseStore(db, serverId).put('cat:1', release);
      await repo.pin(PinTargetType.track, 'sr_1');
      await repo.pin(PinTargetType.track, 'sr_2');
      await repo.pin(PinTargetType.track, 'sr_9'); // not from the release

      final all = await entries();

      expect(all.map((e) => e.releaseId), unorderedEquals(['cat:1', null]));
      expect(all.where((e) => e.releaseId == null).single.kind, 'Song');
    });

    test(
        'a release that is only in the library has no entry, and neither does a playlist or album pin lose its own',
        () async {
      await ReleaseStore(db, serverId)
          .put('cat:1', release.copyWith(download: false));
      await repo.pin(PinTargetType.track, 'sr_1');

      final all = await entries();

      expect(all.single.releaseId, isNull,
          reason: 'no intent to keep it on the phone: the pin is a loose song');
      expect(all.single.kind, 'Song');
    });
  });

  group('on the screens', () {
    Future<AppDatabase> open(WidgetTester tester, List<String> pinnedActions,
        {List<Override> more = const []}) async {
      final app = await pumpApp(tester, overrides: [
        downloadActionsProvider.overrideWithValue(_Actions(pinnedActions)),
        ...more,
      ]);
      final repo = DownloadsRepository(app.db, app.serverId,
          clock: FakeClock(DateTime.utc(2026, 10, 30, 22)));
      await ReleaseStore(app.db, app.serverId).put('cat:1', release);
      await repo.pin(PinTargetType.track, 'sr_1');
      await repo.pin(PinTargetType.track, 'sr_2');
      await settle(tester);
      return app.db;
    }

    testWidgets('Library > Downloaded lists a two-song release once',
        (tester) async {
      final db = await open(tester, []);

      await tester.tap(find.text('Your Library'));
      await settle(tester);
      // The chip row scrolls: "Downloaded" is the last chip and starts off the edge of a phone.
      await tester.ensureVisible(find.text('Downloaded'));
      await settle(tester);
      await tester.tap(find.text('Downloaded'));
      await settle(tester);

      expect(find.textContaining('Weird Fishes Release'), findsOneWidget);
      expect(find.textContaining('Unavailable item'), findsNothing,
          reason: 'the two songs are not shown as loose songs');
      await closeApp(tester, db);
    });

    // Offline the Library opens on Downloaded by itself (and the chip would switch it off), so the chip is only tapped with a connection.
    Future<void> openDownloaded(WidgetTester tester,
        {required bool chip}) async {
      await tester.tap(find.text('Your Library'));
      await settle(tester);
      if (chip) {
        await tester.ensureVisible(find.text('Downloaded'));
        await settle(tester);
        await tester.tap(find.text('Downloaded'));
        await settle(tester);
      }
    }

    testWidgets(
        'D-36: the entry opens the release page when there is a connection',
        (tester) async {
      final db = await open(tester, [], more: [
        networkKindProvider
            .overrideWith((ref) => Stream.value(NetworkKind.wifi)),
      ]);
      await openDownloaded(tester, chip: true);

      await tester.tap(find.textContaining('Weird Fishes Release'));
      await settle(tester);

      expect(find.byType(CatalogueAlbumScreen), findsOneWidget);
      expect(find.byType(DownloadedScreen), findsNothing);
      await closeApp(tester, db);
    });

    testWidgets(
        'D-36: with no connection the entry opens the songs that are on the phone, not a page that cannot load',
        (tester) async {
      final db = await open(tester, [], more: [
        networkKindProvider
            .overrideWith((ref) => Stream.value(NetworkKind.none)),
      ]);
      await openDownloaded(tester, chip: false);

      await tester.tap(find.textContaining('Weird Fishes Release'));
      await settle(tester);

      expect(find.byType(DownloadedScreen), findsOneWidget);
      expect(find.byType(CatalogueAlbumScreen), findsNothing);
      await closeApp(tester, db);
    });

    testWidgets(
        'Settings > Downloads & storage lists it once, and Remove takes both songs off',
        (tester) async {
      final took = <String>[];
      final db = await open(tester, took);
      final element = tester.element(find.byType(Scaffold).first);
      unawaited(GoRouter.of(element).push<void>('/settings/downloads'));
      await settle(tester);

      expect(find.text('Weird Fishes Release'), findsOneWidget);
      expect(find.byTooltip('Remove download'), findsOneWidget);

      await tester.tap(find.byTooltip('Remove download'));
      await settle(tester);

      expect(took, unorderedEquals(['sr_1', 'sr_2']));
      final back = (await ReleaseStore(db, 1).phone())['cat:1']!;
      expect(back.download, isFalse);
      await closeApp(tester, db);
    });

    testWidgets(
        'Settings > Downloads & storage: Remove all downloads takes every song of a release off, not only its first (code review)',
        (tester) async {
      final took = <String>[];
      final db = await open(tester, took);
      final element = tester.element(find.byType(Scaffold).first);
      unawaited(GoRouter.of(element).push<void>('/settings/downloads'));
      await settle(tester);

      await tester.tap(find.text('Remove all downloads'));
      await settle(tester);
      await tester.tap(find.text('Remove'));
      await settle(tester);

      expect(took, unorderedEquals(['sr_1', 'sr_2']));
      final back = (await ReleaseStore(db, 1).phone())['cat:1']!;
      expect(back.download, isFalse);
      await closeApp(tester, db);
    });
  });
}

/// The download actions over nothing: it only says what was unpinned.
class _Actions implements DownloadActions {
  _Actions(this.unpinned);

  final List<String> unpinned;

  @override
  Future<void> pin(PinTargetType type, String targetId,
      {AudioQuality? quality}) async {}

  @override
  Future<void> unpin(PinTargetType type, String targetId) async =>
      unpinned.add(targetId);

  @override
  Future<void> retry() async {}

  @override
  Future<void> removeAll() async {}
}
