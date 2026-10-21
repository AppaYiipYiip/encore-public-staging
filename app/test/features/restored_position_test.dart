import 'package:encore/features/player/playback_facade.dart';
import 'package:encore/features/providers.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/test_app.dart';

/// A song the app was killed on comes back paused where it was (J-11): the
/// scrubber must show that position at once, not 0:00 until the song is
/// played again.
void main() {
  PlaybackSnapshot paused(Duration at) => PlaybackSnapshot(
        track: const NowPlayingTrack(id: 'song-1', title: 'Low Life'),
        position: at,
        duration: const Duration(minutes: 5, seconds: 23),
      );

  test('the position shows what the player already knows, before it plays',
      () async {
    final facade = FakePlaybackFacade(paused(const Duration(minutes: 2)));
    final container = ProviderContainer(overrides: [
      playbackFacadeProvider.overrideWithValue(facade),
    ]);
    addTearDown(container.dispose);
    final sub = container.listen(playbackPositionProvider, (_, __) {});
    addTearDown(sub.close);

    expect(await container.read(playbackPositionProvider.future),
        const Duration(minutes: 2));
  });

  test('and then follows the player', () async {
    final facade = FakePlaybackFacade(paused(const Duration(minutes: 2)));
    final container = ProviderContainer(overrides: [
      playbackFacadeProvider.overrideWithValue(facade),
    ]);
    addTearDown(container.dispose);
    final sub = container.listen(playbackPositionProvider, (_, __) {});
    addTearDown(sub.close);
    await container.read(playbackPositionProvider.future);
    await pumpEventQueue(); // the provider is now listening for positions

    facade.emitPosition(const Duration(minutes: 2, seconds: 5));
    await pumpEventQueue();

    expect(container.read(playbackPositionProvider).value,
        const Duration(minutes: 2, seconds: 5));
  });
}
