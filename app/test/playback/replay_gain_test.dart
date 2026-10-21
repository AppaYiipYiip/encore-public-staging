import 'package:encore/playback/replay_gain.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('off is unity', () {
    final p = planReplayGain(mode: ReplayGainMode.off, trackGain: -9);
    expect(p.volume, 1);
    expect(p.boostDb, 0);
  });

  test('a loud track is attenuated by its gain', () {
    final p = planReplayGain(mode: ReplayGainMode.track, trackGain: -6);
    expect(p.volume, closeTo(0.501, 0.001));
    expect(p.boostDb, 0);
  });

  test('track mode falls back to album gain and vice versa', () {
    expect(
      planReplayGain(mode: ReplayGainMode.track, albumGain: -6).volume,
      closeTo(0.501, 0.001),
    );
    expect(
      planReplayGain(mode: ReplayGainMode.album, trackGain: -6).volume,
      closeTo(0.501, 0.001),
    );
  });

  test('album mode prefers album gain', () {
    final p = planReplayGain(
        mode: ReplayGainMode.album, trackGain: -12, albumGain: -6);
    expect(p.volume, closeTo(0.501, 0.001));
  });

  test('a quiet track is boosted, capped at the maximum', () {
    final p = planReplayGain(mode: ReplayGainMode.track, trackGain: 15);
    expect(p.volume, 1);
    expect(p.boostDb, 9);
  });

  test('boost never clips: limited by the track peak', () {
    // peak 0.8 leaves ~1.94 dB of headroom.
    final p = planReplayGain(
        mode: ReplayGainMode.track, trackGain: 6, trackPeak: 0.8);
    expect(p.boostDb, closeTo(1.94, 0.01));
  });

  test('peak above 1.0 forces attenuation even for a positive tag', () {
    final p = planReplayGain(
        mode: ReplayGainMode.track, trackGain: 2, trackPeak: 1.25);
    expect(p.boostDb, 0);
    expect(p.volume, lessThan(1));
  });

  test('preamp shifts the result; untagged uses the fallback', () {
    final p = planReplayGain(
        mode: ReplayGainMode.track, preampDb: -3, untaggedDb: -3);
    expect(p.volume, closeTo(0.501, 0.001), reason: '-3 + -3 dB');
  });

  test('garbage peak values are ignored', () {
    final p =
        planReplayGain(mode: ReplayGainMode.track, trackGain: -4, trackPeak: 0);
    expect(p.volume, closeTo(0.631, 0.001));
  });
}
