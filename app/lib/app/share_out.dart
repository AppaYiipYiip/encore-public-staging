import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Hands a text to the phone's own share sheet (Messages, WhatsApp, e-mail...):
/// the way an invitation reaches the person it is for. No extra package: the
/// native side of the app (`MainActivity`) opens the system chooser.
abstract interface class ShareOut {
  /// `true` when the share sheet opened.
  Future<bool> text(String text);
}

class ChannelShareOut implements ShareOut {
  ChannelShareOut([MethodChannel? channel])
      : _channel = channel ?? const MethodChannel('app.encore/share');

  final MethodChannel _channel;

  @override
  Future<bool> text(String text) async {
    try {
      return await _channel.invokeMethod<bool>('send', text) ?? false;
    } on MissingPluginException {
      return false; // not on a phone (tests, desktop)
    } on PlatformException {
      return false;
    }
  }
}

/// Tests replace it.
final shareOutProvider = Provider<ShareOut>((ref) => ChannelShareOut());
