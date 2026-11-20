import 'package:encore/data/repos/downloads_repository.dart';
import 'package:encore/features/downloads/download_providers.dart';
import 'package:encore/features/instant/release_save.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

/// N-39, review of PR 119: when is a catalogue release (one pin for each of its songs) STOPPED? The person's Stop flags every song of it, and a song the
/// person asks for on its own afterwards (the track menu) is a new request: its pin is not stopped and it starts by itself, while the other songs still
/// wait. The release must then say Stopped and offer Resume (it used to say "downloading" with a Stop and no Resume, with the held songs waiting for ever).
void main() {
  PinState song({
    bool pinned = true,
    bool stopped = false,
    int done = 0,
    int active = 1,
  }) =>
      PinState(
          pinned: pinned,
          total: 1,
          done: done,
          active: active,
          stopped: stopped);

  Future<PinState> releaseOf(Map<String, PinState> songs) async {
    final c = ProviderContainer(overrides: [
      pinStateProvider.overrideWith(
          (ref, key) => Stream.value(songs[key.$2] ?? PinState.none)),
    ]);
    addTearDown(c.dispose);
    final joined = songs.keys.join(',');
    c.listen(releasePinStateProvider(joined), (_, __) {});
    for (final id in songs.keys) {
      c.listen(pinStateProvider((PinTargetType.track, id)), (_, __) {});
    }
    await Future<void>.delayed(const Duration(milliseconds: 10));
    return c.read(releasePinStateProvider(joined));
  }

  test(
      'N-39: a release is stopped when ANY of its pinned songs is held, also when one was asked for on its own afterwards',
      () async {
    final state = await releaseOf({
      'sr_1': song(stopped: true),
      'sr_2': song(stopped: true),
      'sr_3': song(), // pinned on its own from the track menu: going
    });

    expect(state.stopped, isTrue);
    expect(state.phase, PinPhase.stopped,
        reason: 'the line says Stopped and offers Resume, not Stop');
    expect(state.total, 3);
  });

  test("N-39: one held song among going ones is still a held song", () async {
    final state = await releaseOf({
      'sr_1': song(),
      'sr_2': song(stopped: true),
      'sr_3': song(),
    });

    expect(state.phase, PinPhase.stopped);
  });

  test(
      'N-39: a release none of whose songs is stopped is not stopped, and a song that is not pinned does not make it one',
      () async {
    final going = await releaseOf({
      'sr_1': song(),
      'sr_2': song(),
      'sr_3': song(pinned: false, active: 0),
    });
    expect(going.stopped, isFalse);
    expect(going.phase, PinPhase.downloading);

    final nothing = await releaseOf({
      'sr_1': song(pinned: false, active: 0),
      'sr_2': song(pinned: false, active: 0),
    });
    expect(nothing.stopped, isFalse);
    expect(nothing.pinned, isFalse);
  });

  test(
      'N-39: a release that has every song is complete, whatever a pin of it says',
      () async {
    final state = await releaseOf({
      'sr_1': song(done: 1, active: 0, stopped: true),
      'sr_2': song(done: 1, active: 0),
    });

    expect(state.phase, PinPhase.complete);
  });
}
