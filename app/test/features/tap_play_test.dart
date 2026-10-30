import 'package:encore/features/instant/tap_play.dart';
import 'package:flutter_test/flutter_test.dart';

/// D-24 (AUDIT F33): a tap on a catalogue song means the FULL song. The owner's phone played 30 seconds of everything: the instant-play
/// backend was not ready (the first minutes of a fresh sign-in, or still loading), so a tap silently started a 30-second preview. Now a
/// tap waits for the backend; a preview only comes from a long-press, or on a server KNOWN to be a plain music server where it is all there
/// is. Anything else (an Encore server that cannot get the song, a server not known yet, no address answering) says so in words.
void main() {
  /// Time moves one tick per poll; the fakes read it.
  late int ticks;
  Future<void> tick(Duration _) async => ticks++;

  setUp(() => ticks = 0);

  Future<TapPlan> plan({
    required bool Function(int) instant,
    required bool Function(int) mayStillCome,
    required bool knownPlain,
    Duration timeout = const Duration(seconds: 12),
  }) =>
      planTap(
        instant: () => instant(ticks),
        mayStillCome: () => mayStillCome(ticks),
        knownPlain: () => knownPlain,
        delay: tick,
        timeout: timeout,
      );

  test('the backend is ready: the full song, no waiting', () async {
    final result = await plan(
        instant: (_) => true, mayStillCome: (_) => false, knownPlain: false);

    expect(result, TapPlan.full);
    expect(ticks, 0);
  });

  test(
      'F33: the backend is still loading and comes 500 ms later: the tap waits and plays the FULL song, not the preview',
      () async {
    final result = await plan(
      instant: (t) => t >= 5,
      mayStillCome: (t) => t < 5,
      knownPlain: false,
    );

    expect(result, TapPlan.full);
    expect(ticks, greaterThanOrEqualTo(5), reason: 'it waited');
  });

  test(
      'F33: a fresh sign-in is still finding out it is an Encore server: the tap waits for that, then plays the full song',
      () async {
    final result = await plan(
      instant: (t) => t >= 20,
      mayStillCome: (t) => t < 20,
      knownPlain: false,
    );

    expect(result, TapPlan.full);
  });

  test(
      'an Encore server whose backend does not come says so; it never falls back to a preview',
      () async {
    final result = await plan(
        instant: (_) => false, mayStillCome: (_) => false, knownPlain: false);

    expect(result, TapPlan.cannot);
  });

  test(
      'a server that is still not known after the whole wait gets the sentence, never a preview (no address answered, or too slow)',
      () async {
    final result = await plan(
      instant: (_) => false,
      mayStillCome: (_) => true,
      knownPlain: false,
      timeout: const Duration(seconds: 2),
    );

    expect(result, TapPlan.cannot);
    expect(ticks, lessThanOrEqualTo(25), reason: 'it gave up after the time');
  });

  test(
      'a server KNOWN to be a plain music server has no instant play: the preview is all there is (and the rows say so)',
      () async {
    final result = await plan(
        instant: (_) => false, mayStillCome: (_) => false, knownPlain: true);

    expect(result, TapPlan.preview);
  });

  test(
      'a plain server that answered while the tap waited is a plain server: the preview, after the wait ended early',
      () async {
    // Still being checked for 3 polls, then the answer comes: not Encore.
    final result = await plan(
      instant: (_) => false,
      mayStillCome: (t) => t < 3,
      knownPlain: true,
    );

    expect(result, TapPlan.preview);
    expect(ticks, 3);
  });
}
