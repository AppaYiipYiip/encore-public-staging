import 'dart:convert';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:encore/data/catalogue/catalogue_models.dart';
import 'package:encore/data/catalogue/deezer_client.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/domain/search_rank.dart' show songMatch;
import 'package:encore/features/providers.dart' show SearchResults;
import 'package:encore/features/search/search_assembly.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/factories.dart';
import '../support/fake_http.dart';

/// P1-07 (owner, 15 Nov 2026): "searching landmrvk instead of landmrvks shows one of their songs instead of the band".
///
/// Reproduced on the A35: "landmvrk" (the band LANDMVRKS without its last letter) gave Top result = the song "LANDMVRKS - CONCERT 4K -
/// ZÉNITH DE PARIS 2026 - slash musique", a library row of an old import saved with the uploading channel as its artist (N-26, B-125).
/// The song's title starts with the typed word and scored 0.72; the band's name, started and not finished, scored 0.7.
///
/// The rule these tests hold: **a title that begins with "Name - " where Name is an artist that is one of the answers is a song BY that
/// artist: Name counts as an artist word, not as the start of the title, so the artist whose name was typed unfinished is the Top result.**
void main() {
  ArtistRow artist(String id, String name) => ArtistRow(
      serverId: 1,
      id: id,
      name: name,
      albumCount: 1,
      fingerprint: 'f',
      syncRun: 1);

  String top(AssembledSearch page) => switch (page.top) {
        final SongHit s => 'song: ${s.artist} - ${s.title}',
        final ArtistHit a => 'artist: ${a.name}',
        final AlbumHit a => 'album: ${a.title}',
        null => 'nothing',
      };

  const upload =
      'LANDMVRKS - CONCERT 4K - ZÉNITH DE PARIS 2026 - slash musique';

  SearchResults library() => SearchResults(
        artists: [artist('1', 'LANDMVRKS')],
        tracks: [
          trackRow('t1', title: upload, artist: 'slash musique'),
          trackRow('t2', title: 'Scars', artist: 'LANDMVRKS'),
        ],
      );

  group('a name typed unfinished', () {
    test('the band is the Top result, not an upload that repeats its name', () {
      for (final typed in ['landmvrk', 'landmvr', 'landm']) {
        expect(
            top(assembleSearch(typed, local: library())), 'artist: LANDMVRKS',
            reason: typed);
      }
    });

    test(
        'a typo in the unfinished name too: "landmrvk" (typed as the owner typed it) gives the band',
        () {
      expect(top(assembleSearch('landmrvk', local: library())),
          'artist: LANDMVRKS');
    });

    test('the upload is still listed, under the band', () {
      final page = assembleSearch('landmvrk', local: library());

      expect([for (final s in page.songs) s.title], contains(upload));
    });

    test('the song is still the Top result when what was typed is the song',
        () {
      expect(top(assembleSearch('concert 4k zenith', local: library())),
          'song: slash musique - $upload');
    });

    test('with the band not among the answers the upload is ranked as before',
        () {
      final page = assembleSearch('landmvrk',
          local: SearchResults(tracks: [
            trackRow('t1', title: upload, artist: 'slash musique')
          ]));

      expect(top(page), 'song: slash musique - $upload');
    });
  });

  group('an exact name is as it was', () {
    test('"landmvrks" typed in full is the band', () {
      expect(top(assembleSearch('landmvrks', local: library())),
          'artist: LANDMVRKS');
    });
  });

  /// What Deezer really answered for [recorded] (tools/record_deezer_fixtures.py), whatever was typed: the namesake artist
  /// "Hotel California" (7,812 fans) is in the answer for "hotel california".
  Future<CatalogueResults> deezerFor(String recorded, String typed) async {
    final all =
        jsonDecode(File('test/fixtures/deezer/search.json').readAsStringSync())
            as Map<String, dynamic>;
    final adapter = FakeHttpAdapter(routes: {
      for (final kind in ['artist', 'album', 'track'])
        '/search/$kind': (request) => FakeResponse.json(
            {'data': (all[recorded] as Map<String, dynamic>)[kind]}),
    });
    return DeezerClient(
            dio: Dio(BaseOptions(baseUrl: 'https://api.deezer.com'))
              ..httpClientAdapter = adapter)
        .search(typed);
  }

  group('only an artist the song can really be by is taken', () {
    test(
        'a catalogue namesake with a handful of fans does not turn "Song - Suffix" into an upload',
        () async {
      // Deezer lists an ARTIST called "Hotel California" (7,812 fans) next to the song. A library row "Hotel California - Live at the Forum" by
      // Eagles is the song with a suffix and must keep the score it had (0.72 and up), not 0.53.
      const title = 'Hotel California - Live at the Forum';
      final deezer = await deezerFor('hotel california', 'hotel california');

      final page = assembleSearch('hotel california',
          local: SearchResults(
              tracks: [trackRow('1', title: title, artist: 'Eagles')]),
          catalogue: deezer);

      final listed = [
        if (page.top is SongHit) page.top as SongHit,
        ...page.songs,
      ];
      final row = listed.firstWhere((s) => s.title == title,
          orElse: () => fail('the library row is nowhere in the answer: ${[
                for (final s in listed)
                  '${s.artist} - ${s.title} ${s.score.toStringAsFixed(2)}'
              ]}'));
      expect(row.score,
          songMatch('hotel california', artist: 'Eagles', title: title));
      expect(row.score, greaterThan(0.7));
    });

    test(
        'a well known catalogue artist the library does not have counts: "jinj" gives Jinjer, not an upload of the band',
        () async {
      // Jinjer: 100,806 fans, not in this library. The row is an upload filed under its channel.
      final deezer = await deezerFor('jinjer', 'jinj');

      final page = assembleSearch('jinj',
          local: SearchResults(tracks: [
            trackRow('1',
                title: 'Jinjer - Pisces (Official Video)',
                artist: 'Some Music Channel'),
          ]),
          catalogue: deezer);

      expect(top(page), 'artist: Jinjer');
    });

    test('songs of the catalogue are never reread: they name their real artist',
        () async {
      final deezer = await deezerFor('jinjer', 'jinjer');
      final withRule = assembleSearch('jinj',
          local: const SearchResults(), catalogue: deezer);
      final jinjerSongs = [
        for (final s in withRule.songs)
          if (!s.owned) s.score
      ];

      // Every catalogue song keeps the score `songMatch` gives it with no known artist.
      for (final s in withRule.songs.where((s) => !s.owned)) {
        expect(s.score, songMatch('jinj', artist: s.artist, title: s.title),
            reason: s.title);
      }
      expect(jinjerSongs, isNotEmpty);
    });
  });
}
