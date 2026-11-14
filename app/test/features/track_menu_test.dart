import 'package:drift/drift.dart' show Value;
import 'package:encore/data/db/app_database.dart';
import 'package:encore/features/common/widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import '../support/test_app.dart';

void main() {
  setUpAll(loadAppFonts);

  Future<void> openAlbum(WidgetTester tester) async {
    final element = tester.element(find.byType(Scaffold).first);
    GoRouter.of(element).go('/home/album/al3');
    await settle(tester);
  }

  Future<void> openFirstTrackMenu(WidgetTester tester) async {
    // The page header has its own "More" button; target the first track row.
    final firstRow = find.byType(TrackTile).first;
    await tester.tap(find.descendant(
        of: firstRow, matching: find.byIcon(Icons.more_vert_rounded)));
    await settle(tester);
  }

  testWidgets('three-dot sheet lists the item actions', (tester) async {
    final app = await pumpApp(tester);
    await openAlbum(tester);
    await openFirstTrackMenu(tester);

    expect(find.text('Play next'), findsOneWidget);
    expect(find.text('Add to queue'), findsOneWidget);
    expect(find.text('Go to album'), findsOneWidget);
    expect(find.text('Go to artist'), findsOneWidget);
    // The seeded first track is liked.
    expect(find.text('Remove from Liked Songs'), findsOneWidget);

    await closeApp(tester, app.db);
  });

  testWidgets('Add to queue calls the playback engine and confirms',
      (tester) async {
    final app = await pumpApp(tester);
    await openAlbum(tester);
    await openFirstTrackMenu(tester);

    await tester.tap(find.text('Add to queue'));
    await settle(tester);

    expect(app.facade.calls, contains('queue(al3-t1)'));
    expect(find.text('Added to queue'), findsOneWidget);

    await closeApp(tester, app.db);
  });

  testWidgets('Play next queues the track after the current one',
      (tester) async {
    final app = await pumpApp(tester);
    await openAlbum(tester);
    await openFirstTrackMenu(tester);

    await tester.tap(find.text('Play next'));
    await settle(tester);

    expect(app.facade.calls, contains('next(al3-t1)'));

    await closeApp(tester, app.db);
  });

  testWidgets('Go to artist navigates and closes the sheet', (tester) async {
    final app = await pumpApp(tester);
    await openAlbum(tester);
    await openFirstTrackMenu(tester);

    await tester.tap(find.text('Go to artist'));
    await settle(tester);

    expect(find.text('Periphery'), findsWidgets);
    expect(find.text('Go to album'), findsNothing, reason: 'sheet closed');
    expect(find.text('Discography'), findsOneWidget);

    await closeApp(tester, app.db);
  });

  testWidgets('swiping a row right adds it to the queue and snaps back',
      (tester) async {
    final app = await pumpApp(tester);
    await openAlbum(tester);

    await tester.drag(find.text('Echoes The').first, const Offset(300, 0));
    await settle(tester);

    expect(app.facade.calls, contains('queue(al3-t2)'));
    expect(find.text('Added to queue'), findsOneWidget);
    expect(find.text('Echoes The'), findsWidgets, reason: 'row must stay');

    await closeApp(tester, app.db);
  });

  testWidgets('a short swipe does not trigger anything', (tester) async {
    final app = await pumpApp(tester);
    await openAlbum(tester);

    await tester.drag(find.text('Echoes The').first, const Offset(40, 0));
    await settle(tester);

    expect(app.facade.calls.where((c) => c.startsWith('queue')), isEmpty);

    await closeApp(tester, app.db);
  });

  testWidgets('tapping a track plays the whole album from that track',
      (tester) async {
    final app = await pumpApp(tester);
    await openAlbum(tester);

    await tester.tap(find.text('Echoes The').first);
    await settle(tester);

    expect(
      app.facade.calls,
      contains('playTracks(5, start=1, source=The Walk, shuffle=false)'),
    );

    await closeApp(tester, app.db);
  });

  // N-12 (the owner's list, 13 Nov 2026): the player opens each artist of a song on its own; the song's menu still offered one.
  testWidgets('a song by several artists offers Go to each of them (N-12)',
      (tester) async {
    final app = await pumpApp(tester);
    await (app.db.update(app.db.tracks)..where((t) => t.id.equals('al3-t1')))
        .write(
            const TracksCompanion(artistsJson: Value('["Periphery","Opeth"]')));
    await openAlbum(tester);
    await openFirstTrackMenu(tester);

    expect(find.text('Go to Periphery'), findsOneWidget);
    expect(find.text('Go to Opeth'), findsOneWidget);
    expect(find.text('Go to artist'), findsNothing,
        reason: 'one line per artist, not one for the first');

    await tester.tap(find.text('Go to Opeth'));
    await settle(tester);

    expect(find.text('Go to album'), findsNothing, reason: 'sheet closed');
    expect(find.text('Discography'), findsOneWidget,
        reason: 'the page of the SECOND artist opened');

    await closeApp(tester, app.db);
  });

  testWidgets(
      'a song with one artist keeps the single Go to artist line (N-12)',
      (tester) async {
    final app = await pumpApp(tester);
    await (app.db.update(app.db.tracks)..where((t) => t.id.equals('al3-t1')))
        .write(const TracksCompanion(artistsJson: Value('["Periphery"]')));
    await openAlbum(tester);
    await openFirstTrackMenu(tester);

    expect(find.text('Go to artist'), findsOneWidget);
    expect(find.text('Go to Periphery'), findsNothing);

    await closeApp(tester, app.db);
  });
}
