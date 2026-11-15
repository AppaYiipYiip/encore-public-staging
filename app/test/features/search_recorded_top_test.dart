import 'dart:convert';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:encore/data/catalogue/catalogue_models.dart';
import 'package:encore/data/catalogue/deezer_client.dart';
import 'package:encore/features/providers.dart' show SearchResults;
import 'package:encore/features/search/search_assembly.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/factories.dart';
import '../support/fake_http.dart';

/// The 20 real Deezer answers of 22 Oct 2026 (and "jinjer", 13 Nov), pushed THROUGH `assembleSearch` as the app does (the library's rows, the
/// catalogue's artists, albums and songs, the Top result, the first rows below it): what the person sees for each is pinned in
/// `test/fixtures/deezer/search_assembled_expected.json`. `search_rank_test.dart` calls `songMatch` alone; this is the whole assembly. It was
/// written for P1-07 (15 Nov 2026, a title that begins with an artist's name) and the file was produced by the code BEFORE that change, so a
/// difference is a change of what a person sees: it needs a reason, then the file is written again with `ENCORE_WRITE_EXPECTED=1`.
///
/// Two library scenarios per search: no library, and a library with one "Song - Live at the Forum" row of the first song Deezer lists (the shape
/// the rule of `_leadingArtist` must not turn into an upload).
void main() {
  const expectedPath = 'test/fixtures/deezer/search_assembled_expected.json';
  final recorded =
      jsonDecode(File('test/fixtures/deezer/search.json').readAsStringSync())
          as Map<String, dynamic>;

  Future<CatalogueResults> deezer(String q) => DeezerClient(
          dio: Dio(BaseOptions(baseUrl: 'https://api.deezer.com'))
            ..httpClientAdapter = FakeHttpAdapter(routes: {
              for (final kind in ['artist', 'album', 'track'])
                '/search/$kind': (request) => FakeResponse.json(
                    {'data': (recorded[q] as Map<String, dynamic>)[kind]}),
            }))
      .search(q);

  String describeHit(SearchHit? hit) => switch (hit) {
        final SongHit s => 'song: ${s.artist} - ${s.title}',
        final ArtistHit a => 'artist: ${a.name}',
        final AlbumHit a => 'album: ${a.title}',
        _ => 'nothing',
      };

  Map<String, Object> describe(AssembledSearch page) => {
        'top': describeHit(page.top),
        'songs': [for (final s in page.songs) describeHit(s)],
        'artists': [for (final a in page.artists) describeHit(a)],
        'albums': [for (final a in page.albums) describeHit(a)],
      };

  test('every recorded search shows what it showed before P1-07 (15 Nov)',
      () async {
    final actual = <String, Object>{};
    for (final q in recorded.keys) {
      final catalogue = await deezer(q);
      actual['$q | no library'] = describe(assembleSearch(q,
          local: const SearchResults(), catalogue: catalogue));
      final first = catalogue.tracks.isEmpty ? null : catalogue.tracks.first;
      actual['$q | a live cut in the library'] = describe(assembleSearch(q,
          local: SearchResults(tracks: [
            if (first != null)
              trackRow('lib1',
                  title: '${first.title} - Live at the Forum',
                  artist: first.artistName),
          ]),
          catalogue: catalogue));
    }

    if (Platform.environment['ENCORE_WRITE_EXPECTED'] == '1') {
      File(expectedPath).writeAsStringSync(
          '${const JsonEncoder.withIndent(' ').convert(actual)}\n');
      return;
    }
    final expected = jsonDecode(File(expectedPath).readAsStringSync())
        as Map<String, dynamic>;
    expect(actual.keys.toList(), expected.keys.toList());
    for (final key in actual.keys) {
      expect(jsonDecode(jsonEncode(actual[key])), expected[key], reason: key);
    }
  });
}
