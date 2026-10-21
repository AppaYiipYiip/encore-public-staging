import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:drift/drift.dart';

import '../../core/clock.dart';
import '../../core/network_policy.dart';
import '../../core/result.dart';
import '../../core/server_url.dart';
import '../api/opensubsonic/models.dart';
import '../api/opensubsonic/opensubsonic_client.dart';
import '../db/app_database.dart';
import '../sync/endpoint_resolver.dart';
import 'credential_store.dart';

/// What a successful "Test & continue" learned about the server.
class ServerCheckReport {
  const ServerCheckReport({
    required this.ping,
    required this.reachableEndpoints,
    this.songCount,
  });

  final SsPing ping;
  final List<ServerEndpoint> reachableEndpoints;
  final int? songCount;
}

/// Validates connection details and persists a server profile.
///
/// Steps are surfaced one by one (reachable -> authenticated -> library) so the
/// UI can show actionable progress instead of one opaque spinner
/// (docs/06-ux-spec.md 4.10).
class ServerSetupService {
  ServerSetupService({
    required AppDatabase db,
    required CredentialStore credentials,
    Dio Function()? dioFactory,
    Clock clock = const SystemClock(),
  })  : _db = db,
        _credentials = credentials,
        _dioFactory = dioFactory ?? _defaultDio,
        _clock = clock;

  final AppDatabase _db;
  final CredentialStore _credentials;
  final Dio Function() _dioFactory;
  final Clock _clock;

  static Dio _defaultDio() => Dio(BaseOptions(
        connectTimeout: const Duration(seconds: 6),
        receiveTimeout: const Duration(seconds: 15),
        sendTimeout: const Duration(seconds: 15),
      ));

  /// What the first address is called in *Your server*: "Home" for one on the
  /// home network, "Server" for an https one (the public door, which is
  /// not home: a friend who signed in with it was told "Home").
  static String firstAddressLabel(Uri url) =>
      url.scheme == 'https' ? 'Server' : 'Home';

  /// Accepts what people actually type: `192.168.1.5:4533`, `music.example.org`,
  /// `http://nas.local/navidrome/`. Returns `null` if it cannot be a URL.
  static Uri? normalizeUrl(String input) {
    var text = input.trim();
    if (text.isEmpty) return null;
    if (!text.contains('://')) text = 'http://$text';
    final uri = Uri.tryParse(text);
    if (uri == null || uri.host.isEmpty) return null;
    if (uri.scheme != 'http' && uri.scheme != 'https') return null;
    return canonicalBaseUrl(uri);
  }

  /// Form validation: `null` when [input] is an acceptable address, else a
  /// short message (bad format, or cleartext to a public host - ADR-032).
  static String? validateAddress(String input) {
    final uri = normalizeUrl(input);
    if (uri == null) return 'Enter your server address';
    return cleartextProblem(uri);
  }

  /// Verifies every candidate; succeeds if at least one endpoint answers and
  /// authenticates.
  Future<Result<ServerCheckReport>> check({
    required List<ServerEndpoint> endpoints,
    required String username,
    required String password,
    void Function(String step)? onStep,
  }) async {
    if (endpoints.isEmpty) {
      return const Result.err(
          NetworkFailure('Enter the address of your server'));
    }
    for (final endpoint in endpoints) {
      final problem = cleartextProblem(endpoint.url);
      if (problem != null) return Result.err(NetworkFailure(problem));
    }

    final creds = SubsonicCredentials(username: username, password: password);
    final reachable = <ServerEndpoint>[];
    SsPing? ping;
    AppFailure? lastFailure;
    OpenSubsonicClient? firstGood;

    for (final endpoint in endpoints) {
      onStep?.call('Reaching ${endpoint.label}...');
      final client = OpenSubsonicClient(
        dio: _dioFactory(),
        baseUrl: () => endpoint.url,
        credentials: creds,
      );
      final result = await client.ping();
      switch (result) {
        case Ok(:final value):
          reachable.add(endpoint);
          ping ??= value;
          firstGood ??= client;
        case Err(:final failure):
          lastFailure = failure;
          if (failure is AuthFailure) {
            // Reachable but credentials rejected: stop early, say so.
            return Result.err(failure);
          }
      }
    }
    if (ping == null || firstGood == null) {
      return Result.err(
          lastFailure ?? const NetworkFailure('Cannot reach the server'));
    }

    onStep?.call('Looking at your library...');
    int? count;
    final scan = await firstGood.getScanStatus();
    if (scan case Ok(:final value)) count = value.count;

    return Result.ok(ServerCheckReport(
      ping: ping,
      reachableEndpoints: reachable,
      songCount: count,
    ));
  }

  /// Persists the profile and its password; returns the new server id.
  Future<int> save({
    required String name,
    required List<ServerEndpoint> endpoints,
    required String username,
    required String password,
    SsPing? ping,
  }) async {
    final id = await _db.into(_db.servers).insert(ServersCompanion.insert(
          name: name.trim().isEmpty ? 'My server' : name.trim(),
          username: username,
          endpointsJson: jsonEncode([for (final e in endpoints) e.toJson()]),
          capabilitiesJson: Value(jsonEncode({
            if (ping?.type != null) 'type': ping!.type,
            if (ping?.serverVersion != null) 'version': ping!.serverVersion,
            'openSubsonic': ping?.openSubsonic ?? false,
          })),
          createdAtMs: _clock.now().millisecondsSinceEpoch,
        ));
    await _credentials.writePassword(id, password);
    return id;
  }

  /// Replaces the address list of a saved server. At least one address is
  /// kept; the network session is rebuilt by the change.
  Future<void> updateEndpoints(
      int serverId, List<ServerEndpoint> endpoints) async {
    if (endpoints.isEmpty) {
      throw ArgumentError('A server needs at least one address');
    }
    await (_db.update(_db.servers)..where((s) => s.id.equals(serverId))).write(
      ServersCompanion(
        endpointsJson:
            Value(jsonEncode([for (final e in endpoints) e.toJson()])),
      ),
    );
  }

  /// How long [endpoint] takes to answer a `ping` with this login, or `null`
  /// when it does not answer. A server that answers but refuses the login
  /// still counts as reachable: the address is right.
  Future<Duration?> probe(
    ServerEndpoint endpoint, {
    required String username,
    required String password,
  }) async {
    final client = OpenSubsonicClient(
      dio: _dioFactory(),
      baseUrl: () => endpoint.url,
      credentials: SubsonicCredentials(username: username, password: password),
    );
    final started = _clock.now();
    final result = await client.ping();
    final answered = result.isOk || result.failureOrNull is AuthFailure;
    return answered ? _clock.now().difference(started) : null;
  }

  /// Removes a profile, its library cache (cascade) and its password.
  Future<void> remove(int serverId) async {
    await (_db.delete(_db.servers)..where((s) => s.id.equals(serverId))).go();
    await _credentials.deletePassword(serverId);
  }
}
