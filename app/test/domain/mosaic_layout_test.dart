import 'dart:ui' show Rect;

import 'package:encore/domain/mosaic_layout.dart';
import 'package:flutter_test/flutter_test.dart';

double _area(Rect r) => r.width * r.height;

double _overlap(Rect a, Rect b) {
  final i = a.intersect(b);
  return (i.width <= 0 || i.height <= 0) ? 0 : _area(i);
}

void main() {
  group('MosaicLayout.compute', () {
    for (var n = 1; n <= MosaicLayout.maxTiles; n++) {
      test('$n tile(s) partition the unit square exactly', () {
        final tiles = MosaicLayout.compute(n);

        expect(tiles, hasLength(n));
        // Inside the square.
        for (final t in tiles) {
          expect(t.left, greaterThanOrEqualTo(-1e-9));
          expect(t.top, greaterThanOrEqualTo(-1e-9));
          expect(t.right, lessThanOrEqualTo(1 + 1e-9));
          expect(t.bottom, lessThanOrEqualTo(1 + 1e-9));
          expect(t.width, greaterThan(0));
          expect(t.height, greaterThan(0));
        }
        // No gaps: areas sum to 1.
        expect(
            tiles.fold<double>(0, (s, t) => s + _area(t)), closeTo(1.0, 1e-9));
        // No overlaps.
        for (var i = 0; i < tiles.length; i++) {
          for (var j = i + 1; j < tiles.length; j++) {
            expect(_overlap(tiles[i], tiles[j]), closeTo(0, 1e-9),
                reason: 'tiles $i and $j overlap');
          }
        }
      });

      test('$n tile(s): hero (index 0) is the largest', () {
        final tiles = MosaicLayout.compute(n);
        final maxArea = tiles.map(_area).reduce((a, b) => a > b ? a : b);
        expect(_area(tiles.first), closeTo(maxArea, 1e-12));
      });
    }

    test('is deterministic', () {
      expect(MosaicLayout.compute(7), MosaicLayout.compute(7));
    });

    test('out-of-range counts are clamped', () {
      expect(MosaicLayout.compute(0), hasLength(1));
      expect(MosaicLayout.compute(50), hasLength(MosaicLayout.maxTiles));
    });

    test('golden proportions: the first split is 61.8 / 38.2', () {
      final tiles = MosaicLayout.compute(5);
      final hero = tiles.first;
      // Hero is the major part of a golden cut of the unit square (0.618).
      expect(hero.width, closeTo(0.618, 0.001));
    });
  });

  group('MosaicLayout.pickCovers', () {
    test('most frequent first, distinct, ignoring empties', () {
      final picked =
          MosaicLayout.pickCovers(['a', 'b', null, 'b', '', 'c', 'b', 'a']);
      expect(picked, ['b', 'a', 'c']);
    });

    test('ties keep first-seen order and are capped', () {
      final ids = [for (var i = 0; i < 20; i++) 'id$i'];
      final picked = MosaicLayout.pickCovers(ids, max: 5);
      expect(picked, ['id0', 'id1', 'id2', 'id3', 'id4']);
    });

    test('nothing usable -> empty (caller falls back to gradient)', () {
      expect(MosaicLayout.pickCovers([null, '']), isEmpty);
    });
  });
}
