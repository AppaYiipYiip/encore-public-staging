import 'package:encore/data/db/app_database.dart';
import 'package:encore/features/providers.dart' show SearchResults;
import 'package:encore/features/search/search_assembly.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/factories.dart';

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
}
