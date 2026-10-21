import 'dart:ui' show Rect;

/// Deterministic cover-art collage layouts (R-09, ADR-024).
///
/// Returns tiles in the unit square, largest ("hero") first, that partition
/// the square exactly: no gaps, no overlaps. Pure function - no Flutter widgets
/// - so the geometry is property-tested.
///
/// * 1 -> whole square
/// * 2 -> two halves
/// * 3 -> hero (left, 61.8%) + two stacked
/// * 4 -> 2x2 grid
/// * 5..[maxTiles] -> golden guillotine: repeatedly split the largest tile
///   along its longer side at the golden ratio, which yields the Fibonacci-
///   like spiral of ever smaller tiles.
abstract final class MosaicLayout {
  static const double phi = 1.6180339887498949;
  static const double _major = 1 / phi; // 0.618...
  static const int maxTiles = 9;

  static List<Rect> compute(int count) {
    final n = count.clamp(1, maxTiles);
    switch (n) {
      case 1:
        return const [Rect.fromLTWH(0, 0, 1, 1)];
      case 2:
        return const [
          Rect.fromLTWH(0, 0, 0.5, 1),
          Rect.fromLTWH(0.5, 0, 0.5, 1),
        ];
      case 3:
        return const [
          Rect.fromLTWH(0, 0, _major, 1),
          Rect.fromLTWH(_major, 0, 1 - _major, 0.5),
          Rect.fromLTWH(_major, 0.5, 1 - _major, 0.5),
        ];
      case 4:
        return const [
          Rect.fromLTWH(0, 0, 0.5, 0.5),
          Rect.fromLTWH(0.5, 0, 0.5, 0.5),
          Rect.fromLTWH(0, 0.5, 0.5, 0.5),
          Rect.fromLTWH(0.5, 0.5, 0.5, 0.5),
        ];
    }

    final tiles = <Rect>[const Rect.fromLTWH(0, 0, 1, 1)];
    while (tiles.length < n) {
      // Split the largest tile (first wins ties => deterministic).
      var index = 0;
      for (var i = 1; i < tiles.length; i++) {
        if (_area(tiles[i]) > _area(tiles[index]) + 1e-12) index = i;
      }
      final r = tiles.removeAt(index);
      if (r.width >= r.height) {
        final cut = r.width * _major;
        tiles
          ..insert(index, Rect.fromLTWH(r.left, r.top, cut, r.height))
          ..insert(index + 1,
              Rect.fromLTWH(r.left + cut, r.top, r.width - cut, r.height));
      } else {
        final cut = r.height * _major;
        tiles
          ..insert(index, Rect.fromLTWH(r.left, r.top, r.width, cut))
          ..insert(index + 1,
              Rect.fromLTWH(r.left, r.top + cut, r.width, r.height - cut));
      }
    }
    // Hero (largest) first; stable for equal areas.
    final indexed = tiles.asMap().entries.toList()
      ..sort((a, b) {
        final c = _area(b.value).compareTo(_area(a.value));
        return c != 0 ? c : a.key.compareTo(b.key);
      });
    return [for (final e in indexed) e.value];
  }

  static double _area(Rect r) => r.width * r.height;

  /// Picks the distinct cover ids that should appear in a mosaic, most
  /// frequent first (so the hero tile shows the dominant album), capped at
  /// [maxTiles]. [coverIds] may contain nulls/duplicates (one per track).
  static List<String> pickCovers(Iterable<String?> coverIds,
      {int max = maxTiles}) {
    final counts = <String, int>{};
    final firstSeen = <String, int>{};
    var order = 0;
    for (final id in coverIds) {
      if (id == null || id.isEmpty) continue;
      counts.update(id, (v) => v + 1, ifAbsent: () {
        firstSeen[id] = order++;
        return 1;
      });
    }
    final ids = counts.keys.toList()
      ..sort((a, b) {
        final c = counts[b]!.compareTo(counts[a]!);
        return c != 0 ? c : firstSeen[a]!.compareTo(firstSeen[b]!);
      });
    return ids.take(max.clamp(1, maxTiles)).toList();
  }
}
