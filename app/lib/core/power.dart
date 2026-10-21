import 'package:flutter/services.dart';

/// What the phone's battery and screen are doing right now.
class PowerReading {
  const PowerReading({
    required this.level,
    required this.charging,
    this.powerSave = false,
    this.screenOn = true,
  });

  /// 0..100.
  final int level;
  final bool charging;

  /// Android's battery saver is on.
  final bool powerSave;
  final bool screenOn;
}

/// Reads [PowerReading]s. Behind an interface so the listening log is tested
/// without a phone.
abstract interface class PowerProbe {
  /// `null` when the platform cannot say (desktop, tests).
  Future<PowerReading?> read();
}

/// Asks the Android side (`app.encore/power`).
class MethodChannelPowerProbe implements PowerProbe {
  MethodChannelPowerProbe([MethodChannel? channel])
      : _channel = channel ?? const MethodChannel('app.encore/power');

  final MethodChannel _channel;

  @override
  Future<PowerReading?> read() async {
    try {
      final map = await _channel.invokeMapMethod<String, Object?>('status');
      if (map == null) return null;
      final level = map['level'];
      if (level is! int) return null;
      return PowerReading(
        level: level.clamp(0, 100),
        charging: map['charging'] == true,
        powerSave: map['powerSave'] == true,
        screenOn: map['screenOn'] != false,
      );
    } on MissingPluginException {
      return null;
    } on PlatformException {
      return null;
    }
  }
}
