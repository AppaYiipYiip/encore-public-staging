import 'package:dio/dio.dart';
import 'package:drift/drift.dart' show Value;
import 'package:encore/app/connection.dart'
    show ServerReachability, serverReachabilityProvider;
import 'package:encore/app/providers.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/encore/encore_api.dart';
import 'package:encore/data/encore/encore_instant.dart';
import 'package:encore/features/common/playability.dart'
    show kNotAvailableWords;
import 'package:encore/features/common/widgets.dart' show TrackTile;
import 'package:encore/features/instant/instant_controller.dart';
import 'package:encore/features/providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import '../support/fake_encore_server.dart';
import '../support/reachability.dart';
import '../support/test_app.dart';

/// N-32 (the owner, 15 Nov 2026): "I also want the ability to search in my liked playlist". Liked Songs (S-15) is a page of its own and had no
/// "Find in playlist" field, although every playlist has one since N-25 (S-17). Drawn in S-15 as the same field and the same finding, with
/// the words naming the list as Spotify's do ("Find in Liked Songs", "No results for ... in Liked Songs"; a playlist keeps "playlist"): a field
/// between the header lines and the buttons; tapped, it takes the top of the page, narrows the list as the person types with Search's own
/// matching restricted to the liked songs, and a tap on a result plays the WHOLE of Liked Songs from that song's place in it.
///
/// The seeded Liked Songs, in the order of the page (the song liked last first): 0 Opening The (Periphery), 1 Echoes The (Periphery),
/// 2 Opening Ghost (Opeth), 3 Hollow Sky (Katatonia), 4 Echoes Blackwater (Opeth), 5 Tides Kodama (Alcest). The library holds other songs
/// with the same words that are not liked ("Opening Kodama", "Echoes Ghost", ...): they are never found here.
void main() {
  setUpAll(loadAppFonts);

  const fieldWords = 'Find in Liked Songs';
  const noResults = 'No results for "zzzz" in Liked Songs';

  /// The likes of the page: the seed already likes al3-t1 (1700000000000); the others are liked a little earlier each, all at different times, so
  /// the order of the page, and what "from its place" means, is never a tie.
  Future<void> likeSix(AppDatabase db, int serverId) async {
    const ids = ['al3-t2', 'al4-t1', 'al5-t3', 'al6-t2', 'al1-t4'];
    for (final (i, id) in ids.indexed) {
      await (db.update(db.tracks)..where((t) => t.id.equals(id))).write(
          TracksCompanion(starredAtMs: Value(1699999990000 - i * 10000)));
    }
  }

  Future<({AppDatabase db, FakePlaybackFacade facade, int serverId})> open(
      WidgetTester tester,
      {Size size = const Size(390, 1400),
      List<Override> overrides = const [],
      Future<void> Function(AppDatabase db, int serverId)? seed}) async {
    final app = await pumpApp(tester, size: size, overrides: overrides);
    await likeSix(app.db, app.serverId);
    await seed?.call(app.db, app.serverId);
    final element = tester.element(find.byType(Scaffold).first);
    GoRouter.of(element).go('/home/liked');
    await settle(tester);
    return app;
  }

  Future<void> type(WidgetTester tester, String text) async {
    await tester.enterText(find.byType(TextField), text);
    // Search's own short wait before the list follows the letters.
    await tester.pump(const Duration(milliseconds: 200));
    await settle(tester);
  }

  Future<void> openFind(WidgetTester tester) async {
    await tester.tap(find.text(fieldWords));
    await settle(tester);
  }

  const allRows = [
    'Opening The',
    'Echoes The',
    'Opening Ghost',
    'Hollow Sky',
    'Echoes Blackwater',
    'Tides Kodama',
  ];

  // Liked songs of the library that the page does not list because they are not liked, and that the words below would match.
  const notLiked = [
    'Opening Kodama',
    'Echoes Kodama',
    'Echoes Ghost',
    'Opening Blackwater',
  ];

  void expectRows(Iterable<String> shown) {
    for (final title in allRows) {
      expect(find.text(title),
          shown.contains(title) ? findsOneWidget : findsNothing,
          reason: '"$title" ${shown.contains(title) ? 'is' : 'is not'} listed');
    }
    for (final title in notLiked) {
      expect(find.text(title), findsNothing,
          reason: '"$title" is not liked, so it is never on this page');
    }
  }

  testWidgets(
      'Liked Songs with songs has the field between its header lines and its buttons',
      (tester) async {
    final handle = tester.ensureSemantics();
    final app = await open(tester);

    expect(find.text(fieldWords), findsOneWidget);
    expect(find.bySemanticsLabel(fieldWords), findsOneWidget,
        reason: 'a screen reader says the same words as the screen');
    final subtitle = tester.getTopLeft(find.textContaining('6 songs')).dy;
    final field = tester.getTopLeft(find.text(fieldWords)).dy;
    final buttons = tester.getTopLeft(find.byIcon(Icons.shuffle_rounded)).dy;
    expect(field, greaterThan(subtitle));
    expect(field, lessThan(buttons));
    expect(
        tester
            .getSize(find.ancestor(
                of: find.text(fieldWords), matching: find.byType(InkWell)))
            .height,
        greaterThanOrEqualTo(48),
        reason: 'a 48 dp high target');
    await closeApp(tester, app.db);
    handle.dispose();
  });

  testWidgets('empty Liked Songs has no field: there is nothing to find',
      (tester) async {
    final app = await pumpApp(tester, size: const Size(390, 1400));
    // The seeded library likes one song: take the like away.
    await (app.db.update(app.db.tracks))
        .write(const TracksCompanion(starredAtMs: Value(null)));
    GoRouter.of(tester.element(find.byType(Scaffold).first)).go('/home/liked');
    await settle(tester);

    expect(find.text('Songs you like appear here'), findsOneWidget);
    expect(find.text(fieldWords), findsNothing);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'tapped, the field takes the top of the page with the whole list under it and the keyboard asked for',
      (tester) async {
    final app = await open(tester);
    await openFind(tester);

    final field = tester.widget<TextField>(find.byType(TextField));
    expect(field.focusNode!.hasFocus, isTrue);
    expect(field.decoration!.hintText, fieldWords);
    expectRows(allRows);
    expect(find.byIcon(Icons.shuffle_rounded), findsNothing,
        reason: 'the header and its buttons have gone up out of the way');
    expect(find.byTooltip('Clear'), findsNothing, reason: 'nothing to clear');
    await closeApp(tester, app.db);
  });

  testWidgets(
      'the list narrows as the person types, in the order of Liked Songs, among the liked songs only',
      (tester) async {
    final app = await open(tester);
    await openFind(tester);

    await type(tester, 'opeth');
    expectRows(['Opening Ghost', 'Echoes Blackwater']);
    expect(tester.getTopLeft(find.text('Opening Ghost')).dy,
        lessThan(tester.getTopLeft(find.text('Echoes Blackwater')).dy));

    // The album and the start of a word find songs too, as Search does; "Opening Kodama" and "Echoes Kodama" have the album and are not liked.
    await type(tester, 'kod');
    expectRows(['Tides Kodama']);
    await type(tester, 'ECHOES');
    expectRows(['Echoes The', 'Echoes Blackwater']);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'a tap on a result plays the whole of Liked Songs from that song\'s place in it, not only the songs found',
      (tester) async {
    final app = await open(tester);
    await openFind(tester);
    await type(tester, 'opeth');

    await tester.tap(find.text('Echoes Blackwater'));
    await settle(tester);

    expect(app.facade.calls.last,
        'playTracks(6, start=4, source=Liked Songs, shuffle=false)',
        reason: 'the queue is the whole of Liked Songs (6), the start is the '
            'song\'s place in it (4), not its place among the results (1)');
    await closeApp(tester, app.db);
  });

  testWidgets(
      'nothing matches: Search\'s words, naming Liked Songs; clearing brings the list back and keeps the field open',
      (tester) async {
    final app = await open(tester);
    await openFind(tester);

    await type(tester, 'zzzz');
    expectRows(const []);
    expect(find.text(noResults), findsOneWidget);
    expect(
        find.text('Check the spelling, or try fewer words.'), findsOneWidget);

    await tester.tap(find.byTooltip('Clear'));
    await tester.pump(const Duration(milliseconds: 200));
    await settle(tester);
    expectRows(allRows);
    expect(tester.widget<TextField>(find.byType(TextField)).controller!.text,
        isEmpty);
    expect(find.byTooltip('Clear'), findsNothing);
    expect(find.text(noResults), findsNothing);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'a song liked while the finding is open appears, and one unliked goes',
      (tester) async {
    final app = await open(tester);
    await openFind(tester);
    await type(tester, 'kodama');
    expectRows(['Tides Kodama']);

    await (app.db.update(app.db.tracks)..where((t) => t.id.equals('al1-t1')))
        .write(const TracksCompanion(starredAtMs: Value(1699999000000)));
    await settle(tester);
    expect(find.text('Opening Kodama'), findsOneWidget,
        reason: 'the new like is found at once');

    await (app.db.update(app.db.tracks)..where((t) => t.id.equals('al1-t4')))
        .write(const TracksCompanion(starredAtMs: Value(null)));
    await settle(tester);
    expect(find.text('Tides Kodama'), findsNothing);
    expect(find.text('Opening Kodama'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'the arrow closes the finding: the whole page is back and the words are gone',
      (tester) async {
    final app = await open(tester);
    await openFind(tester);
    await type(tester, 'opeth');

    await tester.tap(find.byTooltip('Back'));
    await settle(tester);

    expect(find.byType(TextField), findsNothing);
    expect(find.text(fieldWords), findsOneWidget);
    expect(find.byIcon(Icons.shuffle_rounded), findsOneWidget);
    expectRows(allRows);
    // Opened again, the field is empty.
    await openFind(tester);
    expect(tester.widget<TextField>(find.byType(TextField)).controller!.text,
        isEmpty);
    expectRows(allRows);
    await closeApp(tester, app.db);
  });

  testWidgets('Back (the phone\'s) closes the finding first, then the page',
      (tester) async {
    final app = await open(tester);
    await openFind(tester);
    await type(tester, 'opeth');

    await tester.binding.handlePopRoute();
    await settle(tester);
    expect(find.byType(TextField), findsNothing,
        reason: 'the finding is closed, the person is still on Liked Songs');
    expect(find.text(fieldWords), findsOneWidget);

    await tester.binding.handlePopRoute();
    await settle(tester);
    expect(find.text(fieldWords), findsNothing,
        reason: 'the second Back leaves Liked Songs');
    await closeApp(tester, app.db);
  });

  testWidgets(
      'offline and downloaded in part: the finding works, a song that is not downloaded is grey and says so, and still plays the same way',
      (tester) async {
    final app = await open(tester, overrides: [
      networkKindProvider.overrideWith((ref) => Stream.value(NetworkKind.none)),
      downloadedIdsProvider.overrideWith((ref) => Stream.value({'al3-t1'})),
    ]);
    await openFind(tester);
    await type(tester, 'periphery');

    expectRows(['Opening The', 'Echoes The']);
    expect(find.text('Not downloaded'), findsOneWidget,
        reason: 'only the song that is not on the phone says it');
    expect(find.byIcon(Icons.cloud_off_rounded), findsOneWidget);

    await tester.tap(find.text('Not downloaded'));
    await settle(tester);
    expect(app.facade.calls.last,
        'playTracks(6, start=1, source=Liked Songs, shuffle=false)',
        reason: 'the player itself says "Not downloaded. Connect to play it."');
    await closeApp(tester, app.db);
  });

  testWidgets(
      'a long Liked Songs (800 songs): the rows are built as they scroll in and the right one plays',
      (tester) async {
    final app = await open(tester, seed: (db, serverId) async {
      await db.batch((b) {
        b.insertAll(db.tracks, [
          for (var i = 0; i < 800; i++)
            TracksCompanion.insert(
              serverId: serverId,
              id: 'long-$i',
              title: 'Long song $i',
              artist: const Value('Band'),
              // Liked after the six of the seed, the first of them last: the place of `long-i` is 6 + i.
              starredAtMs: Value(1600000000000 - i),
            ),
        ]);
      });
    });

    await openFind(tester);
    expect(find.byType(TrackTile).evaluate().length, lessThan(30),
        reason: 'only the rows that are on the screen are built');

    await type(tester, 'long 777');
    expect(find.widgetWithText(TrackTile, 'Long song 777'), findsOneWidget);
    expect(find.byType(TrackTile), findsOneWidget);

    await tester.tap(find.byType(TrackTile));
    await settle(tester);
    expect(app.facade.calls.last,
        'playTracks(806, start=783, source=Liked Songs, shuffle=false)');
    await closeApp(tester, app.db);
  });

  testWidgets(
      'closing the finding brings the page back where it was scrolled to',
      (tester) async {
    final app = await open(tester, size: const Size(390, 560));
    double offset() => tester
        .state<ScrollableState>(find.byType(Scrollable).first)
        .position
        .pixels;

    await tester.drag(find.byType(CustomScrollView), const Offset(0, -150));
    await settle(tester);
    final before = offset();
    expect(before, greaterThan(50));

    await openFind(tester);
    await type(tester, 'opeth');
    await tester.tap(find.byTooltip('Back'));
    await settle(tester);

    expect(find.text(fieldWords), findsOneWidget);
    expect(offset(), before);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'the finding page lays out at 2x text and its targets are 48 dp and labelled',
      (tester) async {
    tester.platformDispatcher.textScaleFactorTestValue = 2.0;
    addTearDown(tester.platformDispatcher.clearAllTestValues);
    final handle = tester.ensureSemantics();
    final app = await open(tester);
    await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
    await expectLater(tester, meetsGuideline(labeledTapTargetGuideline));

    await openFind(tester);
    await type(tester, 'opeth');
    expect(tester.takeException(), isNull);
    await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
    await expectLater(tester, meetsGuideline(labeledTapTargetGuideline));

    await type(tester, 'zzzz');
    expect(tester.takeException(), isNull);
    expect(find.text(noResults), findsOneWidget);
    await closeApp(tester, app.db);
    handle.dispose();
  });

  testWidgets(
      'an ordinary playlist that is called "liked" has the field like any playlist, and is not this page',
      (tester) async {
    final handle = tester.ensureSemantics();
    final app = await open(tester, seed: (db, serverId) async {
      await db.into(db.playlists).insert(PlaylistsCompanion.insert(
            serverId: serverId,
            id: 'pl-liked',
            name: 'liked',
            songCount: const Value(2),
            entriesFetchedAtMs: const Value(1700000000000),
          ));
      for (final (i, id) in ['al1-t1', 'al3-t3'].indexed) {
        await db
            .into(db.playlistEntries)
            .insert(PlaylistEntriesCompanion.insert(
              serverId: serverId,
              playlistId: 'pl-liked',
              position: i,
              trackId: id,
            ));
      }
    });
    GoRouter.of(tester.element(find.byType(Scaffold).first))
        .go('/home/playlist/pl-liked');
    await settle(tester);

    // A playlist keeps "playlist" in its words, whatever it is called.
    expect(find.text('Find in playlist'), findsOneWidget);
    expect(find.bySemanticsLabel('Find in playlist'), findsOneWidget);
    expect(find.text(fieldWords), findsNothing);
    expect(find.text('Opening Kodama'), findsOneWidget,
        reason: 'the playlist\'s own songs, which are not liked');
    await tester.tap(find.text('Find in playlist'));
    await settle(tester);
    await type(tester, 'kodama');
    expect(find.text('Opening Kodama'), findsOneWidget);
    expect(find.text('Hollow The'), findsNothing);
    await type(tester, 'zzzz');
    expect(find.text('No results for "zzzz" in this playlist'), findsOneWidget);
    await closeApp(tester, app.db);
    handle.dispose();
  });

  group('B-128 and N-13 inside the finding page', () {
    const sentence =
        'Nothing matching that song was found. Try again in a few days.';
    late FakeEncoreServer server;

    /// A song of the library: a ref of the server, with a file there (or not), liked at [liked].
    Future<String> song(AppDatabase db, int serverId, String title,
        {required int liked, bool file = false}) async {
      final id = server.addRef(title, 'Lofi & Sleep');
      await db.into(db.tracks).insert(TracksCompanion.insert(
            serverId: serverId,
            id: id,
            title: title,
            isRef: const Value(true),
            fileId: Value(file ? 'nd-$title' : null),
            artist: const Value('Lofi & Sleep'),
            artistsJson: const Value('["Lofi & Sleep"]'),
            starredAtMs: Value(liked),
          ));
      return id;
    }

    Finder snack(String text) => find.descendant(
        of: find.byType(SnackBar), matching: find.textContaining(text));

    testWidgets(
        'a found song the server cannot get stays grey with its words; a tap says why, and a tap on another found song plays the whole list without it',
        (tester) async {
      server = FakeEncoreServer();
      late List<String> ids;
      final app = await open(tester, overrides: [
        serverReachabilityProvider
            .overrideWith(() => ReachabilityFrom(() => ServerReachability.ok)),
        instantBackendProvider.overrideWith((ref) async => EncoreInstantBackend(
              api: EncoreApi(
                dio: Dio()..httpClientAdapter = server.adapter,
                baseUrl: () => Uri.parse('http://home.test:4540'),
                auth: () => {'u': 'tester', 't': 'tok', 's': 'salt'},
              ),
              ingest: (_) async {},
            )),
      ], seed: (db, serverId) async {
        server.cannotGet['lofi for focus'] =
            (reason: 'not_found', retryIn: const Duration(days: 7));
        ids = [
          await song(db, serverId, 'Nude', liked: 3000, file: true),
          await song(db, serverId, 'Lofi For Focus', liked: 2000),
          await song(db, serverId, 'Time', liked: 1000, file: true),
        ];
      });
      app.facade.simulateQueue = true;
      await tester.pump(const Duration(seconds: 1));
      await settle(tester);

      await openFind(tester);
      await type(tester, 'lofi');
      await tester.pump(const Duration(seconds: 1));
      await settle(tester);

      expect(find.byType(TrackTile), findsNWidgets(3),
          reason: 'the three songs of the artist, not the six of the seed');
      expect(find.text(kNotAvailableWords), findsOneWidget);
      expect(find.text('Lofi & Sleep'), findsNWidgets(2),
          reason: 'the two songs the server can get keep their artist line');
      expect([for (final q in server.unavailableIdsAsked) ...q],
          everyElement(ids[1]),
          reason: 'only the row with no file is ever asked about');

      await tester.tap(find.text('Lofi For Focus'));
      await settle(tester);
      expect(snack(sentence), findsOneWidget);
      expect(app.facade.calls.where((c) => c.startsWith('playTracks')), isEmpty,
          reason: 'a tap on the grey song says why and plays nothing');

      await tester.pump(const Duration(seconds: 6));
      await tester.tap(find.text('Time'));
      await settle(tester);
      final queue = app.facade.queueState;
      expect([
        for (final item in queue.items) item.id
      ], [
        // The six songs of the seed (none of them found by "lofi"), then the three found, without the grey one.
        'al3-t1', 'al3-t2', 'al4-t1', 'al5-t3', 'al6-t2', 'al1-t4',
        ids[0], ids[2],
      ],
          reason: 'the whole of Liked Songs, including the songs that were not '
              'found, and without the grey one');
      expect(queue.items[queue.currentIndex].id, ids[2],
          reason: 'the list plays on from the song that was tapped');
      await closeApp(tester, app.db);
    });
  });
}
