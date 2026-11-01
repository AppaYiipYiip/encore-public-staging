import 'dart:async';
import 'dart:ui' show Tristate;

import 'package:drift/drift.dart' show Value;
import 'package:encore/app/providers.dart';
import 'package:encore/app/session.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/features/common/download_button.dart';
import 'package:encore/features/common/widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../support/fake_http.dart';
import '../support/test_app.dart';

/// The testing agent's walk (QA-UI-2026-10-31, Q1 and Q2): on an empty playlist the download arrow showed "Downloading..." at 0 % for ever and
/// the playlist was listed in Downloads, and Play and Shuffle looked active and did nothing. A control that cannot do anything must say so.
void main() {
  setUpAll(loadAppFonts);
  setUp(() =>
      SharedPreferences.setMockInitialValues({'encore.libraryScope': 'mine'}));

  late FakeHttpAdapter adapter;

  setUp(() {
    adapter = FakeHttpAdapter(routes: {
      'ping': (_) => FakeResponse.json(subsonicOk({})),
      'createPlaylist': (_) => FakeResponse.json(subsonicOk({
            'playlist': {'id': 'srv-new', 'name': 'x'},
          })),
      'updatePlaylist': (_) => FakeResponse.json(subsonicOk({})),
    });
  });

  Future<({AppDatabase db, FakePlaybackFacade facade, int serverId})> pump(
      WidgetTester tester) {
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

  Future<String> blankPlaylist(WidgetTester tester) async =>
      (await ProviderScope.containerOf(
                  tester.element(find.byType(Scaffold).first))
              .read(sessionProvider.future))!
          .playlists
          .create('Blank');

  group('Q1: the download arrow on an empty playlist', () {
    testWidgets(
        'tells the person there is nothing to download, and never shows a spinner or says "Downloading"',
        (tester) async {
      final handle = tester.ensureSemantics();
      final app = await pump(tester);
      final id = await blankPlaylist(tester);
      await open(tester, '/home/playlist/$id');

      await tester.tap(find.byType(DownloadButton));
      await settle(tester);

      expect(find.textContaining('Downloading Blank'), findsNothing,
          reason: 'there is nothing it could be downloading');
      expect(find.textContaining('Nothing to download yet'), findsOneWidget,
          reason: 'the answer to the tap, in words');
      expect(
          find.descendant(
              of: find.byType(DownloadButton),
              matching: find.byType(CircularProgressIndicator)),
          findsNothing,
          reason: 'a ring that never moves is the phantom download');
      expect(find.bySemanticsLabel(RegExp('^Downloading')), findsNothing);
      // The arrow's own label (the snackbar's sentence ends in a full stop).
      expect(
          find.bySemanticsLabel(RegExp(
              r'^Nothing to download yet\. Songs you add to Blank will download$')),
          findsOneWidget);
      handle.dispose();
      await closeApp(tester, app.db);
    });

    testWidgets(
        'Library > Downloaded lists it as finished: "Nothing to download yet", not "Getting ready"',
        (tester) async {
      final app = await pump(tester);
      final id = await blankPlaylist(tester);
      await open(tester, '/home/playlist/$id');
      await tester.tap(find.byType(DownloadButton));
      await settle(tester);

      await open(tester, '/library');
      await tester.ensureVisible(find.text('Downloaded'));
      await tester.pump();
      await tester.tap(find.text('Downloaded'));
      await settle(tester);

      expect(find.text('Blank'), findsOneWidget);
      expect(find.text('Playlist • Nothing to download yet'), findsOneWidget);
      expect(find.textContaining('Getting ready to download'), findsNothing);
      await closeApp(tester, app.db);
    });
  });

  testWidgets(
      'Settings > Downloads & storage lists it without a progress line that can never finish (Q1)',
      (tester) async {
    final app = await pump(tester);
    final id = await blankPlaylist(tester);
    await open(tester, '/home/playlist/$id');
    await tester.tap(find.byType(DownloadButton));
    await settle(tester);

    await open(tester, '/settings/downloads');

    expect(find.text('Blank'), findsOneWidget);
    expect(find.textContaining('Downloading'), findsNothing);
    expect(find.textContaining(' of 0'), findsNothing);
    await closeApp(tester, app.db);
  });

  group('Q1: a playlist whose songs have not reached the phone yet', () {
    testWidgets(
        'is not told it is empty: the server says it holds songs, so the arrow does not say "Nothing to download"',
        (tester) async {
      final app = await pump(tester);
      await app.db.into(app.db.playlists).insert(PlaylistsCompanion.insert(
          serverId: app.serverId,
          id: 'plLate',
          name: 'Forty songs',
          songCount: const Value(40)));
      await open(tester, '/home/playlist/plLate');

      final button = find.byType(DownloadButton);
      expect(button, findsOneWidget);
      await tester.tap(button);
      await settle(tester);
      expect(find.textContaining('Nothing to download yet'), findsNothing);
      await closeApp(tester, app.db);
    });
  });

  group('Q2: Play and Shuffle on an empty playlist', () {
    testWidgets('look and read as unavailable, and a tap does nothing',
        (tester) async {
      final handle = tester.ensureSemantics();
      final app = await pump(tester);
      final id = await blankPlaylist(tester);
      await open(tester, '/home/playlist/$id');

      final play = find.byType(PlayButton);
      expect(play, findsOneWidget);
      final faded = find.descendant(of: play, matching: find.byType(Opacity));
      expect(faded, findsOneWidget,
          reason: 'a filled green Play that cannot play looks like a bug');
      expect(tester.widget<Opacity>(faded).opacity, lessThan(0.5));
      expect(
          tester.getSemantics(find.bySemanticsLabel('Play')),
          matchesSemantics(
              label: 'Play',
              isButton: true,
              hasEnabledState: true,
              isEnabled: false));
      final shuffle = tester.getSemantics(find.byTooltip('Shuffle'));
      expect(shuffle.getSemanticsData().flagsCollection.isEnabled,
          Tristate.isFalse,
          reason: 'Shuffle is switched off, and a screen reader says so');

      await tester.tap(play, warnIfMissed: false);
      await tester.tap(find.byTooltip('Shuffle'), warnIfMissed: false);
      await settle(tester);
      expect(
          app.facade.calls.where((c) => c.startsWith('playTracks')), isEmpty);
      handle.dispose();
      await closeApp(tester, app.db);
    });

    testWidgets('on a playlist with songs, Play is bright and works',
        (tester) async {
      final app = await pump(tester);
      await open(tester, '/home/playlist/pl2'); // Late night: three songs
      final play = find.byType(PlayButton);
      expect(find.descendant(of: play, matching: find.byType(Opacity)),
          findsNothing,
          reason: 'the dimming is only for a control that cannot act');
      await tester.tap(play);
      await settle(tester);
      expect(app.facade.calls.where((c) => c.startsWith('playTracks')),
          isNotEmpty);
      await closeApp(tester, app.db);
    });
  });
}
