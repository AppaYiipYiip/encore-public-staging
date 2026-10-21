import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../core/logger.dart';
import '../core/result.dart';
import '../data/alerts/alerts_service.dart';
import '../data/auth/credential_store.dart';
import '../data/requests/portal_client.dart';
import '../domain/release_alerts.dart';
import '../features/requests/request_providers.dart';
import 'notifications.dart';
import 'providers.dart';

/// Where the request portal address and user are kept (same keys the settings
/// controller writes) - read directly because the background job has no
/// provider container.
const String _kPortalUrl = 'encore.requestPortal';
const String _kPortalUser = 'encore.requestPortalUser';

/// The download service's imports with the stored login, for the alerts
/// service. `null` when no service is connected or it cannot be reached.
Future<List<ImportSnapshot>?> readPortalImports({
  required CredentialStore credentials,
  required String? fallbackUser,
  String? fallbackPassword,
  Dio? dio,
}) async {
  try {
    final prefs = await SharedPreferences.getInstance();
    final url = prefs.getString(_kPortalUrl);
    if (url == null || url.isEmpty) return null;
    final uri = Uri.tryParse(url);
    if (uri == null || uri.host.isEmpty) return null;
    final user = prefs.getString(_kPortalUser) ?? fallbackUser;
    final own = await credentials.readSecret(kPortalPasswordKey);
    // No password of its own: the service takes the music server's login.
    final password = (own != null && own.isNotEmpty) ? own : fallbackPassword;
    if (user == null || user.isEmpty || password == null || password.isEmpty) {
      return null;
    }
    final client = HomelabPortalClient(
      baseUrl: uri,
      username: user,
      password: password,
      dio: dio,
    );
    final result = await client.overview();
    if (result case Ok(:final value)) {
      return [
        for (final i in value.imports)
          ImportSnapshot(
            name: i.name,
            tracks: i.tracks ?? 0,
            inLibrary: i.inLibrary ?? 0,
          ),
      ];
    }
  } on Object catch (error) {
    Log.debug('alerts', 'imports not read: $error');
  }
  return null;
}

/// The alerts service for the configured server (foreground use: marking
/// what the person has already seen).
final alertsServiceProvider = Provider<AlertsService?>((ref) {
  final serverId = ref.watch(activeServerIdProvider).value;
  if (serverId == null) return null;
  return AlertsService(
    db: ref.watch(databaseProvider),
    serverId: serverId,
    clock: ref.watch(clockProvider),
    sink: ref.watch(localNotificationsProvider),
    catalogue: ref.watch(catalogueClientProvider),
  );
});
