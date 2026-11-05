import 'package:flutter/services.dart';

/// Whether Android itself found internet on the network the phone is using (`NET_CAPABILITY_VALIDATED`).
///
/// A phone can have a network and no internet: a mobile network with no data, a Wi-Fi with a sign-in page. Android checks that by itself, and
/// this only reads its answer, so the app makes no outside call to find out (ADR-R38). It chooses the words of the strip when the server does
/// not answer (D-45, CN-4b): with no internet the person is offline; with internet only the server is away.
abstract interface class NetworkValidation {
  /// `true` internet was found, `false` it was not, `null` it cannot be known (desktop, tests, an old answer).
  Future<bool?> validated();
}

/// Asks the Android side (`app.encore/network`).
class MethodChannelNetworkValidation implements NetworkValidation {
  MethodChannelNetworkValidation([MethodChannel? channel])
      : _channel = channel ?? const MethodChannel('app.encore/network');

  final MethodChannel _channel;

  @override
  Future<bool?> validated() async {
    try {
      return await _channel.invokeMethod<bool>('validated');
    } on MissingPluginException {
      return null;
    } on PlatformException {
      return null;
    }
  }
}
