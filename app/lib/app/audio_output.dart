import 'package:flutter/services.dart';

import '../core/logger.dart';

/// Opens the system's audio output chooser (speaker / headset / Bluetooth /
/// Audio Sharing on Android 16). Playback routing is an OS concern; the app
/// only needs to put the right switcher one tap away.
abstract final class AudioOutput {
  static const MethodChannel _channel =
      MethodChannel('app.encore/audio_output');

  /// Returns `true` when a system switcher was shown.
  static Future<bool> showSwitcher() async {
    try {
      return await _channel.invokeMethod<bool>('showOutputSwitcher') ?? false;
    } on PlatformException catch (error) {
      Log.warn('audio', 'output switcher unavailable', error.message);
      return false;
    } on MissingPluginException {
      return false;
    }
  }
}
