import 'package:encore/core/network_validation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

/// Android's own "this network has internet" answer, read through a channel; anything that cannot be read is "unknown", never a guess.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const channel = MethodChannel('app.encore/network');

  void answer(Object? Function(MethodCall call) handler) =>
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(channel, (call) async => handler(call));

  tearDown(() => TestDefaultBinaryMessengerBinding
      .instance.defaultBinaryMessenger
      .setMockMethodCallHandler(channel, null));

  test('it passes on what Android found', () async {
    answer((call) => call.method == 'validated' ? true : null);
    expect(await MethodChannelNetworkValidation().validated(), isTrue);
    answer((call) => false);
    expect(await MethodChannelNetworkValidation().validated(), isFalse);
  });

  test('when Android cannot say, the answer is unknown', () async {
    answer((call) => null);
    expect(await MethodChannelNetworkValidation().validated(), isNull);
  });

  test(
      'with no platform behind it (a desktop test host) it is unknown, not an error',
      () async {
    expect(await MethodChannelNetworkValidation().validated(), isNull);
  });
}
