import 'package:encore/features/player/speed_sheet.dart';
import 'package:encore/features/settings/settings_controller.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('labels read naturally', () {
    expect(speedLabel(1), '1x');
    expect(speedLabel(2), '2x');
    expect(speedLabel(1.25), '1.25x');
    expect(speedLabel(1.5), '1.5x');
    expect(speedLabel(0.75), '0.75x');
  });

  test(
      'D-23: a speed saved by an earlier version is dropped, so nobody stays at 1.25x with no way back',
      () async {
    SharedPreferences.setMockInitialValues({'encore.playbackSpeed': 1.25});
    final prefs = await SharedPreferences.getInstance();

    final s = SettingsController.fromPrefs(prefs);

    expect(s.playbackSpeed, 1.0);
  });
}
