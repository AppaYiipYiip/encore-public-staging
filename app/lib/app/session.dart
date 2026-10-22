import 'dart:async';
import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:drift/drift.dart';
import 'package:flutter/foundation.dart' show ValueNotifier;

import '../core/clock.dart';
import '../core/logger.dart';
import '../core/result.dart';
import '../data/api/opensubsonic/opensubsonic_client.dart';
import '../data/db/app_database.dart';
import '../data/encore/encore_api.dart';
import '../data/encore/encore_models.dart';
import '../data/encore/encore_mutations.dart';
import '../data/encore/encore_sync.dart';
import '../data/encore/encore_upgrade.dart';
import '../data/navidrome/play_history_client.dart';
import '../data/repos/library_repository.dart';
import '../data/sync/endpoint_resolver.dart';
import '../data/sync/outbox.dart';
import '../data/sync/playlist_mutations.dart';
import '../data/sync/sync_engine.dart';
import '../data/sync/sync_scheduler.dart';
import '../data/sync/sync_state_store.dart';

/// Where the move onto an Encore server stands (shown on Home while it runs, and when it could not finish).
class UpgradeStatus {
  const UpgradeStatus.idle()
      : running = false,
        step = null,
        failure = null;
  const UpgradeStatus.running(String this.step)
      : running = true,
        failure = null;
  const UpgradeStatus.failed(String this.failure)
      : running = false,
        step = null;

  final bool running;

  /// What is being done now ("Matching your songs").
  final String? step;

  /// Why it could not finish, in words for the person; it is tried again.
  final String? failure;
}

/// The capabilities saved with a server profile (what a "Test & continue" and later looks learned about it).
Map<String, dynamic> serverCapabilities(ServerRow server) {
  try {
    final decoded = jsonDecode(server.capabilitiesJson);
    return decoded is Map ? decoded.cast<String, dynamic>() : const {};
  } on FormatException {
    return const {};
  }
}

