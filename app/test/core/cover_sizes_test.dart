import 'package:encore/app/providers.dart';
import 'package:encore/core/cover_sizes.dart';
import 'package:flutter_test/flutter_test.dart';

/// A cover is at most two cache entries however many screens show it (E3: it used to be seven, so a cover seen in a row was a
/// letter in the player when offline).
void main() {
  test('every widget size maps to one of two fetch sizes', () {
    final sizes = {for (var px = 1; px <= 2400; px++) CoverSize.forPixels(px)};
    expect(sizes, {CoverSize.small, CoverSize.large});
  });

  test(
      'rows and the mini-player share the small size, cards and the player the large one',
      () {
    expect(CoverSize.forPixels(48 * 3), CoverSize.small,
        reason: 'a 48 dp row cover on a 3x screen');
    expect(CoverSize.forPixels(56 * 2), CoverSize.small);
    expect(CoverSize.forPixels(160 * 3), CoverSize.large, reason: 'a card');
    expect(CoverSize.forPixels(360 * 3), CoverSize.large, reason: 'the player');
  });

  test('the other size is the one that is not asked for', () {
    expect(CoverSize.otherThan(CoverSize.small), CoverSize.large);
    expect(CoverSize.otherThan(CoverSize.large), CoverSize.small);
  });

  test(
      'the resolver fetches and caches by the same key, and names the stand-in',
      () {
    const resolver = CoverArtResolver(serverId: 7);

    final row = resolver.resolve('al-1', 150);
    expect(row.cacheKey, 'cover:7:al-1:${CoverSize.small}');
    expect(
        resolver.alternateKey('al-1', 150), 'cover:7:al-1:${CoverSize.large}');

    final player = resolver.resolve('al-1', 1000);
    expect(player.cacheKey, 'cover:7:al-1:${CoverSize.large}');
    expect(resolver.alternateKey('al-1', 1000), row.cacheKey);
  });

  test('the cache key never carries credentials', () {
    final key =
        const CoverArtResolver(serverId: 1).resolve('mf-9', 300).cacheKey;
    expect(key, isNot(contains('http')));
    expect(key, isNot(contains('=')));
  });
}
