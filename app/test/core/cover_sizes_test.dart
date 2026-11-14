import 'package:encore/app/cover_wiring.dart' show coverBudgetForNetwork;
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

  test(
      'a picture that is an address is fetched as it is and cached once for every size',
      () {
    const resolver = CoverArtResolver(serverId: 7);
    const url = 'https://cdn-images.dzcdn.net/images/cover/abc/1000x1000.jpg';

    final row = resolver.resolve(url, 150);
    final player = resolver.resolve(url, 1000);

    expect(row.url.toString(), url,
        reason: 'it is its own address, with no music-server login on it');
    expect(row.cacheKey, 'url:$url');
    expect(player.cacheKey, row.cacheKey);
    expect(resolver.alternateKey(url, 150), row.cacheKey);
  });

  test('the cache key never carries credentials', () {
    final key =
        const CoverArtResolver(serverId: 1).resolve('mf-9', 300).cacheKey;
    expect(key, isNot(contains('http')));
    expect(key, isNot(contains('=')));
  });

  group('P4-24: one rule for how much of a cover the phone fetches', () {
    test(
        'full: both sizes, a widget gets the size it needs, 600 for the background',
        () {
      expect(CoverBudget.full.sizes, [CoverSize.small, CoverSize.large]);
      expect(CoverBudget.full.fetchSize(160 * 3), CoverSize.large);
      expect(CoverBudget.full.fetchSize(48 * 3), CoverSize.small);
      expect(CoverBudget.full.backgroundLimit, 600);
    });

    test(
        'mobile: the small size only, at most 120 in the background (the rule that was in cover_wiring)',
        () {
      expect(CoverBudget.mobile.sizes, [CoverSize.small]);
      expect(CoverBudget.mobile.fetchSize(360 * 3), CoverSize.small,
          reason: 'even the player asks for the small one');
      expect(CoverBudget.mobile.backgroundLimit, 120);
    });

    test(
        'the background fetch takes its budget from the link, as it always did',
        () {
      expect(coverBudgetForNetwork(NetworkKind.wifi), CoverBudget.full);
      expect(coverBudgetForNetwork(NetworkKind.mobile), CoverBudget.mobile);
    });

    test(
        'the resolver under the mobile budget fetches and caches the small size for every widget',
        () {
      const resolver =
          CoverArtResolver(serverId: 7, budget: CoverBudget.mobile);

      final player = resolver.resolve('al-1', 1000);
      expect(player.cacheKey, 'cover:7:al-1:${CoverSize.small}');
      expect(resolver.alternateKey('al-1', 1000),
          'cover:7:al-1:${CoverSize.large}',
          reason: 'a large cover already on the phone still stands in offline');
    });

    test('without a budget the resolver is exactly what it was', () {
      const resolver = CoverArtResolver(serverId: 7);
      expect(resolver.resolve('al-1', 1000).cacheKey,
          'cover:7:al-1:${CoverSize.large}');
    });
  });
}
