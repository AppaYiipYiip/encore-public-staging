import 'dart:async';

import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:encore/app/providers.dart';
import 'package:encore/app/session.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import '../support/fake_http.dart';
import '../support/fake_subsonic_server.dart';
import '../support/test_app.dart';

void main() {
  setUpAll(loadAppFonts);

  /// A real [ServerSession] whose network is an in-memory adapter, so the
  /// whole path UI -> PlaylistMutations -> database -> UI runs for real.
  late FakeHttpAdapter adapter;

  setUp(() {
    adapter = FakeHttpAdapter(routes: {
      'ping': (_) => FakeResponse.json(subsonicOk({})),
      'createPlaylist': (_) => FakeResponse.json(subsonicOk({
            'playlist': {'id': 'srv-new', 'name': 'x'},
          })),
      'updatePlaylist': (_) => FakeResponse.json(subsonicOk({})),
      'deletePlaylist': (_) => FakeResponse.json(subsonicOk({})),
      'getPlaylist': (_) => FakeResponse.json(subsonicOk({
            'playlist': FakeSubsonicServer.playlist('pl1', 'Prog Snob',
                songIds: ['al3-t1', 'al3-t2', 'al4-t1', 'al5-t3', 'al6-t2']),
          })),
    });
  });

  Future<({AppDatabase db, FakePlaybackFacade facade, int serverId})> pump(
    WidgetTester tester,
  ) {
    return pumpApp(
      tester,
      size: const Size(390, 1400),
      session: (ref) async {
        final db = ref.read(databaseProvider);
        final server = (await db.select(db.servers).get()).first;
        final session = await ServerSession.create(
          verifyAddresses: false,
          db: db,
          server: server,
          password: 'x',
          dio: fakeDio(adapter),
        );
        // The app starts the session's sync; stop its timers with the test.
        ref.onDispose(() => unawaited(session.dispose()));
        return session;
      },
    );
  }

  Future<void> open(WidgetTester tester, String location) async {
    final element = tester.element(find.byType(Scaffold).first);
    GoRouter.of(element).go(location);
    await settle(tester);
  }

  Future<List<String>> entries(AppDatabase db, String id) async {
    final rows = await (db.select(db.playlistEntries)
          ..where((e) => e.playlistId.equals(id))
          ..orderBy([(e) => OrderingTerm.asc(e.position)]))
        .get();
    return [for (final e in rows) e.trackId];
  }

  group('add to playlist', () {
    testWidgets('only editable playlists are offered; choosing one adds',
        (tester) async {
      final app = await pump(tester);
      await open(tester, '/home/album/al1');

      // The first song's three-dot menu (index 0 is the page header's).
      await tester.tap(find.byTooltip('More options').at(1));
      await settle(tester);
      await tester.tap(find.text('Add to playlist'));
      await settle(tester);

      expect(find.text('Prog Snob'), findsOneWidget);
      expect(find.text('Late night'), findsOneWidget);
      expect(find.text('Phone Offline'), findsNothing,
          reason: 'server-generated playlists cannot be edited');
      expect(find.text('New playlist'), findsOneWidget);

      await tester.tap(find.text('Late night'));
      await settle(tester);

      expect(await entries(app.db, 'pl2'),
          ['al1-t1', 'al2-t3', 'al2-t4', 'al1-t1']);
      expect(
          find.textContaining('Added 1 song to "Late night"'), findsOneWidget);
      await closeApp(tester, app.db);
    });

    testWidgets('"New playlist" asks for a name and creates it with the song',
        (tester) async {
      final app = await pump(tester);
      await open(tester, '/home/album/al1');

      await tester.tap(find.byTooltip('More options').at(1));
      await settle(tester);
      await tester.tap(find.text('Add to playlist'));
      await settle(tester);
      await tester.tap(find.text('New playlist'));
      await settle(tester);

      await tester.enterText(find.byType(TextField), 'Road trip');
      await tester.tap(find.text('Create'));
      await settle(tester);

      final created = await (app.db.select(app.db.playlists)
            ..where((p) => p.name.equals('Road trip')))
          .getSingle();
      expect(created.owner, 'marwa');
      expect(await entries(app.db, created.id), ['al1-t1']);
      await closeApp(tester, app.db);
    });

    testWidgets('an album can be added to a playlist in one go',
        (tester) async {
      final app = await pump(tester);
      await open(tester, '/home/album/al1');

      await tester.tap(find.byTooltip('More options').first);
      await settle(tester);
      await tester.tap(find.text('Add to playlist'));
      await settle(tester);
      await tester.tap(find.text('Prog Snob'));
      await settle(tester);

      final ids = await entries(app.db, 'pl1');
      expect(ids, hasLength(6 + 5));
      expect(
          ids.sublist(6), ['al1-t1', 'al1-t2', 'al1-t3', 'al1-t4', 'al1-t5']);
      await closeApp(tester, app.db);
    });
  });

  group('editing a playlist page', () {
    testWidgets('remove from this playlist', (tester) async {
      final app = await pump(tester);
      await open(tester, '/home/playlist/pl2');

      await tester.tap(find.byTooltip('More options').at(1));
      await settle(tester);
      await tester.tap(find.text('Remove from this playlist'));
      await settle(tester);

      expect(await entries(app.db, 'pl2'), ['al2-t3', 'al2-t4']);
      await closeApp(tester, app.db);
    });

    testWidgets(
        'remove from this playlist, from a result of "Find in playlist", takes out the entry that was found (N-25)',
        (tester) async {
      final app = await pump(tester);
      await open(tester, '/home/playlist/pl2');

      await tester.tap(find.text('Find in playlist'));
      await settle(tester);
      await tester.enterText(find.byType(TextField), 'hollow');
      await tester.pump(const Duration(milliseconds: 200));
      await settle(tester);
      expect(find.text('Hollow Les'), findsOneWidget);
      expect(find.text('Opening Kodama'), findsNothing);

      // The only "more" button is the found song's: its place in the list is 0, its place in the playlist is 1.
      await tester.tap(find.byTooltip('More options'));
      await settle(tester);
      await tester.tap(find.text('Remove from this playlist'));
      await settle(tester);

      expect(await entries(app.db, 'pl2'), ['al1-t1', 'al2-t4']);
      await closeApp(tester, app.db);
    });

    testWidgets('rename', (tester) async {
      final app = await pump(tester);
      await open(tester, '/home/playlist/pl2');

      await tester.tap(find.byTooltip('More options').first);
      await settle(tester);
      await tester.tap(find.text('Rename playlist'));
      await settle(tester);
      await tester.enterText(find.byType(TextField), 'After hours');
      await tester.tap(find.text('Save'));
      await settle(tester);

      expect(find.text('After hours'), findsWidgets);
      await closeApp(tester, app.db);
    });

    testWidgets('delete asks first, then leaves the page', (tester) async {
      final app = await pump(tester);
      await open(tester, '/home/playlist/pl2');

      await tester.tap(find.byTooltip('More options').first);
      await settle(tester);
      await tester.tap(find.text('Delete playlist'));
      await settle(tester);
      expect(find.text('Delete playlist?'), findsOneWidget);
      await tester.tap(find.text('Delete'));
      await settle(tester);

      final row = await (app.db.select(app.db.playlists)
            ..where((p) => p.id.equals('pl2')))
          .getSingle();
      expect(row.deletedAtMs, isNotNull);
      expect(find.text('Late night'), findsNothing);
      await closeApp(tester, app.db);
    });

    testWidgets('a server-generated playlist offers no editing',
        (tester) async {
      final app = await pump(tester);
      await open(tester, '/home/playlist/pl3');

      await tester.tap(find.byTooltip('More options').at(1));
      await settle(tester);
      expect(find.text('Add to playlist'), findsOneWidget);
      expect(find.text('Remove from this playlist'), findsNothing);
      // Close the sheet and check the page menu too.
      await tester.tapAt(const Offset(10, 10));
      await settle(tester);
      await tester.tap(find.byTooltip('More options').first);
      await settle(tester);
      expect(find.text('Rename playlist'), findsNothing);
      expect(find.text('Delete playlist'), findsNothing);
      await closeApp(tester, app.db);
    });
  });

  group('empty playlist', () {
    testWidgets('invites to add songs and hides pointless menu items',
        (tester) async {
      final app = await pump(tester);
      final id = await (await ProviderScope.containerOf(
                  tester.element(find.byType(Scaffold).first))
              .read(sessionProvider.future))!
          .playlists
          .create('Blank');
      await open(tester, '/home/playlist/$id');

      expect(find.text('Add songs to "Blank"'), findsOneWidget);
      expect(find.text('Find songs'), findsOneWidget);

      await tester.tap(find.byTooltip('More options').first);
      await settle(tester);
      expect(find.text('Play next'), findsNothing);
      expect(find.text('Add to queue'), findsNothing);
      expect(find.text('Rename playlist'), findsOneWidget);
      await closeApp(tester, app.db);
    });
  });

  group('library', () {
    testWidgets('"+" creates an empty playlist and opens it', (tester) async {
      final app = await pump(tester);
      await tester.tap(find.text('Your Library').last);
      await settle(tester);

      await tester.tap(find.byTooltip('Create'));
      await settle(tester);
      expect(find.text('Import from Spotify or YouTube Music'), findsOneWidget);
      await tester.tap(find.text('New playlist'));
      await settle(tester);
      await tester.enterText(find.byType(TextField), 'Fresh start');
      await tester.tap(find.text('Create'));
      await settle(tester);

      final created = await (app.db.select(app.db.playlists)
            ..where((p) => p.name.equals('Fresh start')))
          .getSingle();
      expect(created.songCount, 0);
      expect(find.text('Fresh start'), findsWidgets);
      await closeApp(tester, app.db);
    });

    testWidgets('"+" also leads to importing from Spotify / YouTube Music',
        (tester) async {
      final app = await pump(tester);
      await tester.tap(find.text('Your Library').last);
      await settle(tester);

      await tester.tap(find.byTooltip('Create'));
      await settle(tester);
      await tester.tap(find.text('Import from Spotify or YouTube Music'));
      await settle(tester);

      expect(find.text('Import music'), findsWidgets);
      expect(find.text('Spotify or YouTube Music link(s)'), findsOneWidget);
      await closeApp(tester, app.db);
    });
  });
}
