import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Where server passwords live. Never the database, logs, or image-cache keys
/// (ADR-017).
abstract interface class CredentialStore {
  Future<String?> readPassword(int serverId);
  Future<void> writePassword(int serverId, String password);
  Future<void> deletePassword(int serverId);

  /// Other secrets (request-portal password...), keyed by name.
  Future<String?> readSecret(String key);
  Future<void> writeSecret(String key, String value);
  Future<void> deleteSecret(String key);
}

/// Android Keystore / iOS Keychain backed store.
class SecureCredentialStore implements CredentialStore {
  SecureCredentialStore([FlutterSecureStorage? storage])
      : _storage = storage ?? const FlutterSecureStorage();

  final FlutterSecureStorage _storage;

  String _key(int serverId) => 'encore.server.$serverId.password';

  @override
  Future<String?> readPassword(int serverId) =>
      _storage.read(key: _key(serverId));

  @override
  Future<void> writePassword(int serverId, String password) =>
      _storage.write(key: _key(serverId), value: password);

  @override
  Future<void> deletePassword(int serverId) =>
      _storage.delete(key: _key(serverId));

  String _secretKey(String key) => 'encore.secret.$key';

  @override
  Future<String?> readSecret(String key) => _storage.read(key: _secretKey(key));

  @override
  Future<void> writeSecret(String key, String value) =>
      _storage.write(key: _secretKey(key), value: value);

  @override
  Future<void> deleteSecret(String key) =>
      _storage.delete(key: _secretKey(key));
}

/// For tests and previews.
class InMemoryCredentialStore implements CredentialStore {
  final Map<int, String> _values = {};

  @override
  Future<String?> readPassword(int serverId) async => _values[serverId];

  @override
  Future<void> writePassword(int serverId, String password) async =>
      _values[serverId] = password;

  @override
  Future<void> deletePassword(int serverId) async => _values.remove(serverId);

  final Map<String, String> _secrets = {};

  @override
  Future<String?> readSecret(String key) async => _secrets[key];

  @override
  Future<void> writeSecret(String key, String value) async =>
      _secrets[key] = value;

  @override
  Future<void> deleteSecret(String key) async => _secrets.remove(key);
}
