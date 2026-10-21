import 'package:encore/data/catalogue/catalogue_models.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('rankNamesakes', () {
    const tiny = CatalogueArtist(id: '1', name: 'Raid', fans: 4);
    const real = CatalogueArtist(id: '2', name: 'RAID', fans: 36096);
    const other = CatalogueArtist(id: '3', name: 'Radiohead', fans: 4106205);

    test('artists with exactly the name typed come first, the best known first',
        () {
      final ranked = rankNamesakes('raid', [tiny, other, real]);

      expect(ranked.map((a) => a.id), ['2', '1', '3']);
    });

    test(
        'without an exact match the catalogue\'s own order is kept (a typo '
        'correction stays the first hit)', () {
      final ranked = rankNamesakes('radiohed', [other, tiny, real]);

      expect(ranked.map((a) => a.id), ['3', '1', '2']);
    });

    test('case, accents and punctuation do not make a namesake a stranger', () {
      const accent = CatalogueArtist(id: '4', name: 'Raïd!', fans: 900000);

      final ranked = rankNamesakes('RAID', [tiny, accent]);

      expect(ranked.first.id, '4');
    });
  });
}
