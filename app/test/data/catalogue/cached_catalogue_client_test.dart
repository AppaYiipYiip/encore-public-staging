import 'package:encore/data/catalogue/cached_catalogue_client.dart';
import 'package:encore/data/catalogue/catalogue_models.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_catalogue.dart';

/// Owner, 7 Nov 2026: opening an artist took about 3 seconds, "even if I do it for the same artist multiple times". Every open asked the
/// outside catalogue again; a page that is opened again must come from memory.
void main() {
  const tool = CatalogueArtist(id: '1', name: 'Tool', fans: 5);
  late FakeCatalogue inner;
  late DateTime now;
  late CachedCatalogueClient client;

  setUp(() {
    inner = FakeCatalogue()
      ..artistsById['1'] = tool
      ..artistsByName['tool'] = [tool]
      ..topTracksByArtist['1'] = [
        const CatalogueTrack(
            id: 't1',
            title: 'Sober',
            artistName: 'Tool',
            duration: Duration(seconds: 1)),
      ];
    now = DateTime(2026, 11, 7, 12);
    client = CachedCatalogueClient(inner, now: () => now);
  });

  test('the second look at an artist comes from memory', () async {
    expect((await client.artist('1'))?.name, 'Tool');
    expect((await client.artist('1'))?.name, 'Tool');
    expect((await client.artistTopTracks('1')).length, 1);
    expect((await client.artistTopTracks('1')).length, 1);
    expect(inner.lookups, ['artist:1', 'top:1']);
  });

  test('a search for artists is the same whatever the case or the spaces',
      () async {
    await client.searchArtists('Tool', limit: 8);
    await client.searchArtists(' tool ', limit: 8);
    expect(inner.artistSearches, ['Tool']);
    // another limit is another question
    await client.searchArtists('Tool', limit: 5);
    expect(inner.artistSearches, ['Tool', 'Tool']);
  });

  test('two asks at the same moment share one request', () async {
    final a = client.artist('1');
    final b = client.artist('1');
    expect((await a)?.id, (await b)?.id);
    expect(inner.lookups, ['artist:1']);
  });

  test('an answer is kept half an hour, then asked again', () async {
    await client.artist('1');
    now = now.add(const Duration(minutes: 29));
    await client.artist('1');
    expect(inner.lookups, ['artist:1']);
    now = now.add(const Duration(minutes: 2));
    await client.artist('1');
    expect(inner.lookups, ['artist:1', 'artist:1']);
  });

  test(
      'an answer of nothing is kept only half a minute: an unreachable catalogue looks the same and must not stick',
      () async {
    expect(await client.artist('2'), isNull);
    await client.artist('2');
    expect(inner.lookups, ['artist:2'],
        reason: 'asked once inside the half minute');

    inner.artistsById['2'] =
        const CatalogueArtist(id: '2', name: 'Back online');
    now = now.add(const Duration(seconds: 31));
    expect((await client.artist('2'))?.name, 'Back online');
  });

  test('a request that throws is forgotten at once and the error goes on',
      () async {
    final failing = _Throwing();
    final c = CachedCatalogueClient(failing, now: () => now);
    await expectLater(c.artist('1'), throwsStateError);
    failing.fail = false;
    expect((await c.artist('1'))?.name, 'Tool');
    expect(failing.asked, 2);
  });

  test('the oldest answers go first when the memory is full', () async {
    final small = CachedCatalogueClient(inner, most: 2, now: () => now);
    await small.artist('1');
    await small.artist('2');
    await small.artist('3'); // pushes '1' out
    await small.artist('2'); // still known
    await small.artist('1'); // asked again
    expect(inner.lookups, ['artist:1', 'artist:2', 'artist:3', 'artist:1']);
  });

  test('the text search and the charts are not remembered', () async {
    await client.search('tool');
    await client.search('tool');
    expect(inner.queries, ['tool', 'tool']);
    await client.genreChart(1);
    await client.genreChart(1);
    expect(inner.lookups, ['genre:1', 'genre:1']);
  });

  test('the releases of an artist are kept per limit and name', () async {
    await client.artistAlbums('1', artistName: 'Tool', limit: 50);
    await client.artistAlbums('1', artistName: 'Tool', limit: 50);
    await client.artistAlbums('1', artistName: 'Tool');
    expect(inner.lookups, ['albums:1', 'albums:1']);
  });
}

class _Throwing implements CatalogueClient {
  bool fail = true;
  int asked = 0;

  @override
  Future<CatalogueArtist?> artist(String artistId) async {
    asked++;
    if (fail) throw StateError('network');
    return const CatalogueArtist(id: '1', name: 'Tool');
  }

  @override
  dynamic noSuchMethod(Invocation invocation) =>
      throw UnimplementedError('${invocation.memberName}');
}
