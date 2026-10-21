import 'dart:async';

/// Rate limiting for streams that fire in bursts (a download queue updating
/// hundreds of rows would otherwise rebuild the UI hundreds of times).
extension ThrottleLatest<T> on Stream<T> {
  /// Emits the first event immediately, then at most one event per
  /// [interval] - always the *latest* value seen. The final value is never
  /// dropped: it is delivered when the interval ends.
  Stream<T> throttleLatest(Duration interval) {
    late StreamController<T> controller;
    StreamSubscription<T>? subscription;
    Timer? timer;
    T? pending;
    var hasPending = false;
    var windowOpen = false;

    void flush() {
      if (hasPending) {
        final value = pending as T;
        hasPending = false;
        pending = null;
        controller.add(value);
        timer = Timer(interval, flush);
      } else {
        windowOpen = false;
      }
    }

    controller = StreamController<T>(
      onListen: () {
        subscription = listen(
          (event) {
            if (!windowOpen) {
              windowOpen = true;
              controller.add(event);
              timer = Timer(interval, flush);
            } else {
              pending = event;
              hasPending = true;
            }
          },
          onError: controller.addError,
          onDone: () {
            timer?.cancel();
            if (hasPending) controller.add(pending as T);
            unawaited(controller.close());
          },
        );
      },
      onPause: () => subscription?.pause(),
      onResume: () => subscription?.resume(),
      onCancel: () async {
        timer?.cancel();
        await subscription?.cancel();
      },
    );
    return controller.stream;
  }
}