/// Everything that talks to one server, assembled once and shared.
///
/// The UI never *waits* for a session: catalogue screens read the local
/// database through [LibraryRepository] (ADR-003). The session adds the
/// network side (sync, media URLs) in the background.
///
/// A session runs in one of two modes. On a plain music server the music server is everything (stars, playlists, a dump of its songs). On
/// an Encore server ([encoreMode]) the person's library lives in the Encore server and songs are references, with the music server kept
/// for what it does well: the browse index of albums and artists, covers, and the audio of kept files. A phone that knew a server as a
/// plain one is moved over by [EncoreUpgrade] the first time that server turns out to be an Encore server.
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
    required this.encore,
    required this.encoreMode,
    required EncoreUpgrade upgradeRunner,
    required AppDatabase db,
    required Dio Function() probeDio,
  })  : _db = db,
        _upgradeRunner = upgradeRunner,
        _probeDio = probeDio;

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
    // The Encore server's own API, on the same address as the music server's (one door).
    final encore = EncoreApi(
      dio: http,
      baseUrl: () => endpoints.currentUrl,
      auth: client.authQuery,
    );
    final encoreMode = serverCapabilities(server)['encore'] == true;
    final outbox = OutboxProcessor(
      db: db,
      client: client,
      serverId: server.id,
      clock: clock,
      encore: encoreMode ? encore : null,
    );
    final engine = SyncEngine(
      db: db,
      client: client,
      serverId: server.id,
      clock: clock,
      outbox: outbox,
      encore: encoreMode
          ? EncoreSync(
              db: db,
              api: encore,
              serverId: server.id,
              ownerName: server.username,
              clock: clock,
            )
          : null,
    );
    final mutations = MutationService(
      db: db,
      serverId: server.id,
      clock: clock,
      onQueued: () => unawaited(outbox.flush()),
    );
    final PlaylistEditor playlists = encoreMode
        ? EncorePlaylistEditor(
            db: db,
            serverId: server.id,
            clock: clock,
            ownerName: server.username,
            onQueued: () => unawaited(outbox.flush()),
          )
        : PlaylistMutations(
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
    final upgrade = EncoreUpgrade(
      db: db,
      api: encore,
      serverId: server.id,
      ownerName: server.username,
      pendingEdits: () async {
        await outbox.flush();
        // Edits that are parked as failed would never be sent: only the waiting ones hold the move back.
        final count = db.outbox.id.count();
        final query = db.selectOnly(db.outbox)
          ..addColumns([count])
          ..where(db.outbox.serverId.equals(server.id) &
              db.outbox.status.equals('pending'));
        return (await query.getSingle()).read(count) ?? 0;
      },
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
      encore: encore,
      encoreMode: encoreMode,
      upgradeRunner: upgrade,
      db: db,
      // A short look: a server that is not there must not hold the start of syncing back.
      probeDio: () => dio ?? _buildDio(connect: const Duration(seconds: 3)),
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
  final PlaylistEditor playlists;

  /// The Encore server's API (always built; used when [encoreMode], and to find out whether this server has one).
  final EncoreApi encore;

  /// This server is an Encore server and this phone has been moved over to it.
  final bool encoreMode;

  final AppDatabase _db;
  final EncoreUpgrade _upgradeRunner;
  final Dio Function() _probeDio;
  bool _disposed = false;

  /// Where moving this phone onto an Encore server stands.
  final ValueNotifier<UpgradeStatus> upgrade =
      ValueNotifier(const UpgradeStatus.idle());

  /// Starts background synchronisation (after the first frame).
  ///
  /// On a plain server the first thing is to ask whether it is an Encore server: if so the phone is moved over before the first sync, so
  /// the two ways of syncing never run against one database at once.
  Future<void> start() async {
    unawaited(client.loadExtensions());
    if (encoreMode) {
      scheduler.start();
      return;
    }
    unawaited(_detectAndUpgrade());
  }

  Future<void> _detectAndUpgrade() async {
    var syncing = false;
    void syncTheOldWay() {
      if (!syncing && !_disposed) {
        syncing = true;
        scheduler.start();
      }
    }

    var pause = const Duration(minutes: 2);
    while (!_disposed) {
      final info = await _look();
      if (_disposed) return;
      if (info == null) {
        // Not reachable now, or not an Encore server: sync the old way meanwhile, and look again later in case it was only the line.
        syncTheOldWay();
        await Future<void>.delayed(pause);
        pause = pause * 2 > const Duration(hours: 1)
            ? const Duration(hours: 1)
            : pause * 2;
        continue;
      }
      if (info.apiVersion.isEmpty || !info.hasRefs) {
        syncTheOldWay();
        return;
      }
      // An Encore server: move this phone onto it.
      _status(const UpgradeStatus.running('Getting ready'));
      final result = await _upgradeRunner.run(
        onStep: (step) => _status(UpgradeStatus.running(step)),
      );
      if (_disposed) return;
      switch (result) {
        case Ok():
          _status(const UpgradeStatus.idle());
          await _markEncore(info);
          return; // the session is rebuilt in Encore mode by the change of the server's profile
        case Err(:final failure):
          Log.warn('session',
              'the move onto the Encore server did not finish: ${failure.message}');
          _status(UpgradeStatus.failed(failure.message));
          syncTheOldWay();
          await Future<void>.delayed(const Duration(minutes: 2));
      }
    }
  }

  void _status(UpgradeStatus status) {
    if (!_disposed) upgrade.value = status;
  }

  /// Asks the address of this server whether it is an Encore server; `null` when it is not, or cannot be reached.
  Future<EncoreInfo?> _look() async {
    final probe = EncoreApi(
        dio: _probeDio(),
        baseUrl: () => endpoints.currentUrl,
        auth: client.authQuery);
    return (await probe.info()).valueOrNull;
  }

  Future<void> _markEncore(EncoreInfo info) async {
    final merged = {
      ...serverCapabilities(server),
      'encore': true,
      'encoreApi': info.apiVersion
    };
    await (_db.update(_db.servers)..where((s) => s.id.equals(server.id))).write(
      ServersCompanion(capabilitiesJson: Value(jsonEncode(merged))),
    );
  }

  Uri coverArtUrl(String id, {int size = 300}) =>
      client.coverArtUrl(id, size: size);

  Future<void> dispose() async {
    _disposed = true;
    upgrade.dispose();
    await scheduler.dispose();
    await outbox.dispose();
    await sync.dispose();
    await endpoints.dispose();
  }
}
