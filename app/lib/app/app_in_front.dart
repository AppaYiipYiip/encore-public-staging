import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Whether the app is in front of the person (docs/design S-95, P2-29): the card of the downloads is live while it is, and the dated card once it is
/// not (what is shown outside the app must stay true if it freezes).
///
/// `inactive` is still in front: Android reports it while the notification shade is pulled over the app, while a call banner is up and while the
/// recents button is pressed. Only `hidden`, `paused` and `detached` are leaving. Before the first report (a test, the first frame) the app is in front.
final appInFrontProvider = NotifierProvider<AppInFront, bool>(AppInFront.new);

class AppInFront extends Notifier<bool> {
  @override
  bool build() {
    final listener = AppLifecycleListener(
      onStateChange: (next) => state = _inFront(next),
    );
    ref.onDispose(listener.dispose);
    return _inFront(WidgetsBinding.instance.lifecycleState);
  }

  static bool _inFront(AppLifecycleState? state) => switch (state) {
        AppLifecycleState.hidden ||
        AppLifecycleState.paused ||
        AppLifecycleState.detached =>
          false,
        _ => true,
      };
}
