import 'package:cached_network_image/cached_network_image.dart';
import 'package:encore/app/providers.dart';
import 'package:encore/design/theme.dart';
import 'package:encore/design/tokens.dart';
import 'package:encore/features/common/cover_art.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

/// Pictures asked for before the cover ticket has arrived get a placeholder address with the real cache key (so a cached cover still shows).
/// When the ticket comes the address changes but the cache key does not, and an image widget that is only told "same key" would stay as it was:
/// the picture must be asked for again at that moment (docs/tasks P2-20 slice 2).
void main() {
  test('the image provider of one cache key is the same whatever the address',
      () {
    final before = CachedNetworkImageProvider(
        'https://cover-cache.invalid/1/al-1/300',
        cacheKey: 'k');
    final after = CachedNetworkImageProvider(
        'http://home.test/encore/cover/al-1?sig=x',
        cacheKey: 'k');

    expect(before == after, isTrue,
        reason: 'this is why the widget has to be told the ticket came');
  });

  test('a resolver without a ticket says its address is a placeholder', () {
    const without = CoverArtResolver(serverId: 1);

    final r = without.resolve('al-1', 300);

    expect(r.ready, isFalse);
    expect(r.url.host, 'cover-cache.invalid');
  });

  testWidgets(
      'the picture is built again when the ticket arrives, and not at every '
      'rebuild', (tester) async {
    final ready = NotifierProvider<_Flag, bool>(_Flag.new);
    var builds = 0;
    await tester.pumpWidget(ProviderScope(
      overrides: [
        coverArtResolverProvider.overrideWith((ref) {
          builds++;
          return ref.watch(ready)
              ? _Ready(serverId: 1)
              : const CoverArtResolver(serverId: 1);
        }),
      ],
      child: MaterialApp(
        theme:
            buildEncoreTheme(EncoreColors.dark(), brightness: Brightness.dark),
        home: const SizedBox(
            width: 100, height: 100, child: CoverArt(coverArtId: 'al-1')),
      ),
    ));
    final first =
        tester.widget<CachedNetworkImage>(find.byType(CachedNetworkImage)).key;

    final container =
        ProviderScope.containerOf(tester.element(find.byType(CoverArt)));
    container.read(ready.notifier).raise();
    await tester.pump();
    final second =
        tester.widget<CachedNetworkImage>(find.byType(CachedNetworkImage)).key;

    expect(first, const ValueKey<bool>(false));
    expect(second, const ValueKey<bool>(true));
    expect(builds, 2);
  });
}

/// "The ticket has arrived", as a provider the test can turn on.
class _Flag extends Notifier<bool> {
  @override
  bool build() => false;

  void raise() => state = true;
}

/// A resolver whose ticket is there: the address is the real one.
class _Ready extends CoverArtResolver {
  _Ready({required super.serverId});

  @override
  ({Uri url, String cacheKey, bool ready}) resolve(String coverArtId, int px) {
    final base = super.resolve(coverArtId, px);
    return (
      url: Uri.parse('http://home.test/encore/cover/$coverArtId?sig=x'),
      cacheKey: base.cacheKey,
      ready: true,
    );
  }
}
