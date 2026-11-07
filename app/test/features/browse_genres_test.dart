import 'package:encore/data/catalogue/catalogue_models.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/features/instant/tap_play.dart' show kPlainServerLine;
import 'package:encore/features/requests/request_providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fake_catalogue.dart';
import '../support/test_app.dart';

/// Found on a friend's phone (2026-10-17): "in the Search screen it is fully
/// empty; usually it shows a grid of genres". The grid came from the genre tags
/// of the library, so a library with no songs, or songs with no tag, gave a
/// blank page. The catalogue knows 24 genres and what is on top in each.
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
    albums: [
      CatalogueAlbum(
        id: '9',
        title: 'Parachutes',
        artistName: 'Coldplay',
        year: 2000,
        recordType: 'album',
      ),
    ],
  );

  Future<({AppDatabase db, FakePlaybackFacade facade, int serverId})> open(
      WidgetTester tester,
      {bool emptyLibrary = false}) async {
    final catalogue = FakeCatalogue()..genreCharts[152] = chart;
    final app = await pumpApp(tester,
        size: const Size(390, 3200),
        overrides: [catalogueClientProvider.overrideWithValue(catalogue)]);
    if (emptyLibrary) {
      await app.db.delete(app.db.tracks).go();
      await app.db.delete(app.db.albums).go();
      await app.db.delete(app.db.artists).go();
    }
    await tester.tap(find.text('Search').last);
    await settle(tester);
    return app;
  }

  testWidgets('a library with no genres still has a grid to browse',
      (tester) async {
    final app = await open(tester, emptyLibrary: true);

    expect(find.text('Browse all'), findsOneWidget);
    for (final genre in const [
      'Pop',
      'Rock',
      'Metal',
      'Jazz',
      'Arabic music'
    ]) {
      expect(find.text(genre), findsOneWidget, reason: genre);
    }
    await closeApp(tester, app.db);
  });

  testWidgets(
      'the library\'s own genres are still there, under their own '
      'heading', (tester) async {
    final app = await open(tester);

    expect(find.text('Browse all'), findsOneWidget);
    await tester.drag(
        find.byType(CustomScrollView).first, const Offset(0, -1500));
    await settle(tester);
    expect(find.text('In your library'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets('a genre opens its top songs, artists and albums',
      (tester) async {
    final app = await open(tester, emptyLibrary: true);

    await tester.tap(find.text('Rock'));
    await settle(tester);

    expect(find.text('Top songs'), findsOneWidget);
    expect(find.text('Sparks'), findsOneWidget);
    expect(find.text('Top artists'), findsOneWidget);
    expect(find.text('Coldplay'), findsWidgets);
    expect(find.text('Top albums'), findsOneWidget);
    expect(find.text('Parachutes'), findsWidgets);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'a song of a genre says so when the server only plays what it has',
      (tester) async {
    final app = await open(tester, emptyLibrary: true);
    await tester.tap(find.text('Rock'));
    await settle(tester);

    await tester.tap(find.text('Sparks'));
    await settle(tester);

    expect(find.text(kPlainServerLine), findsOneWidget,
        reason:
            'no instant-play service in this test: the sentence, no snippet');
    expect(app.facade.calls.where((c) => c.startsWith('streamed')), isEmpty);
    await closeApp(tester, app.db);
  });

  testWidgets('an artist of a genre opens the artist', (tester) async {
    final app = await open(tester, emptyLibrary: true);
    await tester.tap(find.text('Rock'));
    await settle(tester);

    await tester.tap(find.text('Coldplay').first);
    await settle(tester);

    expect(find.text('Popular'), findsOneWidget,
        reason: 'the catalogue artist page');
    await closeApp(tester, app.db);
  });
}
