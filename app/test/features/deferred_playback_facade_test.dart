import 'dart:async';

import 'package:encore/features/player/deferred_playback_facade.dart';
import 'package:encore/features/player/playback_facade.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/test_app.dart';

/// The UI starts before the audio engine is ready; the deferred facade holds
/// the commands until it is. It sits on the start-up path and had no test
/// (docs/23, B13/B14).
void main() {
  late Completer<PlaybackFacade> engine;
  late DeferredPlaybackFacade facade;
  late FakePlaybackFacade inner;

  setUp(() {
    engine = Completer<PlaybackFacade>();
    facade = DeferredPlaybackFacade(engine.future);
    inner = FakePlaybackFacade();
  });

  test('every command pressed before the engine is ready is applied, in order',
      () async {
    facade.toggleShuffle();
    facade.cycleRepeat();
    final paused = facade.pause();
    final played = facade.play();

    engine.complete(inner);
    await Future.wait([paused, played]);

    expect(
        inner.calls, containsAllInOrder(['shuffle', 'repeat', 'pause', 'play']),
        reason: 'shuffle and repeat used to be dropped silently');
  });

  test('a command after the engine is ready goes straight through', () async {
    engine.complete(inner);
    await pumpEventQueue();

    facade.toggleShuffle();

    expect(inner.calls, ['shuffle']);
  });

  test('an engine that fails to start leaves a quiet player and one notice',
      () async {
    final notices = <PlaybackNotice>[];
    facade.notices.listen(notices.add);

    engine.completeError(StateError('could not start'));
    await pumpEventQueue();

    expect(notices, hasLength(1));
    expect(notices.single.isError, isTrue);
    // Commands must not throw into the UI.
    await facade.play();
    await facade.pause();
    facade.toggleShuffle();
    expect(facade.snapshot, PlaybackSnapshot.idle);
  });

  test('disposed before the engine arrives, it never subscribes to it',
      () async {
    await facade.dispose();

    engine.complete(inner);
    await pumpEventQueue();

    expect(inner.hasSnapshotListeners, isFalse,
        reason: 'four subscriptions used to be added after dispose and leak');
  });

  test('a sleep timer already running in the engine is shown once ready',
      () async {
    inner.sleep = const SleepTimerStatus(remaining: Duration(minutes: 20));
    final seen = <SleepTimerStatus>[];
    facade.sleepTimerStream.listen(seen.add);

    engine.complete(inner);
    await pumpEventQueue();

    expect(facade.sleepTimer.remaining, const Duration(minutes: 20));
    expect(seen.map((s) => s.remaining), contains(const Duration(minutes: 20)));
  });
}
