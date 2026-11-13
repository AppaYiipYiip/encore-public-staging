import 'dart:convert';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:drift/drift.dart' show Value;
import 'package:encore/data/catalogue/catalogue_models.dart';
import 'package:encore/data/catalogue/deezer_client.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/features/providers.dart' show SearchResults;
import 'package:encore/features/requests/request_providers.dart'
    show catalogueClientProvider;
import 'package:encore/features/search/search_assembly.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/factories.dart';
import '../support/fake_catalogue.dart';
import '../support/fake_http.dart';
import '../support/test_app.dart';

/// P1-07 (owner, 13 Nov 2026): searching "jinjer", spelled right, put a song first and not the band.
///
/// The rule these tests hold: **an artist whose name is exactly what was typed is the Top result; a song or an album that only starts
/// with, or contains, the words never takes its place, and only a song or an album that is itself exactly the typed words can, and
/// then only when the artist is barely known** (fewer than [wellKnownFans] fans and not in the library).
void main() {
  setUpAll(loadAppFonts);

  /// What Deezer really answered for "jinjer" (recorded with `tools/record_deezer_fixtures.py`, 13 Nov 2026): the band with 100,806
  /// fans and 29 releases, then its songs.
  late CatalogueResults deezer;
  setUpAll(() async {
    final recorded =
        jsonDecode(File('test/fixtures/deezer/search.json').readAsStringSync())
            as Map<String, dynamic>;
    final adapter = FakeHttpAdapter(routes: {
      for (final kind in ['artist', 'album', 'track'])
        '/search/$kind': (request) => FakeResponse.json({
              'data': (recorded[request.uri.queryParameters['q']]
                  as Map<String, dynamic>)[kind],
            }),
    });
    deezer = await DeezerClient(
            dio: Dio(BaseOptions(baseUrl: 'https://api.deezer.com'))
              ..httpClientAdapter = adapter)
        .search('jinjer');
  });

  String top(AssembledSearch page) => switch (page.top) {
        final SongHit s => 'song: ${s.artist} - ${s.title}',
        final ArtistHit a => 'artist: ${a.name}',
        final AlbumHit a => 'album: ${a.title}',
        null => 'nothing',
      };

  group('the band comes before its songs', () {
    test('Deezer\'s own answer for "jinjer": the band is on top', () {
      final page = assembleSearch('jinjer',
          local: const SearchResults(), catalogue: deezer);

      expect(top(page), 'artist: Jinjer');
      expect(page.songs.first.artist, 'Jinjer',
          reason: 'its songs follow in the list below');
    });

    test(
        'a song of the library whose title carries the band\'s name (how a video list names it) does not take the place',
        () {
      final local = SearchResults(tracks: [
        trackRow('1',
            title: 'Jinjer - Pisces (Official Video)', artist: 'Jinjer'),
        trackRow('2', title: 'Jinjer Live', artist: 'Jinjer'),
      ]);

      final page = assembleSearch('jinjer', local: local, catalogue: deezer);

      expect(top(page), 'artist: Jinjer');
    });

    test(
        'a song of the library with no artist tag, titled "Jinjer", does not either',
        () {
      final local =
          SearchResults(tracks: [trackRow('1', title: 'Jinjer', artist: null)]);

      final page = assembleSearch('jinjer', local: local, catalogue: deezer);

      expect(top(page), 'artist: Jinjer');
    });

    test(
        'a well known band comes before a song somebody else titled exactly like it',
        () {
      final answer = CatalogueResults(
        artists: deezer.artists,
        tracks: [
          const CatalogueTrack(
              id: 'x', title: 'Jinjer', artistName: 'A Cover Act'),
          ...deezer.tracks,
        ],
      );

      final page = assembleSearch('jinjer',
          local: const SearchResults(), catalogue: answer);

      expect(top(page), 'artist: Jinjer');
    });

    test(
        'and so does a band few people follow, over songs that only start with its name',
        () {
      const answer = CatalogueResults(
        artists: [
          CatalogueArtist(id: '1', name: 'Creature', fans: 3000, albumCount: 2)
        ],
        tracks: [
          CatalogueTrack(
              id: '2',
              title: 'Creature Comforts',
              artistName: 'Creature Feature'),
          CatalogueTrack(
              id: '3',
              title: 'Creature Of The Night',
              artistName: 'Creature Feature'),
        ],
      );

      final page = assembleSearch('creature',
          local: const SearchResults(), catalogue: answer);

      expect(top(page), 'artist: Creature');
    });
  });

  group('a song named exactly like the query can still win', () {
    test('when no artist has that name', () {
      const answer = CatalogueResults(
        artists: [
          CatalogueArtist(id: '1', name: 'Creature Feature', fans: 90000)
        ],
        tracks: [
          CatalogueTrack(
              id: '2',
              title: 'Creature Comforts',
              artistName: 'Creature Feature'),
          CatalogueTrack(id: '3', title: 'Creature', artistName: 'Someone'),
        ],
      );

      final page = assembleSearch('creature',
          local: const SearchResults(), catalogue: answer);

      expect(top(page), 'song: Someone - Creature');
    });

    test(
        'when the artist with that name is barely known (an exact title and an exact name tie)',
        () {
      const answer = CatalogueResults(
        artists: [
          CatalogueArtist(
              id: '1', name: 'Hotel California', fans: 7812, albumCount: 1)
        ],
        tracks: [
          CatalogueTrack(
              id: '2', title: 'Hotel California', artistName: 'Eagles'),
        ],
      );

      final page = assembleSearch('hotel california',
          local: const SearchResults(), catalogue: answer);

      expect(top(page), 'song: Eagles - Hotel California');
    });

    test(
        'an exact album still comes before a song that only starts with its title',
        () {
      const answer = CatalogueResults(
        albums: [CatalogueAlbum(id: '1', title: 'Macro', artistName: 'Jinjer')],
        tracks: [
          CatalogueTrack(
              id: '2', title: 'Macro Dose', artistName: 'Macro Dose'),
        ],
      );

      final page = assembleSearch('macro',
          local: const SearchResults(), catalogue: answer);

      expect(top(page), 'album: Macro');
    });
  });

  group('on the search screen', () {
    Future<void> search(WidgetTester tester, String text) async {
      await tester.tap(find.text('Search').last);
      await settle(tester);
      await tester.enterText(find.byType(TextField), text);
      // 90 ms screen debounce + 350 ms catalogue debounce.
      await tester.pump(const Duration(milliseconds: 600));
      await settle(tester);
    }

    testWidgets(
        'the Top result is the band, though the library has a song titled with its name',
        (tester) async {
      final app = await pumpApp(tester, overrides: [
        catalogueClientProvider.overrideWithValue(FakeCatalogue(deezer)),
      ]);
      // The library has the band and a song an import named after the video.
      await app.db.into(app.db.artists).insert(ArtistsCompanion.insert(
          serverId: app.serverId,
          id: 'ar-jinjer',
          name: 'Jinjer',
          albumCount: const Value(1)));
      await app.db.into(app.db.tracks).insert(TracksCompanion.insert(
            serverId: app.serverId,
            id: 'jinjer-t1',
            title: 'Jinjer - Pisces (Official Video)',
            artistId: const Value('ar-jinjer'),
            artist: const Value('Jinjer'),
          ));

      await search(tester, 'jinjer');

      final card = find.byKey(const Key('top-result'));
      expect(card, findsOneWidget);
      expect(find.descendant(of: card, matching: find.text('Jinjer')),
          findsOneWidget);
      expect(find.descendant(of: card, matching: find.textContaining('Artist')),
          findsOneWidget,
          reason: 'the Top result is the artist, not a song');
      expect(find.descendant(of: card, matching: find.textContaining('Song')),
          findsNothing);

      await closeApp(tester, app.db);
    });
  });
}
