import 'package:drift/drift.dart' show Value;
import 'package:encore/app/providers.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/features/common/widgets.dart' show TrackTile;
import 'package:encore/features/providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import '../support/test_app.dart';

/// N-25 (the owner, 13 Nov 2026): "a playlist has no search button, so in a long playlist you cannot find one song". Drawn as S-17 "Find in
/// a playlist" (docs/design): a field between the header lines and the buttons; tapped, it takes the top of the page, narrows the list as
/// the person types with Search's own matching, and a tap on a result plays it from its place in the whole playlist.
///
/// The seeded playlist 'pl1' ("Prog Snob"), by position: 0 Opening The (Periphery), 1 Echoes The (Periphery), 2 Opening Ghost (Opeth),
/// 3 Hollow Sky (Katatonia), 4 Echoes Blackwater (Opeth), 5 Tides Kodama (Alcest).
void main() {
  setUpAll(loadAppFonts);

  const fieldWords = 'Find in playlist';

  Future<({AppDatabase db, FakePlaybackFacade facade, int serverId})> open(
      WidgetTester tester,
      {String playlist = 'pl1',
      Size size = const Size(390, 1400),
      List<Override> overrides = const [],
      Future<void> Function(AppDatabase db, int serverId)? seed}) async {
    final app = await pumpApp(tester, size: size, overrides: overrides);
    await seed?.call(app.db, app.serverId);
    final element = tester.element(find.byType(Scaffold).first);
    GoRouter.of(element).go('/home/playlist/$playlist');
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

  void expectRows(Iterable<String> shown) {
    for (final title in allRows) {
      expect(find.text(title),
          shown.contains(title) ? findsOneWidget : findsNothing,
          reason: '"$title" ${shown.contains(title) ? 'is' : 'is not'} listed');
    }
  }

  testWidgets(
      'a playlist with songs has the field between its header lines and its buttons',
      (tester) async {
    final app = await open(tester);

    expect(find.text(fieldWords), findsOneWidget);
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
  });

  testWidgets('an empty playlist has no field: there is nothing to find',
      (tester) async {
    final app = await pumpApp(tester, size: const Size(390, 1400));
    await app.db.into(app.db.playlists).insert(PlaylistsCompanion.insert(
          serverId: app.serverId,
          id: 'none',
          name: 'Nothing yet',
          songCount: const Value(0),
        ));
    final element = tester.element(find.byType(Scaffold).first);
    GoRouter.of(element).go('/home/playlist/none');
    await settle(tester);

    expect(find.text('This playlist is empty'), findsNothing);
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

  testWidgets('the list narrows as the person types, in playlist order',
      (tester) async {
    final app = await open(tester);
    await openFind(tester);

    await type(tester, 'opeth');
    expectRows(['Opening Ghost', 'Echoes Blackwater']);
    expect(tester.getTopLeft(find.text('Opening Ghost')).dy,
        lessThan(tester.getTopLeft(find.text('Echoes Blackwater')).dy));

    // The album and the start of a word find songs too, as Search does.
    await type(tester, 'kod');
    expectRows(['Tides Kodama']);
    await type(tester, 'ECHOES');
    expectRows(['Echoes The', 'Echoes Blackwater']);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'a tap on a result plays the whole playlist from that song\'s place in it',
      (tester) async {
    final app = await open(tester);
    await openFind(tester);
    await type(tester, 'opeth');

    await tester.tap(find.text('Echoes Blackwater'));
    await settle(tester);

    expect(app.facade.calls.last,
        'playTracks(6, start=4, source=Prog Snob, shuffle=false)',
        reason: 'the queue is the whole playlist, the start is the entry\'s '
            'place in it (4), not its place among the results (1)');
    await closeApp(tester, app.db);
  });

  testWidgets(
      'a song in the playlist twice: each entry is its own row and plays from its own place',
      (tester) async {
    final app =
        await open(tester, playlist: 'twice', seed: (db, serverId) async {
      await db.into(db.playlists).insert(PlaylistsCompanion.insert(
            serverId: serverId,
            id: 'twice',
            name: 'Twice',
            songCount: const Value(4),
            entriesFetchedAtMs: const Value(1700000000000),
          ));
      for (final (i, id) in ['al1-t1', 'al2-t3', 'al1-t1', 'al6-t1'].indexed) {
        await db
            .into(db.playlistEntries)
            .insert(PlaylistEntriesCompanion.insert(
              serverId: serverId,
              playlistId: 'twice',
              position: i,
              trackId: id,
            ));
      }
    });

    await openFind(tester);
    await type(tester, 'Opening Kodama');
    // The typed words are the same text, so the rows are counted as rows.
    final rows = find.widgetWithText(TrackTile, 'Opening Kodama');
    expect(rows, findsNWidgets(2));

    await tester.tap(rows.last);
    await settle(tester);
    expect(app.facade.calls.last,
        'playTracks(4, start=2, source=Twice, shuffle=false)',
        reason: 'the second entry of the song, not the first');
    await closeApp(tester, app.db);
  });

  testWidgets(
      'nothing matches: Search\'s words, naming the playlist; clearing brings the list back and keeps the field open',
      (tester) async {
    final app = await open(tester);
    await openFind(tester);

    await type(tester, 'zzzz');
    expectRows(const []);
    expect(find.text('No results for "zzzz" in this playlist'), findsOneWidget);
    expect(
        find.text('Check the spelling, or try fewer words.'), findsOneWidget);

    await tester.tap(find.byTooltip('Clear'));
    await tester.pump(const Duration(milliseconds: 200));
    await settle(tester);
    expectRows(allRows);
    expect(tester.widget<TextField>(find.byType(TextField)).controller!.text,
        isEmpty);
    expect(find.byTooltip('Clear'), findsNothing);
    expect(find.text('No results for "zzzz" in this playlist'), findsNothing);
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
        reason: 'the finding is closed, the person is still on the playlist');
    expect(find.text(fieldWords), findsOneWidget);

    await tester.binding.handlePopRoute();
    await settle(tester);
    expect(find.text(fieldWords), findsNothing,
        reason: 'the second Back leaves the playlist');
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
        'playTracks(6, start=1, source=Prog Snob, shuffle=false)',
        reason: 'the player itself says "Not downloaded. Connect to play it."');
    await closeApp(tester, app.db);
  });

  testWidgets(
      'a long playlist (800 songs): the rows are built as they scroll in and the right one plays',
      (tester) async {
    final app = await open(tester, playlist: 'big', seed: (db, serverId) async {
      await db.batch((b) {
        b.insertAll(db.tracks, [
          for (var i = 0; i < 800; i++)
            TracksCompanion.insert(
              serverId: serverId,
              id: 'long-$i',
              title: 'Long song $i',
              artist: const Value('Band'),
            ),
        ]);
        b.insert(
            db.playlists,
            PlaylistsCompanion.insert(
              serverId: serverId,
              id: 'big',
              name: 'Big',
              songCount: const Value(800),
              entriesFetchedAtMs: const Value(1700000000000),
            ));
        b.insertAll(db.playlistEntries, [
          for (var i = 0; i < 800; i++)
            PlaylistEntriesCompanion.insert(
              serverId: serverId,
              playlistId: 'big',
              position: i,
              trackId: 'long-$i',
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
        'playTracks(800, start=777, source=Big, shuffle=false)');
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
    expect(find.text('No results for "zzzz" in this playlist'), findsOneWidget);
    await closeApp(tester, app.db);
    handle.dispose();
  });
}
