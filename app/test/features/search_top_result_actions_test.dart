import 'package:encore/features/common/widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/test_app.dart';

/// N-21 (owner, 13 Nov 2026): the song at the top of a search has the same buttons as every song below it: the "..." menu (play next, add
/// to queue, ...) and the swipes (right = add to queue). The Top result is its own card, but what a song can do is one thing, not a copy.
void main() {
  setUpAll(loadAppFonts);

  Future<void> search(WidgetTester tester, String text) async {
    await tester.tap(find.text('Search').last);
    await settle(tester);
    await tester.enterText(find.byType(TextField), text);
    await tester.pump(const Duration(milliseconds: 600));
    await settle(tester);
  }

  /// The Top result card: the nearest Material around its tap area.
  Finder topCard() => find
      .ancestor(
          of: find.byKey(const Key('top-result')),
          matching: find.byType(Material))
      .first;

  Finder moreIn(Finder of) =>
      find.descendant(of: of, matching: find.byTooltip('More options'));

  testWidgets(
      'the Top result song has the "More options" button like every song row',
      (tester) async {
    final app = await pumpApp(tester);
    await search(tester, 'Opening Kodama');

    expect(
        find.descendant(
            of: find.byKey(const Key('top-result')),
            matching: find.text('Opening Kodama')),
        findsOneWidget,
        reason: 'precondition: the song is the Top result');
    expect(moreIn(topCard()), findsOneWidget);

    await closeApp(tester, app.db);
  });

  testWidgets(
      'its menu is the song menu: play next and add to queue act on the Top result',
      (tester) async {
    final app = await pumpApp(tester);
    await search(tester, 'Opening Kodama');

    await tester.tap(moreIn(topCard()));
    await settle(tester);
    expect(find.text('Play next'), findsOneWidget);
    expect(find.text('Add to queue'), findsOneWidget);
    expect(find.text('Add to playlist'), findsOneWidget);
    expect(find.text('Go to album'), findsOneWidget);

    await tester.tap(find.text('Add to queue'));
    await settle(tester);
    expect(app.facade.calls, contains('queue(al1-t1)'));

    await tester.tap(moreIn(topCard()));
    await settle(tester);
    await tester.tap(find.text('Play next'));
    await settle(tester);
    expect(app.facade.calls, contains('next(al1-t1)'));

    await closeApp(tester, app.db);
  });

  testWidgets(
      'swiping the Top result right adds the song to the queue, like a row below it',
      (tester) async {
    final app = await pumpApp(tester);
    await search(tester, 'Opening Kodama');

    await tester.drag(
        find.byKey(const Key('top-result')), const Offset(300, 0));
    await settle(tester);

    expect(app.facade.calls, contains('queue(al1-t1)'));
    expect(app.facade.calls.where((c) => c.startsWith('playTracks')), isEmpty,
        reason: 'a swipe never starts the song');
    expect(find.byKey(const Key('top-result')), findsOneWidget,
        reason: 'the card snaps back');

    await closeApp(tester, app.db);
  });

  testWidgets(
      'a tap on the Top result still plays the song, a tap on the button does not',
      (tester) async {
    final app = await pumpApp(tester);
    await search(tester, 'Opening Kodama');

    await tester.tap(moreIn(topCard()));
    await settle(tester);
    expect(app.facade.calls.where((c) => c.startsWith('playTracks')), isEmpty);
    // Closes the sheet: a tap on the barrier, in the corner the sheet does not cover.
    await tester.tapAt(
        tester.getTopLeft(find.byType(ModalBarrier).last) + const Offset(5, 5));
    await settle(tester);

    await tester.tap(find.byKey(const Key('top-result')));
    await settle(tester);
    expect(app.facade.calls.where((c) => c.startsWith('playTracks')),
        hasLength(1));

    await closeApp(tester, app.db);
  });

  testWidgets('a long press on the Top result opens the same menu (D-26)',
      (tester) async {
    final app = await pumpApp(tester);
    await search(tester, 'Opening Kodama');

    await tester.longPress(find.byKey(const Key('top-result')));
    await settle(tester);

    expect(find.text('Play next'), findsOneWidget);
    expect(find.text('Add to queue'), findsOneWidget);
    expect(app.facade.calls.where((c) => c.startsWith('playTracks')), isEmpty,
        reason: 'a long press does not start the song');

    await closeApp(tester, app.db);
  });

  testWidgets(
      'the Top result song with its buttons does not overflow at 2x text',
      (tester) async {
    tester.platformDispatcher.textScaleFactorTestValue = 2.0;
    addTearDown(tester.platformDispatcher.clearAllTestValues);
    final app = await pumpApp(tester, size: const Size(360, 700));
    await search(tester, 'Opening Kodama');

    expect(moreIn(topCard()), findsOneWidget);
    expect(tester.takeException(), isNull);

    await closeApp(tester, app.db);
  });

  testWidgets(
      'a Top result that is an artist has no song buttons (nothing to queue)',
      (tester) async {
    final app = await pumpApp(tester);
    await search(tester, 'Opeth');

    expect(
        find.descendant(
            of: find.byKey(const Key('top-result')),
            matching: find.text('Opeth')),
        findsOneWidget,
        reason: 'precondition: the artist is the Top result');
    expect(moreIn(topCard()), findsNothing);

    await closeApp(tester, app.db);
  });

  testWidgets(
      'the same button is on the songs below the Top result (parity guard)',
      (tester) async {
    final app = await pumpApp(tester, size: const Size(390, 1800));
    await search(tester, 'Opening');

    final rows = find.byType(TrackTile);
    expect(rows, findsWidgets, reason: 'songs below the Top result');
    expect(moreIn(rows.first), findsOneWidget);
    expect(moreIn(topCard()), findsOneWidget);

    await closeApp(tester, app.db);
  });
}
