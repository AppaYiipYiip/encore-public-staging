import 'dart:async';

import 'package:encore/app/providers.dart';
import 'package:encore/core/clock.dart';
import 'package:encore/core/result.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/domain/year_in_music.dart';
import 'package:encore/features/year/year_providers.dart';
import 'package:encore/features/year/year_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import '../support/test_app.dart';

class _Now implements Clock {
  @override
  DateTime now() => DateTime(2026, 10, 17, 15);
}

/// Year in Music, the way a person sees it: the minutes of the year, what they
/// played most, when they listen, and what kind of listener that makes them,
/// each with the number behind it. The plays are those of the seeded library
/// (docs/12, E-61); the arithmetic is in `year_in_music_test.dart`.
void main() {
  setUpAll(loadAppFonts);

  // al4-t2 "Echoes Ghost" (Opeth, 220 s), al1-t1 "Opening Kodama" (Alcest,
  // 200 s), al3-t1 "Opening The" (Periphery, 200 s), al6-t1 (Opeth, 200 s).
  final plays = [
    for (var d = 1; d <= 5; d++)
      Listen('al4-t2', DateTime(2026, 10, d, 23, 10)),
    for (var d = 10; d <= 12; d++) Listen('al1-t1', DateTime(2026, 10, d, 15)),
    Listen('al3-t1', DateTime(2026, 10, 13, 15)),
    Listen('al3-t1', DateTime(2026, 10, 14, 15)),
    Listen('al3-t1', DateTime(2026, 10, 14, 18)), // two on the 14th
    Listen('al4-t2', DateTime(2026, 3, 5, 12)), // this year, not this month
    Listen('al6-t1', DateTime(2025, 6, 1, 12)), // last year
  ];

  Future<({AppDatabase db, FakePlaybackFacade facade, int serverId})> open(
    WidgetTester tester, {
    Future<List<Listen>> Function()? history,
  }) async {
    final app = await pumpApp(tester, size: const Size(390, 3200), overrides: [
      clockProvider.overrideWithValue(_Now()),
      playHistoryProvider
          .overrideWith((ref) => (history ?? () async => plays)()),
    ]);
    final element = tester.element(find.byType(Scaffold).first);
    unawaited(GoRouter.of(element).push<void>('/home/year'));
    await settle(tester);
    await settle(tester);
    return app;
  }

  testWidgets(
      'Home has a card that opens it (the owner: "where do I find it?")',
      (tester) async {
    final app = await pumpApp(tester, size: const Size(390, 1200), overrides: [
      clockProvider.overrideWithValue(_Now()),
      playHistoryProvider.overrideWith((ref) async => plays),
    ]);

    expect(find.text('Your Year in Music'), findsOneWidget);
    await tester.tap(find.text('Your Year in Music'));
    await settle(tester);
    await settle(tester);

    expect(find.byType(YearInMusicScreen), findsOneWidget);
    expect(find.text('42 minutes'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets('the year: minutes, plays, and what was played most',
      (tester) async {
    final app = await open(tester);

    expect(find.text('Year in Music'), findsOneWidget);
    expect(find.text('42 minutes'), findsOneWidget);
    expect(find.textContaining('12 plays'), findsWidgets);
    expect(find.text('Top songs'), findsOneWidget);
    expect(find.text('Echoes Ghost'), findsOneWidget);
    expect(find.text('Top artists'), findsOneWidget);
    expect(find.text('Opeth'), findsWidgets);
    expect(find.text('Top albums'), findsOneWidget);
    expect(find.text('Ghost Reveries'), findsWidgets);
    await closeApp(tester, app.db);
  });

  testWidgets('the two big cards use the whole width of the screen',
      (tester) async {
    // Seen on the phone: both cards were only as wide as their text.
    final app = await open(tester);

    for (final text in ['42 minutes', 'You are a Night Owl']) {
      final card = find
          .ancestor(of: find.text(text), matching: find.byType(Container))
          .first;
      // The card with its side margins: the whole 390 dp of the screen.
      expect(tester.getSize(card).width, 390, reason: text);
    }
    await closeApp(tester, app.db);
  });

  testWidgets('looks the way it was drawn (golden)', (tester) async {
    final app = await open(tester);

    await expectLater(find.byType(YearInMusicScreen),
        matchesGoldenFile('goldens/year_in_music.png'));
    await closeApp(tester, app.db);
  });

  testWidgets('a month, the year and all time can be chosen', (tester) async {
    final app = await open(tester);

    await tester.tap(find.text('This month'));
    await settle(tester);
    expect(find.text('38 minutes'), findsOneWidget,
        reason: 'October only: the play of March is not in it');

    await tester.tap(find.text('All time'));
    await settle(tester);
    expect(find.text('45 minutes'), findsOneWidget,
        reason: 'and the play of last year is');

    await tester.tap(find.text('2026'));
    await settle(tester);
    expect(find.text('42 minutes'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets('says what kind of listener you are, and why', (tester) async {
    final app = await open(tester);

    expect(find.text('You are a Night Owl'), findsOneWidget);
    expect(
        find.textContaining('42% of your listening was between 10 pm and 4 am'),
        findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets('shows the busiest day, the longest streak and the hours',
      (tester) async {
    final app = await open(tester);

    expect(find.text('Your busiest day'), findsOneWidget);
    expect(find.text('Wednesday 14 October'), findsOneWidget,
        reason: 'two plays that day, one on every other');
    expect(find.text('Longest streak'), findsOneWidget);
    expect(find.text('5 days in a row'), findsOneWidget,
        reason: 'the 10th to the 14th of October');
    expect(find.text('When you listen'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets('with nothing played it says so instead of showing zeros',
      (tester) async {
    final app = await open(tester, history: () async => const []);

    expect(find.text('Nothing to count yet'), findsOneWidget);
    expect(find.textContaining('Play some music'), findsOneWidget);
    expect(find.text('0 minutes'), findsNothing);
    await closeApp(tester, app.db);
  });

  testWidgets('while the history is being read it says so', (tester) async {
    final never = Completer<List<Listen>>();
    final app = await pumpApp(tester, size: const Size(390, 3200), overrides: [
      clockProvider.overrideWithValue(_Now()),
      playHistoryProvider.overrideWith((ref) => never.future),
    ]);
    final element = tester.element(find.byType(Scaffold).first);
    unawaited(GoRouter.of(element).push<void>('/home/year'));
    await tester.pump(const Duration(milliseconds: 400));

    expect(
        find.textContaining('Reading your listening history'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets('when the server cannot be reached it says so and can try again',
      (tester) async {
    var asked = 0;
    final app = await open(tester, history: () async {
      asked++;
      if (asked == 1) throw const NetworkFailure('Cannot reach your server');
      return plays;
    });

    expect(find.textContaining('Could not read your listening history'),
        findsOneWidget);
    await tester.tap(find.text('Try again'));
    await settle(tester);
    await settle(tester);

    expect(find.text('42 minutes'), findsOneWidget);
    await closeApp(tester, app.db);
  });
}
