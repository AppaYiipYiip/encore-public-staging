import 'package:drift/drift.dart' show Value;
import 'package:encore/app/providers.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/features/downloads/download_status.dart';
import 'package:encore/features/library/library_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../support/test_app.dart';

/// Owner, 2026-10-22: "the page Downloaded should show me the playlists I downloaded, not all songs downloaded. Even offline I want playlists,
/// depending on whether I am at the gym, driving...". Library > Downloaded lists what the person chose to take along, with how far each is,
/// and offline the Library opens there.
void main() {
  setUpAll(loadAppFonts);
  setUp(() =>
      SharedPreferences.setMockInitialValues({'encore.libraryScope': 'mine'}));

  Future<void> open(WidgetTester tester, String location) async {
    final element = tester.element(find.byType(Scaffold).first);
    GoRouter.of(element).go(location);
    await settle(tester);
  }

  Future<void> pin(
          ({AppDatabase db, FakePlaybackFacade facade, int serverId}) app,
          String type,
          String id) =>
      app.db.into(app.db.pins).insert(PinsCompanion.insert(
            serverId: app.serverId,
            targetType: type,
            targetId: id,
            createdAtMs: 1,
          ));

  Future<void> downloaded(
      ({AppDatabase db, FakePlaybackFacade facade, int serverId}) app,
      Iterable<String> trackIds) async {
    for (final id in trackIds) {
      await app.db.into(app.db.downloads).insert(DownloadsCompanion.insert(
            serverId: app.serverId,
            trackId: id,
            state: const Value(2),
            localPath: Value('/x/$id.opus'),
            bytes: const Value(5 * 1024 * 1024),
            updatedAtMs: 0,
          ));
    }
  }

  Future<void> chooseDownloaded(WidgetTester tester) async {
    // The chip row scrolls sideways: its last chip is off the edge of a phone.
    await tester.ensureVisible(find.text('Downloaded'));
    await tester.pump();
    await tester.tap(find.text('Downloaded'));
    await settle(tester);
  }

  testWidgets(
      'Downloaded lists the playlists and albums that are on the phone, not one heap of songs',
      (tester) async {
    final app = await pumpApp(tester, size: const Size(390, 1400));
    await pin(app, 'playlist', 'pl2'); // Late night: al1-t1, al2-t3, al2-t4
    await downloaded(app, ['al1-t1', 'al2-t3', 'al2-t4']);
    await pin(app, 'playlist', 'pl1'); // Prog Snob: six songs, one on the phone
    await downloaded(app, ['al3-t1']);
    await open(tester, '/library');

    await chooseDownloaded(tester);

    expect(find.text('Late night'), findsOneWidget);
    expect(find.text('Prog Snob'), findsOneWidget);
    expect(find.text('Playlist • Downloaded • 3 songs'), findsOneWidget);
    expect(find.text('Playlist • Downloading 1 of 6'), findsOneWidget);
    expect(find.textContaining('songs on this phone'), findsOneWidget,
        reason: 'the total and the way to the songs are under the list');
    expect(find.text('Liked Songs'), findsNothing,
        reason: 'only what was chosen for the phone');
    expect(find.text('Playlist • 3 songs'), findsNothing);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'on a plain music server a row takes no room for the two stages: it looks exactly as it did',
      (tester) async {
    final app = await pumpApp(tester, size: const Size(390, 1400));
    await pin(app, 'playlist', 'pl2');
    await downloaded(app, ['al1-t1', 'al2-t3', 'al2-t4']);
    await open(tester, '/library');

    await chooseDownloaded(tester);

    expect(find.byType(DownloadStatus), findsWidgets);
    for (final e in tester.elementList(find.byType(DownloadStatus))) {
      expect(tester.getSize(find.byWidget(e.widget)), Size.zero,
          reason: 'nothing to say, so no padding either');
    }
    await closeApp(tester, app.db);
  });

  testWidgets(
      'an album and Liked Songs that are downloaded are listed with their own pictures and words',
      (tester) async {
    final app = await pumpApp(tester, size: const Size(390, 1400));
    await pin(app, 'album', 'al1');
    await pin(app, 'liked', 'liked');
    await open(tester, '/library');

    await chooseDownloaded(tester);

    expect(find.text('Kodama'), findsOneWidget);
    expect(find.textContaining('Album • Alcest'), findsOneWidget);
    expect(find.text('Liked Songs'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets('with nothing chosen it says how to download', (tester) async {
    final app = await pumpApp(tester, size: const Size(390, 1400));
    await open(tester, '/library');

    await chooseDownloaded(tester);

    expect(find.text('Nothing downloaded yet'), findsOneWidget);
    expect(find.textContaining('tap the download arrow'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets('without a connection the Library opens on what is on the phone',
      (tester) async {
    final app = await pumpApp(tester, size: const Size(390, 1400), overrides: [
      networkKindProvider.overrideWith((ref) => Stream.value(NetworkKind.none)),
    ]);
    await pin(app, 'playlist', 'pl2');
    await downloaded(app, ['al1-t1', 'al2-t3', 'al2-t4']);
    await pin(app, 'playlist', 'pl1');
    await open(tester, '/library');
    await settle(tester);

    expect(
        ProviderScope.containerOf(tester.element(find.byType(Scaffold).first))
            .read(libraryFilterProvider),
        LibraryFilter.downloaded);
    expect(find.text('Late night'), findsOneWidget);
    final greyed = tester.widget<Opacity>(find
        .ancestor(of: find.text('Prog Snob'), matching: find.byType(Opacity))
        .first);
    expect(greyed.opacity, lessThan(1),
        reason:
            'Prog Snob has nothing on the phone: without a connection it cannot be played');
    final usable = tester.widget<Opacity>(find
        .ancestor(of: find.text('Late night'), matching: find.byType(Opacity))
        .first);
    expect(usable.opacity, 1);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'online, a person who chose another view is not pulled to Downloaded',
      (tester) async {
    final app = await pumpApp(tester, size: const Size(390, 1400), overrides: [
      networkKindProvider.overrideWith((ref) => Stream.value(NetworkKind.wifi)),
    ]);
    await open(tester, '/library');
    await settle(tester);

    expect(
        ProviderScope.containerOf(tester.element(find.byType(Scaffold).first))
            .read(libraryFilterProvider),
        isNull);
    await closeApp(tester, app.db);
  });
}
