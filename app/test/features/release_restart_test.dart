import 'package:drift/native.dart';
import 'package:encore/app/providers.dart';
import 'package:encore/core/clock.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/encore/encore_models.dart';
import 'package:encore/data/repos/downloads_repository.dart';
import 'package:encore/data/repos/release_store.dart';
import 'package:encore/domain/audio_quality.dart';
import 'package:encore/features/downloads/download_providers.dart';
import 'package:encore/features/instant/release_save.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

/// D-35 (B2): a release must look the same after the app restarts. Before, the release page's state lived only in memory: after a restart or a
/// kill in the middle of a download (J4) it showed "Add to library" again although the server saved the release and the phone held the files,
/// and "remove download" unpinned nothing. A fresh container over the same database stands in for the restart.
void main() {
  late AppDatabase db;
  late int serverId;
  late List<String> pinned;
  late List<String> unpinned;
  final containers = <ProviderContainer>[];

  const release = PhoneRelease(
    refIds: ['sr_1', 'sr_2', 'sr_3'],
    title: 'In Rainbows',
    artist: 'Radiohead',
    download: true,
  );

  /// The app starting again: a new container, the same database. Pins go to the real tables so what resume sees is what is stored.
  ProviderContainer restart() {
    final repo = DownloadsRepository(db, serverId,
        clock: FakeClock(DateTime.utc(2026, 10, 30, 22)));
    final c = ProviderContainer(overrides: [
      databaseProvider.overrideWithValue(db),
      clockProvider
          .overrideWithValue(FakeClock(DateTime.utc(2026, 10, 30, 22))),
      downloadActionsProvider
          .overrideWithValue(_Actions(repo, pinned, unpinned)),
    ]);
    containers.add(c);
    // What the screens hold while they are open.
    c.listen(activeServerProvider, (_, __) {});
    c.listen(pinsProvider, (_, __) {});
    return c;
  }

  Future<ReleaseState?> pageOf(ProviderContainer c, String id) async {
    // The streams have a first value a moment after they are listened to.
    c.listen(phoneReleasesProvider, (_, __) {});
    c.listen(savedReleasesProvider, (_, __) {});
    await Future<void>.delayed(Duration.zero);
    await c.read(phoneReleasesProvider.future);
    await c.read(savedReleasesProvider.future);
    return c.read(releaseStateProvider(id));
  }

  setUp(() async {
    db = AppDatabase(NativeDatabase.memory());
    serverId = await db.into(db.servers).insert(ServersCompanion.insert(
          name: 'Home',
          username: 'marwa',
          endpointsJson: '[]',
          createdAtMs: 0,
        ));
    pinned = [];
    unpinned = [];
  });

  tearDown(() async {
    for (final c in containers) {
      c.dispose();
    }
    containers.clear();
    await db.close();
  });

  group('after a restart the release page', () {
    test(
        'still says it is in the library, and that the songs are for the phone',
        () async {
      await ReleaseStore(db, serverId).put('cat:1', release);

      final page = await pageOf(restart(), 'cat:1');

      expect(page?.phase, ReleasePhase.saved);
      expect(page?.download, isTrue);
      expect(page?.refIds, ['sr_1', 'sr_2', 'sr_3'],
          reason: 'the ring is added up from the pins of these songs');
    });

    test(
        'on a second phone that only has the synced release says "In your library" with no download',
        () async {
      await ReleaseStore(db, serverId).applySaved(
          [const EncoreSetItem(id: 'cat:1', atMs: 1, removed: false)]);

      final page = await pageOf(restart(), 'cat:1');

      expect(page?.phase, ReleasePhase.saved);
      expect(page?.download, isFalse, reason: 'downloads belong to each phone');
      expect(page?.refIds, isEmpty);
    });

    test('knows nothing of a release nobody saved', () async {
      await ReleaseStore(db, serverId).put('cat:1', release);

      expect(await pageOf(restart(), 'cat:2'), isNull);
    });

    test(
        'an Encore save that is on its way, in memory, wins over what was written down',
        () async {
      await ReleaseStore(db, serverId).put('cat:1', release);
      final c = restart();
      c
          .read(releaseSavesProvider.notifier)
          // ignore: invalid_use_of_protected_member
          .state = {'cat:1': const ReleaseState(ReleasePhase.saving)};

      final page = await pageOf(c, 'cat:1');

      expect(page?.phase, ReleasePhase.saving);
    });
  });

  group('removing the download after a restart', () {
    test('unpins every song of the release, not nothing', () async {
      await ReleaseStore(db, serverId).put('cat:1', release);
      final c = restart();
      // The page's own memory is empty after a restart: only what was written down is left.
      expect(c.read(releaseSavesProvider), isEmpty);

      await c.read(releaseSavesProvider.notifier).removeDownload('cat:1');

      expect(unpinned, unorderedEquals(['sr_1', 'sr_2', 'sr_3']));
      final back = (await ReleaseStore(db, serverId).phone())['cat:1']!;
      expect(back.download, isFalse, reason: 'no intent to keep it here now');
      expect(back.refIds, hasLength(3), reason: 'it is still in the library');
    });

    test('leaves the release saved, without the download', () async {
      await ReleaseStore(db, serverId).put('cat:1', release);
      final c = restart();
      await c.read(releaseSavesProvider.notifier).removeDownload('cat:1');

      final page = await pageOf(restart(), 'cat:1');

      expect(page?.phase, ReleasePhase.saved);
      expect(page?.download, isFalse);
    });
  });

  group('a download that was killed half way', () {
    test(
        'the way the app starts it: only the resume provider is listened to, nothing is faked, and the missing pins are in the table',
        () async {
      await ReleaseStore(db, serverId).put('cat:1', release);
      // Exactly what app.dart does: one listener, no screens open, the real download actions over the real tables.
      final c = ProviderContainer(overrides: [
        databaseProvider.overrideWithValue(db),
        clockProvider
            .overrideWithValue(FakeClock(DateTime.utc(2026, 10, 30, 22))),
      ]);
      containers.add(c);
      c.listen(releaseResumeProvider, (_, __) {});

      final count = await c.read(releaseResumeProvider.future);

      expect(count, 3);
      final rows = await db.select(db.pins).get();
      expect(rows.map((p) => p.targetId),
          unorderedEquals(['sr_1', 'sr_2', 'sr_3']),
          reason:
              'a pin that goes to a repository that is not there yet is lost without a word');
      expect(rows.every((p) => p.targetType == 'track'), isTrue);
    });

    test(
        'is finished when the app starts: only the songs with no pin are pinned',
        () async {
      await ReleaseStore(db, serverId).put('cat:1', release);
      await DownloadsRepository(db, serverId,
              clock: FakeClock(DateTime.utc(2026, 10, 30, 21)))
          .pin(PinTargetType.track,
              'sr_1'); // the first pin was made, then the kill

      final count =
          await restart().read(releaseSavesProvider.notifier).resume();

      expect(count, 2);
      final rows = {
        for (final p in await db.select(db.pins).get()) p.targetId: p
      };
      expect(rows.keys, unorderedEquals(['sr_1', 'sr_2', 'sr_3']));
      expect(rows['sr_1']!.createdAtMs,
          DateTime.utc(2026, 10, 30, 21).millisecondsSinceEpoch,
          reason:
              'the pin that was already there is left alone, not made again');
    });

    test('is not started again when everything is pinned', () async {
      await ReleaseStore(db, serverId).put('cat:1', release);
      final repo = DownloadsRepository(db, serverId,
          clock: FakeClock(DateTime.utc(2026, 10, 30, 21)));
      for (final id in release.refIds) {
        await repo.pin(PinTargetType.track, id);
      }

      final count =
          await restart().read(releaseSavesProvider.notifier).resume();

      expect(count, 0);
      expect(await db.select(db.pins).get(), hasLength(3));
    });

    test(
        'a release that is only in the library is not downloaded by the resume',
        () async {
      await ReleaseStore(db, serverId)
          .put('cat:1', release.copyWith(download: false));

      final count =
          await restart().read(releaseSavesProvider.notifier).resume();

      expect(count, 0);
      expect(await db.select(db.pins).get(), isEmpty);
    });

    test(
        'one song taken off from the song menu is not given back by the next start (D-35, D-32)',
        () async {
      await ReleaseStore(db, serverId).put('cat:1', release);
      final repo = DownloadsRepository(db, serverId,
          clock: FakeClock(DateTime.utc(2026, 10, 30, 21)));
      for (final id in release.refIds) {
        await repo.pin(PinTargetType.track, id);
      }

      await restart()
          .read(releaseSavesProvider.notifier)
          .removeSongDownload('sr_2');
      expect((await db.select(db.pins).get()).map((p) => p.targetId),
          unorderedEquals(['sr_1', 'sr_3']),
          reason: 'the song is off the phone');

      final count =
          await restart().read(releaseSavesProvider.notifier).resume();

      expect(count, 0,
          reason: 'the next start must not pin it again: the person said no');
      expect((await db.select(db.pins).get()).map((p) => p.targetId),
          unorderedEquals(['sr_1', 'sr_3']));
      final record = (await ReleaseStore(db, serverId).phone())['cat:1']!;
      expect(record.refIds, ['sr_1', 'sr_3'],
          reason: 'the phone\'s own record of the release no longer lists it');
      expect(record.download, isTrue,
          reason: 'the other songs are still wanted on the phone');
    });

    test(
        'taking the last downloaded song of a release off leaves the release saved without the download intent',
        () async {
      const one = PhoneRelease(
          refIds: ['sr_1'], title: 'Single', artist: 'A', download: true);
      await ReleaseStore(db, serverId).put('cat:2', one);
      await DownloadsRepository(db, serverId,
              clock: FakeClock(DateTime.utc(2026, 10, 30, 21)))
          .pin(PinTargetType.track, 'sr_1');

      await restart()
          .read(releaseSavesProvider.notifier)
          .removeSongDownload('sr_1');

      final record = (await ReleaseStore(db, serverId).phone())['cat:2']!;
      expect(record.download, isFalse);
      expect(await restart().read(releaseSavesProvider.notifier).resume(), 0);
    });

    test('a song that is in no release is simply unpinned', () async {
      await DownloadsRepository(db, serverId,
              clock: FakeClock(DateTime.utc(2026, 10, 30, 21)))
          .pin(PinTargetType.track, 'loose');

      await restart()
          .read(releaseSavesProvider.notifier)
          .removeSongDownload('loose');

      expect(await db.select(db.pins).get(), isEmpty);
    });

    test('a person who took the download off is not given it back', () async {
      await ReleaseStore(db, serverId).put('cat:1', release);
      await restart()
          .read(releaseSavesProvider.notifier)
          .removeDownload('cat:1');

      final count =
          await restart().read(releaseSavesProvider.notifier).resume();

      expect(count, 0);
      expect(await db.select(db.pins).get(), isEmpty);
    });
  });
}

/// The download actions over the real tables, recording what was pinned and unpinned.
class _Actions implements DownloadActions {
  _Actions(this._repo, this.pinned, this.unpinned);

  final DownloadsRepository _repo;
  final List<String> pinned;
  final List<String> unpinned;

  @override
  Future<void> pin(PinTargetType type, String targetId,
      {AudioQuality? quality}) async {
    pinned.add(targetId);
    await _repo.pin(type, targetId);
  }

  @override
  Future<void> unpin(PinTargetType type, String targetId) async {
    unpinned.add(targetId);
    await _repo.unpin(type, targetId);
  }

  @override
  Future<void> retry() async {}

  @override
  Future<void> removeAll() async {}
}
