import 'dart:async';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:drift/drift.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/clock.dart';
import '../core/cover_sizes.dart';
import '../data/auth/credential_store.dart';
import '../data/auth/server_setup_service.dart';
import '../data/db/app_database.dart';
import '../data/repos/library_repository.dart';
import '../data/sync/sync_scheduler.dart';
import 'session.dart';

// ----------------------------------------------------------------- roots
// These three are overridden in `bootstrap()` / tests.

final databaseProvider = Provider<AppDatabase>(
  (ref) => throw UnimplementedError('databaseProvider must be overridden'),
);

final credentialStoreProvider = Provider<CredentialStore>(
  (ref) =>
      throw UnimplementedError('credentialStoreProvider must be overridden'),
);

final clockProvider = Provider<Clock>((ref) => const SystemClock());

// ------------------------------------------------------- server / session

/// The configured server (first profile). `null` => onboarding.
///
/// Reads the **local database only**, so the app shell can render before any
/// network or secure-storage call completes (R-03).
final activeServerProvider = StreamProvider<ServerRow?>((ref) {
  final db = ref.watch(databaseProvider);
  return (db.select(db.servers)
        ..orderBy([(s) => OrderingTerm.asc(s.id)])
        ..limit(1))
      .watchSingleOrNull();
});

/// Id of the configured server. Emits only when it *changes*, so things that
/// are expensive to rebuild (the playback engine) are not recreated when the
/// server row is merely updated.
final activeServerIdProvider = StreamProvider<int?>((ref) {
  final db = ref.watch(databaseProvider);
  return (db.select(db.servers)
        ..orderBy([(s) => OrderingTerm.asc(s.id)])
        ..limit(1))
      .watchSingleOrNull()
      .map((s) => s?.id)
      .distinct();
});

/// Same stream but only re-emitting when something the *network session*
/// depends on changes (address list, user).
final _sessionServerProvider = StreamProvider<ServerRow?>((ref) {
  final db = ref.watch(databaseProvider);
  return (db.select(db.servers)
        ..orderBy([(s) => OrderingTerm.asc(s.id)])
        ..limit(1))
      .watchSingleOrNull()
      .distinct((a, b) =>
          a?.id == b?.id &&
          a?.endpointsJson == b?.endpointsJson &&
          a?.capabilitiesJson == b?.capabilitiesJson &&
          a?.username == b?.username);
});

/// Repository over the local library; available as soon as the server row is.
final libraryRepositoryProvider = Provider<LibraryRepository?>((ref) {
  final server = ref.watch(activeServerProvider).value;
  if (server == null) return null;
  return LibraryRepository(ref.watch(databaseProvider), server.id);
});

/// The network side. Built in the background; `null` when there is no server
/// or the password is missing (user must re-enter it).
final sessionProvider = FutureProvider<ServerSession?>((ref) async {
  final server = await ref.watch(_sessionServerProvider.future);
  if (server == null) return null;
  final password =
      await ref.watch(credentialStoreProvider).readPassword(server.id);
  if (password == null || password.isEmpty) return null;

  final session = await ServerSession.create(
    db: ref.watch(databaseProvider),
    server: server,
    password: password,
    clock: ref.watch(clockProvider),
  );
  ref.onDispose(() => unawaited(session.dispose()));
  return session;
});

final serverSetupServiceProvider = Provider<ServerSetupService>((ref) {
  return ServerSetupService(
    db: ref.watch(databaseProvider),
    credentials: ref.watch(credentialStoreProvider),
    clock: ref.watch(clockProvider),
  );
});

/// Sync state for Settings / Library header. Never drives a banner.
final syncStatusProvider = StreamProvider<SyncStatus>((ref) async* {
  final session = await ref.watch(sessionProvider.future);
  if (session == null) {
    yield const SyncStatus();
    return;
  }
  yield session.scheduler.status;
  yield* session.scheduler.statusStream;
});

// ---------------------------------------------------------- connectivity

/// What kind of link the phone is on; drives streaming quality and the
/// Wi-Fi-only download rule.
enum NetworkKind { none, wifi, mobile }

final networkKindProvider = StreamProvider<NetworkKind>((ref) async* {
  final connectivity = Connectivity();
  NetworkKind kindOf(List<ConnectivityResult> r) {
    if (r.isEmpty || r.every((e) => e == ConnectivityResult.none)) {
      return NetworkKind.none;
    }
    // A VPN (Tailscale) reports alongside its underlying transport.
    if (r.contains(ConnectivityResult.wifi) ||
        r.contains(ConnectivityResult.ethernet)) {
      return NetworkKind.wifi;
    }
    if (r.contains(ConnectivityResult.mobile)) return NetworkKind.mobile;
    return NetworkKind.wifi;
  }

  yield kindOf(await connectivity.checkConnectivity());
  yield* connectivity.onConnectivityChanged.map(kindOf).distinct();
});

/// Raw connectivity hint (not truth - see EndpointResolver).
final connectivityProvider = StreamProvider<bool>((ref) async* {
  final connectivity = Connectivity();
  bool isOnline(List<ConnectivityResult> r) =>
      r.any((e) => e != ConnectivityResult.none);
  yield isOnline(await connectivity.checkConnectivity());
  yield* connectivity.onConnectivityChanged.map(isOnline).distinct();
});

// ------------------------------------------------------------- artwork

/// Resolves artwork requests to `(url, cacheKey)`.
///
/// The cache key never contains credentials (ADR-017). Before the session is
/// ready a placeholder URL is returned: a disk-cache hit (by key) still
/// renders instantly offline; a miss simply shows the fallback.
class CoverArtResolver {
  const CoverArtResolver({required this.serverId, this.session});

  final int serverId;
  final ServerSession? session;

  /// The size a widget of [px] device pixels fetches (two sizes only: [CoverSize]).
  static int bucket(int px) => CoverSize.forPixels(px);

  ({Uri url, String cacheKey}) resolve(String coverArtId, int px) {
    final size = bucket(px);
    final url = coverArtId.startsWith('https://')
        ? Uri.parse(coverArtId)
        : session?.coverArtUrl(coverArtId, size: size) ??
            Uri.parse(
                'https://cover-cache.invalid/$serverId/$coverArtId/$size');
    return (url: url, cacheKey: CoverSize.key(serverId, coverArtId, size));
  }

  /// The cache key of the *other* size of the cover [resolve] would fetch: what stands in for it when it is not cached.
  String alternateKey(String coverArtId, int px) =>
      CoverSize.key(serverId, coverArtId, CoverSize.otherThan(bucket(px)));
}

final coverArtResolverProvider = Provider<CoverArtResolver?>((ref) {
  final server = ref.watch(activeServerProvider).value;
  if (server == null) return null;
  final session = ref.watch(sessionProvider).value;
  return CoverArtResolver(serverId: server.id, session: session);
});
