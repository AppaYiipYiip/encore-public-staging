import 'package:encore/app/server_kind.dart';
import 'package:encore/features/instant/instant_controller.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

/// The old request portal ("Get new music", the Request chips, the download-service sheets) belongs to a plain music server without the
/// instant-play service. Which kind of server this is must not depend on the "Play songs your server does not have" switch (AUDIT A-7).
void main() {
  bool offered({required ServerKind kind, required bool instant}) {
    final container = ProviderContainer(overrides: [
      serverKindProvider.overrideWithValue(kind),
      instantAvailableProvider.overrideWithValue(instant),
    ]);
    addTearDown(container.dispose);
    return container.read(requestPortalOfferedProvider);
  }

  test(
      'an Encore server never offers the portal, with the play switch on or off',
      () {
    expect(offered(kind: ServerKind.encore, instant: true), isFalse);
    expect(offered(kind: ServerKind.encore, instant: false), isFalse,
        reason:
            'the switch is off: that is how a tap plays, not the kind of server');
  });

  test('a plain server offers it only where there is no instant-play service',
      () {
    expect(offered(kind: ServerKind.plain, instant: false), isTrue);
    expect(offered(kind: ServerKind.plain, instant: true), isFalse);
  });

  test(
      'until it is known which kind of server this is (still looking), it is not offered',
      () {
    expect(offered(kind: ServerKind.detecting, instant: false), isFalse);
  });
}
