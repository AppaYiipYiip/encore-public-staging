import 'package:flutter/services.dart';

import '../../core/logger.dart';

/// Free space of the volume downloads are written to.
abstract interface class DiskSpace {
  /// Bytes available to this app, or `null` when the platform cannot tell
  /// (the storage guard then only enforces the user's cap).
  Future<int?> freeBytes();
}

/// Android: `StatFs` on the app's files directory (the volume downloads use),
/// through the same activity that hosts the output switcher.
class PlatformDiskSpace implements DiskSpace {
  PlatformDiskSpace({MethodChannel? channel})
      : _channel = channel ?? const MethodChannel('app.encore/storage');

  final MethodChannel _channel;

  @override
  Future<int?> freeBytes() async {
    try {
      final value = await _channel.invokeMethod<int>('freeBytes');
      return value;
    } on MissingPluginException {
      return null; // not Android, or running in a test
    } on PlatformException catch (error) {
      Log.warn('downloads', 'free space unavailable: ${error.message}');
      return null;
    }
  }
}
