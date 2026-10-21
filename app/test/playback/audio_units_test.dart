import 'package:encore/playback/audio_units.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('real dB is a tenth of the plugin unit', () {
    // just_audio multiplies by 1000 to get millibels (100 per dB).
    expect(toPlatformGain(4), closeTo(0.4, 1e-9));
    expect(toPlatformGain(15), closeTo(1.5, 1e-9));
    expect(toPlatformGain(-12), closeTo(-1.2, 1e-9));
  });

  test('conversion round-trips', () {
    for (final db in [-15.0, -6.5, 0.0, 3.0, 9.0]) {
      expect(fromPlatformGain(toPlatformGain(db)), closeTo(db, 1e-9));
    }
  });

  test('a 9 dB boost reaches the platform as 900 millibels', () {
    final millibels = toPlatformGain(9) * 1000;
    expect(millibels.round(), 900);
  });
}
