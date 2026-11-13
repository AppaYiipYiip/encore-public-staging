import 'package:encore/data/catalogue/catalogue_models.dart';
import 'package:encore/data/db/app_database.dart' show AppDatabase;
import 'package:encore/features/common/widgets.dart' show ChipRow;
import 'package:encore/features/requests/request_providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fake_catalogue.dart';
import '../support/test_app.dart';

/// N-22 (the owner, 13 Nov 2026): "after a search, tapping Search again should show the first search page as if nothing had been searched.
/// The same for Home and the other main tabs." The router already went back to a tab's root page on a second tap, but a screen that is
/// still mounted at the root (Search with a typed query, Home and Your Library with a chip chosen or scrolled down) kept what it held.
void main() {
  setUpAll(loadAppFonts);

  const chart = CatalogueGenreChart(
    tracks: [
      CatalogueTrack(
        id: 't1',
        title: 'Sparks',
        artistName: 'Coldplay',
        artistId: '7',
        albumTitle: 'Parachutes',
      ),
    ],
    artists: [CatalogueArtist(id: '7', name: 'Coldplay', fans: 9000000)],
    albums: [],
  );

  /// [tall]: the Search page builds its genre grid lazily, so the tests of Search use a tall screen (as browse_genres_test does); Home and Your
  /// Library use a phone's own height, where they really scroll.
  Future<({AppDatabase db})> open(WidgetTester tester,
      {bool tall = false}) async {
    final catalogue = FakeCatalogue()..genreCharts[152] = chart;
    final app = await pumpApp(tester,
        size: tall ? const Size(390, 3200) : const Size(390, 844),
        overrides: [catalogueClientProvider.overrideWithValue(catalogue)]);
    return (db: app.db);
  }

  Future<void> tapTab(WidgetTester tester, String label) async {
    // The tab bar is the last widget with the label (the page's own title can say the same word).
    await tester.tap(find.text(label).last);
    await settle(tester);
  }

  double offsetOfFirstScrollable(WidgetTester tester) => tester
      .state<ScrollableState>(find.byType(Scrollable).first)
      .position
      .pixels;

  testWidgets(
      'Search: a second tap on the tab clears the query and shows the first page',
      (tester) async {
    final app = await open(tester, tall: true);
    await tapTab(tester, 'Search');
    expect(find.text('Browse all'), findsOneWidget);

    await tester.enterText(find.byType(TextField), 'coldplay');
    await tester.pump(const Duration(milliseconds: 200));
    await settle(tester);
    expect(find.text('Browse all'), findsNothing,
        reason: 'a query is typed: the results replace the browse page');

    await tapTab(tester, 'Search');

    expect(find.text('Browse all'), findsOneWidget,
        reason: 'the first search page, as if nothing had been searched');
    expect(tester.widget<TextField>(find.byType(TextField)).controller!.text,
        isEmpty);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'Search: a second tap while a page of a genre is open returns to the first page',
      (tester) async {
    final app = await open(tester, tall: true);
    await tapTab(tester, 'Search');
    await tester.tap(find.text('Rock'));
    await settle(tester);
    expect(find.text('Top songs'), findsOneWidget);

    await tapTab(tester, 'Search');

    expect(find.text('Top songs'), findsNothing);
    expect(find.text('Browse all'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'Search: a tap on another tab keeps the query (only a second tap on the same tab resets)',
      (tester) async {
    final app = await open(tester, tall: true);
    await tapTab(tester, 'Search');
    await tester.enterText(find.byType(TextField), 'coldplay');
    await tester.pump(const Duration(milliseconds: 200));
    await settle(tester);

    await tapTab(tester, 'Home');
    await tapTab(tester, 'Search');

    expect(tester.widget<TextField>(find.byType(TextField)).controller!.text,
        'coldplay',
        reason: 'leaving a tab and coming back is not a second tap on it');
    await closeApp(tester, app.db);
  });

  testWidgets(
      'Home: a second tap puts the chip back to everything and scrolls to the top',
      (tester) async {
    final app = await open(tester);
    expect(find.byType(ChipRow), findsOneWidget);
    await tester.tap(find.text('Albums').first);
    await settle(tester);
    expect(tester.widget<ChipRow>(find.byType(ChipRow)).selected, 1);
    await tester.drag(
        find.byType(CustomScrollView).first, const Offset(0, -600));
    await settle(tester);
    expect(offsetOfFirstScrollable(tester), greaterThan(0));

    await tapTab(tester, 'Home');
    await settle(tester);

    expect(tester.widget<ChipRow>(find.byType(ChipRow)).selected, isNull);
    expect(offsetOfFirstScrollable(tester), 0);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'Your Library: a second tap puts the chip back to everything and scrolls to the top',
      (tester) async {
    final app = await open(tester);
    await tapTab(tester, 'Your Library');
    expect(find.byType(ChipRow), findsOneWidget);
    await tester.tap(find.text('Artists').first);
    await settle(tester);
    expect(tester.widget<ChipRow>(find.byType(ChipRow)).selected, isNotNull);

    await tapTab(tester, 'Your Library');
    await settle(tester);

    expect(tester.widget<ChipRow>(find.byType(ChipRow)).selected, isNull);
    await closeApp(tester, app.db);
  });
}
