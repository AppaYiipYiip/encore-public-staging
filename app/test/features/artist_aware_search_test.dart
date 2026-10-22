import 'package:encore/data/catalogue/catalogue_models.dart';
import 'package:encore/features/providers.dart' show SearchResults;
import 'package:encore/features/search/artist_aware_search.dart';
import 'package:encore/features/search/search_assembly.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fake_catalogue.dart';

/// "Beach House Space Song" (owner, 2026-10-22): the catalogue's text search lists covers and look-alike titles, never Beach House's own
/// song. The artist is found by name and its popular songs are searched for the title.
const beachHouse = CatalogueArtist(id: 'bh', name: 'Beach House', fans: 298995);
const namesake = CatalogueArtist(id: 'bh2', name: 'Beach House', fans: 9);

CatalogueTrack song(String id, String title, String artist,
        {String? artistId}) =>
    CatalogueTrack(
        id: id, title: title, artistName: artist, artistId: artistId);

/// What the text search returned (all real: covers and an uploader's title).
final textMatches = CatalogueResults(tracks: [
  song('c1', 'Beach House Space Song', 'Cigarettiquette'),
  song('c2', 'Space Song (Beach House Cover)', 'Alles Club'),
  song('c3', 'Beach House Space Song', 'Lee Sang Gul'),
]);

FakeCatalogue catalogue() {
  final c = FakeCatalogue();
  c.artistsByName['beach house'] = [namesake, beachHouse];
  c.topTracksByArtist['bh'] = [
    song('s1', 'Space Song', 'Beach House', artistId: 'bh'),
    song('s2', 'Master of None', 'Beach House', artistId: 'bh'),
    song('s3', 'Silver Soul', 'Beach House', artistId: 'bh'),
  ];
  return c;
}

void main() {
  group('ways to read the typed words', () {
    test('fewer than three words are not split', () {
      expect(artistTitleSplits('radiohead nude'), isEmpty);
      expect(artistTitleSplits('nude'), isEmpty);
    });

    test('the first or the last words are the artist', () {
      final splits = artistTitleSplits('Beach House Space Song')
          .map((s) => '${s.artist}|${s.title.join(' ')}')
          .toList();
      expect(splits, contains('beach house|space song'));
      expect(splits, contains('beach|house space song'));
      expect(splits, contains('song|beach house space'));
      expect(splits, contains('space song|beach house'),
          reason: '"space song beach house" reads the other way round');
      expect(splits.every((s) => s.contains('|')), isTrue);
    });

    test('an artist name is at most three words, and always leaves a title',
        () {
      final splits = artistTitleSplits('a b c');
      expect(
          splits
              .map((s) => s.artist.split(' ').length)
              .reduce((a, b) => a > b ? a : b),
          2);
    });
  });

  group('the artist\'s own song is found', () {
    test(
        'the song of the artist named first, with the artist, ahead of the covers',
        () async {
      final c = catalogue();

      final found =
          await withArtistSongs(c, 'Beach House Space Song', textMatches);

      expect(found.tracks.first.id, 's1');
      expect(found.tracks.first.artistName, 'Beach House');
      expect(found.tracks.map((t) => t.id), containsAll(['c1', 'c2', 'c3']),
          reason: 'what the text search found stays');
      expect(found.artists.first.id, 'bh',
          reason: 'the best known Beach House, not the namesake with 9 fans');
      expect(c.lookups, ['top:bh'], reason: 'one list of songs read');
    });

    test('the artist named last: "space song beach house"', () async {
      final found = await withArtistSongs(
          catalogue(), 'Space Song Beach House', textMatches);

      expect(found.tracks.first.id, 's1');
    });

    test('the top result of the page is that song', () async {
      final found = await withArtistSongs(
          catalogue(), 'Beach House Space Song', textMatches);

      final page = assembleSearch('Beach House Space Song',
          local: const SearchResults(), catalogue: found);

      expect(page.top, isA<SongHit>());
      expect((page.top! as SongHit).title, 'Space Song');
      expect((page.top! as SongHit).artist, 'Beach House');
    });

    test('without the fix the covers would win (what was measured)', () {
      final page = assembleSearch('Beach House Space Song',
          local: const SearchResults(), catalogue: textMatches);

      expect((page.top! as SongHit).artist, isNot('Beach House'));
    });

    test('artists the text search already found are not asked for again',
        () async {
      final c = catalogue();
      final base =
          CatalogueResults(artists: [beachHouse], tracks: textMatches.tracks);

      final found = await withArtistSongs(c, 'Beach House Space Song', base);

      expect(found.tracks.first.id, 's1');
      expect(c.artistSearches, isNot(contains('beach house')));
    });
  });

  group('typing a long query does not ask the same thing again', () {
    test('the same names and the same artist are asked for once', () async {
      final c = catalogue();
      final memory = ArtistLookupCache();

      await withArtistSongs(c, 'Beach House Space Song', textMatches,
          cache: memory);
      final asked = c.artistSearches.length;
      await withArtistSongs(c, 'Beach House Space Song', textMatches,
          cache: memory);
      await withArtistSongs(c, 'Beach House Space Song', textMatches,
          cache: memory);

      expect(c.artistSearches.length, asked);
      expect(c.lookups.where((l) => l == 'top:bh'), hasLength(1));
    });

    test('an answer of nothing is kept only half a minute (it may have failed)',
        () async {
      var now = DateTime(2026, 10, 22, 12);
      final c = FakeCatalogue();
      final memory = ArtistLookupCache(now: () => now);

      await withArtistSongs(c, 'Beach House Space Song', textMatches,
          cache: memory);
      final first = c.artistSearches.length;
      await withArtistSongs(c, 'Beach House Space Song', textMatches,
          cache: memory);
      expect(c.artistSearches.length, first,
          reason: 'the names that found nothing are not asked again at once');

      now = now.add(const Duration(seconds: 31));
      await withArtistSongs(c, 'Beach House Space Song', textMatches,
          cache: memory);
      expect(c.artistSearches.length, first * 2,
          reason: 'but they are asked again after half a minute');
    });
  });

  group('and nothing is spent when it is not needed', () {
    test('a text search that already has a song by the artist is left alone',
        () async {
      final c = catalogue();
      final base = CatalogueResults(tracks: [
        song('g1', 'Silvera', 'Gojira'),
        song('g2', 'Silvera (Live at Hellfest 2016)', 'Gojira'),
      ]);

      final found = await withArtistSongs(c, 'Gojira Silvera', base);

      expect(identical(found, base), isTrue);
      expect(c.artistSearches, isEmpty);
      expect(c.lookups, isEmpty);
    });

    test('two words are the plain search\'s business', () async {
      final c = catalogue();

      final found = await withArtistSongs(c, 'Space Song', textMatches);

      expect(identical(found, textMatches), isTrue);
      expect(c.artistSearches, isEmpty);
    });

    test(
        'a name only a namesake has, with a handful of fans, is not "the artist"',
        () async {
      final c = FakeCatalogue();
      c.artistsByName['beach house'] = [namesake];
      c.topTracksByArtist['bh2'] = [song('x1', 'Space Song', 'Beach House')];

      final found =
          await withArtistSongs(c, 'Beach House Space Song', textMatches);

      expect(identical(found, textMatches), isTrue);
      expect(c.lookups, isEmpty);
    });

    test('a title the artist has no song of changes nothing', () async {
      final c = catalogue();

      final found =
          await withArtistSongs(c, 'Beach House Nonexistent Tune', textMatches);

      expect(identical(found, textMatches), isTrue);
    });
  });
}
