import 'package:encore/app/providers.dart';
import 'package:encore/data/catalogue/catalogue_models.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/features/catalogue/catalogue_providers.dart';
import 'package:encore/features/providers.dart';
import 'package:encore/features/requests/request_providers.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fake_catalogue.dart';

/// Owner, 7 Nov 2026: the page of an artist took about 3 seconds. Which catalogue artist is "this" library artist is worked out with as
/// few requests as possible: one search for artists (not the full search of three), and the releases of namesakes asked together.
void main() {
  ArtistRow artist(String id, String name) => ArtistRow(
      serverId: 1,
      id: id,
      name: name,
      albumCount: 1,
      fingerprint: 'f',
      syncRun: 1);

  AlbumRow album(String id, String name) => AlbumRow(
      serverId: 1,
      id: id,
      name: name,
      songCount: 1,
      durationSec: 100,
      isCompilation: false,
      fingerprint: 'f',
      syncRun: 1);

  CatalogueAlbum released(String id, String title, String artistId) =>
      CatalogueAlbum(
          id: id, title: title, artistName: 'Raid', artistId: artistId);

  Future<CatalogueArtist?> lookup(
      FakeCatalogue catalogue, String artistName, List<AlbumRow> mine) async {
    final container = ProviderContainer(overrides: [
      networkKindProvider.overrideWith((ref) => Stream.value(NetworkKind.wifi)),
      catalogueClientProvider.overrideWithValue(catalogue),
      artistProvider('a1')
          .overrideWith((ref) => Stream.value(artist('a1', artistName))),
      artistAlbumsProvider('a1').overrideWith((ref) => Stream.value(mine)),
    ]);
    addTearDown(container.dispose);
    container.listen(libraryArtistCatalogueProvider('a1'), (_, __) {});
    await container.read(networkKindProvider.future);
    return container.read(libraryArtistCatalogueProvider('a1').future);
  }

  test('one artist of that name: one search for artists, nothing else',
      () async {
    final catalogue = FakeCatalogue()
      ..artistsByName['tool'] = [
        const CatalogueArtist(id: '1', name: 'Tool', fans: 5),
        const CatalogueArtist(id: '9', name: 'Tool Time', fans: 1),
      ];
    final found = await lookup(catalogue, 'Tool', const []);

    expect(found?.id, '1');
    expect(catalogue.artistSearches, ['Tool']);
    expect(catalogue.queries, isEmpty,
        reason: 'the full search (artists, albums, songs) is not asked');
    expect(catalogue.lookups, isEmpty);
  });

  test(
      'namesakes: the one whose releases overlap the library wins, and their releases are asked for together',
      () async {
    final catalogue = FakeCatalogue()
      ..artistsByName['raid'] = [
        const CatalogueArtist(id: 'r1', name: 'Raid', fans: 36000),
        const CatalogueArtist(id: 'r2', name: 'Raid', fans: 10),
      ]
      ..albumsByArtist['r1'] = [released('x1', 'Somebody Else', 'r1')]
      ..albumsByArtist['r2'] = [released('x2', 'My Album', 'r2')];
    final found = await lookup(catalogue, 'Raid', [album('al1', 'My Album')]);

    expect(found?.id, 'r2', reason: 'the namesake with an album in common');
    expect(catalogue.lookups, unorderedEquals(['albums:r1', 'albums:r2']));
    expect(catalogue.queries, isEmpty);
  });

  test('no namesake with an overlap: the best known one', () async {
    final catalogue = FakeCatalogue()
      ..artistsByName['raid'] = [
        const CatalogueArtist(id: 'r2', name: 'Raid', fans: 10),
        const CatalogueArtist(id: 'r1', name: 'Raid', fans: 36000),
      ];
    final found = await lookup(catalogue, 'Raid', [album('al1', 'My Album')]);
    expect(found?.id, 'r1');
  });

  test('nobody of that name: nothing, not a guess', () async {
    final catalogue = FakeCatalogue()
      ..artistsByName['nobody'] = [
        const CatalogueArtist(id: '5', name: 'Nobody Else'),
      ];
    expect(await lookup(catalogue, 'Nobody', const []), isNull);
  });
}
