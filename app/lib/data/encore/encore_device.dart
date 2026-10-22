import 'dart:convert';

import '../../core/logger.dart';
import '../auth/credential_store.dart';
import 'encore_api.dart';

/// This phone's sign-in on an Encore server as a **device** (docs/17 section 1): a token the live channel authenticates with, and an id the
/// server uses to tell a change made here from one made on another phone.
///
/// Made once, with the person's own login, and kept in the phone's secure storage next to the password (never the database). Signing in
/// at every start would add a device to the person's list every time; so the token is reused until the server refuses it.
class EncoreDevice {
  EncoreDevice({
    required EncoreApi api,
    required CredentialStore store,
    required int serverId,
    required String username,
    required String password,
    this.deviceName = 'Android phone',
    this.appVersion,
  })  : _api = api,
        _store = store,
        _key = secretKey(serverId),
        _username = username,
        _password = password;

  /// Where a server's device sign-in is kept in the secure store.
  static String secretKey(int serverId) => 'encore.device.$serverId';

  /// What is kept there.
  static String encode(String token, String? id) =>
      jsonEncode({'token': token, 'id': id});

  final EncoreApi _api;
  final CredentialStore _store;
  final String _key;
  final String _username;
  final String _password;
  final String deviceName;
  final String? appVersion;

  /// The device token: the saved one, or a new one from signing in. `null` when the server cannot be asked just now.
  Future<String?> token() async {
    final saved = await _store.readSecret(_key);
    if (saved != null) {
      try {
        final map = jsonDecode(saved) as Map<String, dynamic>;
        final token = map['token'] as String?;
        if (token != null && token.isNotEmpty) {
          _api.deviceId = map['id'] as String?;
          return token;
        }
      } on Object catch (error) {
        // Unreadable: sign in again.
        Log.debug('encore-live',
            'the saved device sign-in is unreadable: ${error.runtimeType}');
      }
    }
    final result = await _api.login(
      username: _username,
      password: _password,
      deviceName: deviceName,
      appVersion: appVersion,
    );
    final login = result.valueOrNull;
    if (login == null || login.deviceToken.isEmpty) {
      Log.debug('encore-live',
          'device sign-in failed: ${result.failureOrNull?.message}');
      return null;
    }
    await _store.writeSecret(_key, encode(login.deviceToken, login.deviceId));
    _api.deviceId = login.deviceId;
    return login.deviceToken;
  }

  /// The server refused the saved token: forget it, so the next [token] signs in again.
  Future<void> forget() async {
    await _store.deleteSecret(_key);
    _api.deviceId = null;
  }
}
