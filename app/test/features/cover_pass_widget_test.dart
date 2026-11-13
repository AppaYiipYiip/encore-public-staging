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
      'the picture is built again when the ticket arrives and again when it is '
      'renewed (a refused picture must not stay a letter), and not at every '
      'rebuild', (tester) async {
    final ready = NotifierProvider<_Flag, int>(_Flag.new);
    var builds = 0;
    await tester.pumpWidget(ProviderScope(
      overrides: [
        coverArtResolverProvider.overrideWith((ref) {
          builds++;
          final ticket = ref.watch(ready);
          return ticket == 0
              ? const CoverArtResolver(serverId: 1)
              : _Ready(serverId: 1, signature: 'sig$ticket');
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
    container.read(ready.notifier).raise(); // the ticket is renewed
    await tester.pump();
    final third =
        tester.widget<CachedNetworkImage>(find.byType(CachedNetworkImage)).key;
    await tester.pump(); // a rebuild with the same ticket changes nothing
    final again =
        tester.widget<CachedNetworkImage>(find.byType(CachedNetworkImage)).key;

    expect(first, isNot(second), reason: 'the ticket arrived');
    expect(second, isNot(third), reason: 'the ticket was renewed');
    expect(third, again);
    expect(second.toString(), contains('sig1'));
    expect(third.toString(), contains('sig2'));
    expect(builds, 3);
  });
}

/// "A ticket has arrived" (0: none yet; 1, 2: the first and the renewed one), as a provider the test can raise.
class _Flag extends Notifier<int> {
  @override
  int build() => 0;

  void raise() => state = state + 1;
}

/// A resolver whose ticket is there: the address is the real one, written with the ticket's signature.
class _Ready extends CoverArtResolver {
  _Ready({required super.serverId, required this.signature});

  final String signature;

  @override
  ({Uri url, String cacheKey, bool ready}) resolve(String coverArtId, int px) {
    final base = super.resolve(coverArtId, px);
    return (
      url:
          Uri.parse('http://home.test/encore/cover/$coverArtId?sig=$signature'),
      cacheKey: base.cacheKey,
      ready: true,
    );
  }
}
