import 'dart:async';
import 'dart:convert';

import 'package:dio/dio.dart';

import '../core/clock.dart';
import '../core/result.dart';
import '../data/api/opensubsonic/opensubsonic_client.dart';
import '../data/db/app_database.dart';
import '../data/navidrome/play_history_client.dart';
import '../data/repos/library_repository.dart';
import '../data/sync/endpoint_resolver.dart';
import '../data/sync/outbox.dart';
import '../data/sync/playlist_mutations.dart';
import '../data/sync/sync_engine.dart';
import '../data/sync/sync_scheduler.dart';
import '../data/sync/sync_state_store.dart';

/// Everything that talks to one server, assembled once and shared.
///
/// The UI never *waits* for a session: catalogue screens read the local
/// database through [LibraryRepository] (ADR-003). The session adds the
/// network side (sync, media URLs) in the background.
class ServerSession {
  ServerSession._({
    required this.server,
    required this.endpoints,
    required this.client,
    required this.sync,
    required this.scheduler,
    required this.library,
    required this.outbox,
    required this.mutations,
    required this.playlists,
    required this.credentials,
    required this.playHistory,
  });

  /// Builds the network side for [server]. Cheap and non-blocking apart from
  /// one database read; no request is made until [start].
  static Future<ServerSession> create({
    required AppDatabase db,
    required ServerRow server,
    required String password,
    Dio? dio,
    Clock clock = const SystemClock(),
  }) async {
    final candidates = [
      for (final e in jsonDecode(server.endpointsJson) as List)
        ServerEndpoint.fromJson((e as Map).cast<String, dynamic>()),
    ];
    final credentials =
        SubsonicCredentials(username: server.username, password: password);
    final http = dio ?? _buildDio();

    late final EndpointResolver endpoints;
    http.interceptors.add(InterceptorsWrapper(
      onResponse: (response, handler) {
        endpoints.reportSuccess();
        handler.next(response);
      },
      onError: (error, handler) {
        if (error.type == DioExceptionType.connectionError ||
            error.type.name.toLowerCase().contains('timeout')) {
          endpoints.reportFailure();
        }
        handler.next(error);
      },
    ));

    endpoints = EndpointResolver(
      candidates: candidates,
      probe: (base) async {
        final probeClient = OpenSubsonicClient(
          dio: _buildDio(connect: const Duration(seconds: 3)),
          baseUrl: () => base,
          credentials: credentials,
        );
        final result = await probeClient.ping();
        // Reachable but rejecting credentials still means "this is the
        // server": the endpoint is right, the user needs to re-enter them.
        return result.isOk || result.failureOrNull is AuthFailure;
      },
    );

    final client = OpenSubsonicClient(
      dio: http,
      baseUrl: () => endpoints.currentUrl,
      credentials: credentials,
    );
    final playHistory = PlayHistoryClient(
      dio: http,
      baseUrl: () => endpoints.currentUrl,
      credentials: credentials,
    );
    final outbox = OutboxProcessor(
        db: db, client: client, serverId: server.id, clock: clock);
    final engine = SyncEngine(
      db: db,
      client: client,
      serverId: server.id,
      clock: clock,
      outbox: outbox,
    );
    final mutations = MutationService(
      db: db,
      serverId: server.id,
      clock: clock,
      onQueued: () => unawaited(outbox.flush()),
    );
    final playlists = PlaylistMutations(
      db: db,
      serverId: server.id,
      clock: clock,
      ownerName: server.username,
      onQueued: () => unawaited(outbox.flush()),
    );
    final lastFull = await SyncStateStore(db, server.id)
        .getInt(SyncStateStore.lastFullSyncAtMs);
    final scheduler = SyncScheduler(
      engine: engine,
      endpoints: endpoints,
      clock: clock,
      initialSyncDone: lastFull != null,
      // The open app checks for edits made on other devices every few seconds.
      liveProbe: true,
    );

    return ServerSession._(
      server: server,
      endpoints: endpoints,
      client: client,
      sync: engine,
      scheduler: scheduler,
      library: LibraryRepository(db, server.id),
      outbox: outbox,
      mutations: mutations,
      playlists: playlists,
      credentials: credentials,
      playHistory: playHistory,
    );
  }

  static Dio _buildDio({Duration connect = const Duration(seconds: 6)}) => Dio(
        BaseOptions(
          connectTimeout: connect,
          receiveTimeout: const Duration(seconds: 30),
          sendTimeout: const Duration(seconds: 30),
          headers: const {'User-Agent': 'Encore/0.1'},
        ),
      );

  final ServerRow server;
  final EndpointResolver endpoints;
  final OpenSubsonicClient client;
  final SyncEngine sync;
  final SyncScheduler scheduler;
  final LibraryRepository library;
  final OutboxProcessor outbox;
  final SubsonicCredentials credentials;

  /// This person's own play history on the server (Year in Music).
  final PlayHistoryClient playHistory;

  /// Local-first writes (like, rating, scrobble) - UI calls these.
  final MutationService mutations;

  /// Local-first playlist editing (create, add, remove, rename, delete).
  final PlaylistMutations playlists;

  /// Starts background synchronisation (after the first frame).
  Future<void> start() async {
    unawaited(client.loadExtensions());
    scheduler.start();
  }

  Uri coverArtUrl(String id, {int size = 300}) =>
      client.coverArtUrl(id, size: size);

  Future<void> dispose() async {
    await scheduler.dispose();
    await outbox.dispose();
    await sync.dispose();
    await endpoints.dispose();
  }
}
