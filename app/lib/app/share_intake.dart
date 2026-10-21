import 'dart:async';

import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// One text shared to the app. A class and not a plain string on purpose:
/// opening the same link twice is two events, and a value equal to the one
/// before it is not announced (a person who taps the same invitation again
/// would see nothing happen). Two [SharedText]s are never equal.
class SharedText {
  SharedText(this.text);

  final String text;
}

/// Text shared to the app from another one ("Share > Encore" in Spotify,
/// YouTube Music or a browser).
///
/// The native side keeps the latest share until Dart takes it, so a share that
/// *started* the app is not lost, and calls `shared` when one arrives while
/// the app is already running.
class ShareIntake {
  ShareIntake([MethodChannel? channel])
      : _channel = channel ?? const MethodChannel('app.encore/share');

  final MethodChannel _channel;
  final StreamController<SharedText> _controller =
      StreamController<SharedText>.broadcast();

  /// Every shared text, in order.
  Stream<SharedText> get shared => _controller.stream;

  Future<void> start() async {
    _channel.setMethodCallHandler((call) async {
      if (call.method == 'shared' && call.arguments is String) {
        _emit(call.arguments as String);
        // Handed over: do not deliver it again at the next start-up.
        try {
          await _channel.invokeMethod<String>('takeShared');
        } on PlatformException {
          // Nothing to clear.
        }
      }
    });
    try {
      _emit(await _channel.invokeMethod<String>('takeShared'));
    } on MissingPluginException {
      // Not running on Android (tests, desktop): there is no share sheet.
    } on PlatformException {
      // Ignore: sharing is a convenience.
    }
  }

  void _emit(String? text) {
    if (text == null || text.trim().isEmpty || _controller.isClosed) return;
    _controller.add(SharedText(text));
  }

  void dispose() {
    _channel.setMethodCallHandler(null);
    unawaited(_controller.close());
  }
}

final shareIntakeProvider = Provider<ShareIntake>((ref) {
  final intake = ShareIntake();
  unawaited(intake.start());
  ref.onDispose(intake.dispose);
  return intake;
});

/// Emits each text shared to the app.
final sharedTextProvider = StreamProvider<SharedText>(
  (ref) => ref.watch(shareIntakeProvider).shared,
);
