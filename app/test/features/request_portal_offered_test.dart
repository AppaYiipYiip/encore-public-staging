import 'dart:async';

import 'package:encore/features/instant/instant_controller.dart';
import 'package:encore/features/providers.dart' show onEncoreServerProvider;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

/// The old request portal ("Get new music", the Request chips, the download-service sheets) belongs to a plain music server without the
/// instant-play service. Which kind of server this is must not depend on the "Play songs your server does not have" switch (AUDIT A-7).
void main() {
  Future<bool> offered({required bool encore, required bool instant}) async {
    final container = ProviderContainer(overrides: [
      onEncoreServerProvider.overrideWith((ref) async => encore),
      instantAvailableProvider.overrideWithValue(instant),
    ]);
    addTearDown(container.dispose);
    container.listen(onEncoreServerProvider, (_, __) {});
    await container.read(onEncoreServerProvider.future);
    return container.read(requestPortalOfferedProvider);
  }

  test(
      'an Encore server never offers the portal, with the play switch on or off',
      () async {
    expect(await offered(encore: true, instant: true), isFalse);
    expect(await offered(encore: true, instant: false), isFalse,
        reason:
            'the switch is off: that is how a tap plays, not the kind of server');
  });

  test('a plain server offers it only where there is no instant-play service',
      () async {
    expect(await offered(encore: false, instant: false), isTrue);
    expect(await offered(encore: false, instant: true), isFalse);
  });

  test('until it is known which kind of server this is, it is not offered',
      () async {
    final never = Completer<bool>();
    final container = ProviderContainer(overrides: [
      onEncoreServerProvider.overrideWith((ref) => never.future),
      instantAvailableProvider.overrideWithValue(false),
    ]);
    addTearDown(container.dispose);
    container.listen(onEncoreServerProvider, (_, __) {});

    expect(container.read(requestPortalOfferedProvider), isFalse);
  });
}
