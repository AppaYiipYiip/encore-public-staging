import 'dart:async';
import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:drift/drift.dart';
import 'package:flutter/foundation.dart' show ValueNotifier;

import '../core/clock.dart';
import '../core/logger.dart';
import '../core/network_policy.dart';
import '../core/result.dart';
import '../core/server_url.dart';
import '../data/api/opensubsonic/opensubsonic_client.dart';
import '../data/auth/credential_store.dart';
import '../data/db/app_database.dart';
import '../data/encore/encore_api.dart';
import '../data/encore/encore_device.dart';
import '../data/encore/encore_live.dart';
import '../data/encore/encore_models.dart';
import '../data/encore/encore_mutations.dart';
import '../data/encore/encore_sync.dart';
import '../data/encore/encore_upgrade.dart';
import '../data/encore/signed_addresses.dart';
import '../data/navidrome/play_history_client.dart';
import '../data/repos/library_repository.dart';
import '../data/sync/endpoint_resolver.dart';
import '../data/sync/outbox.dart';
import '../data/sync/playlist_mutations.dart';
import '../data/sync/server_identity.dart';
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

/// The addresses the server told this phone about (`GET /encore/api/v1/server`), kept with what the phone learned about the server.
List<ServerEndpoint> learnedAddresses(ServerRow server) {
  final list = serverCapabilities(server)['learnedAddresses'];
  if (list is! List) return const [];
  return [
    for (final e in list)
      if (e is Map && e['url'] is String)
        ServerEndpoint.fromJson(e.cast<String, dynamic>()),
  ];
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
    required this.streams,
    required this.covers,
    required this.live,
    this.device,
    required EncoreUpgrade upgradeRunner,
    required AppDatabase db,
    required Dio Function() probeDio,
    required String? Function() knownKey,
    required Future<void> Function() refreshAddresses,
  })  : _db = db,
        _upgradeRunner = upgradeRunner,
        _probeDio = probeDio,
        _knownKey = knownKey,
        _refreshAddresses = refreshAddresses;

  /// Builds the network side for [server]. Cheap and non-blocking apart from
  /// one database read; no request is made until [start].
  static Future<ServerSession> create({
    required AppDatabase db,
    required ServerRow server,
    required String password,
    Dio? dio,
    Clock clock = const SystemClock(),

    /// Where the device sign-in is kept; without it (the background job, tests) there is no live channel.
    CredentialStore? credentialStore,
    String? appVersion,

    /// Whether an address must prove it is this server before anything is sent to it (docs/11 ADR-R40). On in the app; the tests that
    /// are not about it switch it off.
    bool verifyAddresses = true,

    /// How an address is asked who it is (tests replace it).
    ServerIdentityProbe? identityProbe,
  }) async {
    final candidates = [
      for (final e in jsonDecode(server.endpointsJson) as List)
        ServerEndpoint.fromJson((e as Map).cast<String, dynamic>()),
    ];
    // Addresses the server told this phone about earlier (docs/11 ADR-R40): kept beside the person's own, never in their list. Like any
    // other, they are only used once they have proved who they are.
    for (final e in learnedAddresses(server)) {
      if (!candidates.any((c) => c.url == e.url)) candidates.add(e);
    }
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

    // The key this phone has pinned for the server, if it has learned one. A row from before keys has none: the first time its server
    // proves a key it is pinned (trust on first use), and from then on only that server is accepted.
    var pinned = serverCapabilities(server)['serverId'] as String?;
    final identity = identityProbe ??
        ServerIdentityProbe(dioFactory: () {
          // A client of its own (no interceptors: asking who it is must not count as a request that worked), with the same adapter in tests.
          final probe = _buildDio(connect: const Duration(seconds: 3));
          if (dio != null) probe.httpClientAdapter = dio.httpClientAdapter;
          return probe;
        });

    // The addresses whose last answer was the key of another server (docs/31 CN-11, O-6): the strip names one when none proves itself.
    final answeredWrong = <Uri>{};
    endpoints = EndpointResolver(
      candidates: candidates,
      requireVerified: verifyAddresses,
      anotherServers: () => answeredWrong,
      probe: (base) async {
        if (verifyAddresses) {
          // Nothing secret is sent: a public question with a fresh challenge. Only an address that proves it is the server is ever used.
          final proof = await identity.check(base, expectedId: pinned);
          if (proof.verdict == EndpointVerdict.wrongKey) {
            answeredWrong.add(base);
          } else {
            answeredWrong.remove(base);
          }
          final learned = proof.serverId;
          if (proof.verdict == EndpointVerdict.verified &&
              learned != null &&
              pinned == null) {
            pinned = learned;
            unawaited(_pinServerId(db, server.id, learned));
          }
          return proof.usable;
        }
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

    // Asks the server for the addresses it has and keeps the new ones (a signed-in phone is told, so nobody types them).
    Future<void> refreshAddresses() async {
      if (!encoreMode) return;
      final told = (await encore.server()).valueOrNull;
      if (told == null) return;
      if (pinned != null && told.serverId != null && told.serverId != pinned) {
        Log.warn('identity',
            'the server named a key other than the one this phone knows: its address list is ignored');
        return;
      }
      final found = <ServerEndpoint>[];
      for (final a in told.addresses) {
        final url = canonicalBaseUrl(a.url);
        if (cleartextProblem(url) != null) continue;
        found.add(ServerEndpoint(
          label: switch (a.kind) {
            'home' => 'Home',
            'away' => 'Away',
            _ => 'Server',
          },
          url: url,
        ));
      }
      if (found.isEmpty) return;
      endpoints.addCandidates(found);
      await _rememberAddresses(db, server.id, found);
    }

    // The live channel: the server tells this phone when something changed, so another phone's edit shows within a second or two.
    EncoreLive? live;
    EncoreDevice? device;
    if (encoreMode && credentialStore != null) {
      device = EncoreDevice(
        api: encore,
        store: credentialStore,
        serverId: server.id,
        username: server.username,
        password: password,
        appVersion: appVersion,
      );
      live = EncoreLive(
        baseUrl: () => endpoints.currentUrl,
        deviceToken: device.token,
        tokenRefused: device.forget,
      );
    }
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
      streams: StreamAddresses(fetch: encore.streamAddress),
      covers: CoverPassHolder(
        fetch: encore.coverPass,
        baseUrl: () => endpoints.currentUrl,
      ),
      live: live,
      device: device,
      upgradeRunner: upgrade,
      db: db,
      // A short look: a server that is not there must not hold the start of syncing back.
      probeDio: () => dio ?? _buildDio(connect: const Duration(seconds: 3)),
      knownKey: () => pinned,
      refreshAddresses: refreshAddresses,
    );
  }

  /// Remembers the key a server proved, with what else the phone has learned about it (`capabilitiesJson`).
  /// Keeps the addresses the server named (new ones only), beside what else the phone has learned about it.
  static Future<void> _rememberAddresses(
      AppDatabase db, int serverId, List<ServerEndpoint> found) async {
    try {
      final row = await (db.select(db.servers)
            ..where((s) => s.id.equals(serverId)))
          .getSingleOrNull();
      if (row == null) return;
      final have = learnedAddresses(row);
      final fresh = [
        for (final e in found)
          if (!have.any((h) => h.url == e.url)) e,
      ];
      if (fresh.isEmpty) return;
      await (db.update(db.servers)..where((s) => s.id.equals(serverId))).write(
        ServersCompanion(
          capabilitiesJson: Value(jsonEncode({
            ...serverCapabilities(row),
            'learnedAddresses': [
              for (final e in [...have, ...fresh]) e.toJson()
            ],
          })),
        ),
      );
    } on Object catch (error) {
      Log.warn(
          'identity', 'could not remember the addresses of the server', error);
    }
  }

  static Future<void> _pinServerId(
      AppDatabase db, int serverId, String id) async {
    try {
      final row = await (db.select(db.servers)
            ..where((s) => s.id.equals(serverId)))
          .getSingleOrNull();
      if (row == null) return;
      final known = serverCapabilities(row);
      if (known['serverId'] == id) return;
      await (db.update(db.servers)..where((s) => s.id.equals(serverId))).write(
        ServersCompanion(
            capabilitiesJson: Value(jsonEncode({...known, 'serverId': id}))),
      );
    } on Object catch (error) {
      Log.warn('identity', 'could not remember the key of the server', error);
    }
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

  /// The signed address of every song, kept until it nearly ends (used in [encoreMode]: no login of the music server on a song's address).
  final StreamAddresses streams;

  /// The one ticket that opens every picture (used in [encoreMode]).
  final CoverPassHolder covers;

  /// Signing out of this phone (docs/32 DV-2): the server ends this phone's device, so its token stops working and the person's device list is
  /// right; best effort (offline is fine, the person can end it from another device). Then the saved sign-in is deleted.
  Future<void> endDevice() async {
    await live?.stop();
    await device?.signOut();
  }

  /// The server's live channel (Encore mode, foreground session only); `null` otherwise.
  final EncoreLive? live;

  /// This phone's sign-in on an Encore server as a device (Encore mode with a credential store); `null` otherwise.
  final EncoreDevice? device;
  StreamSubscription<LiveEvent>? _liveEvents;
  StreamSubscription<bool>? _liveConnection;

  final AppDatabase _db;
  final EncoreUpgrade _upgradeRunner;
  final Dio Function() _probeDio;
  final String? Function() _knownKey;
  final Future<void> Function() _refreshAddresses;
  StreamSubscription<ServerEndpoint>? _addressChanges;
  bool _disposed = false;

  /// Asks the server which addresses it has and keeps the new ones (also done by itself once an address has proved itself).
  Future<void> refreshAddresses() => _refreshAddresses();

  /// The key of this server as this phone knows it (pinned the first time the server proved one), or `null` for a server that has none.
  String? get knownKey => _knownKey();

  /// Where moving this phone onto an Encore server stands.
  /// `true` from the moment a plain session is built until the phone KNOWS what the server is: a definite "not an Encore server" answer, or
  /// a move onto Encore that failed. It stays on while the server cannot be reached, and on the way to Encore mode (the session is replaced
  /// then). A tap on a catalogue song waits for it instead of giving up (D-24, AUDIT F33; D-64: there is no preview).
  late final ValueNotifier<bool> detecting = ValueNotifier<bool>(!encoreMode);

  void _detected() {
    if (!_disposed) detecting.value = false;
  }

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
      _startLive();
      unawaited(_learnAddresses());
      unawaited(covers.ensure());
      return;
    }
    unawaited(_detectAndUpgrade());
  }

  /// Once an address has proved itself, and again whenever another one wins the race, ask the server which addresses it has.
  Future<void> _learnAddresses() async {
    _addressChanges ??= endpoints.changes.listen((_) => unawaited(
          _refreshAddresses().catchError((Object e) {
            Log.warn('identity', 'asking for the address list failed', e);
          }),
        ));
    await endpoints.resolve();
    if (!_disposed && endpoints.isVerified) await _refreshAddresses();
  }

  void _startLive() {
    final live = this.live;
    if (live == null || _disposed) return;
    _liveEvents ??= live.events.listen((event) {
      // The server said something changed (or this phone has just connected): ask what, now.
      switch (event.type) {
        case 'hello' || 'library.changed' || 'resync':
          scheduler.liveEvent();
      }
    });
    _liveConnection ??= live.connection.listen(scheduler.setLive);
    live.start();
  }

  /// The app came to the front: check at once and listen to the server again.
  void onForeground() {
    scheduler.onForeground();
    if (encoreMode) {
      _startLive();
      unawaited(covers.ensure());
    }
  }

  /// The app went to the background: nothing is checked and no connection is held (the battery, and Android would cut it anyway).
  void onBackground() {
    scheduler.onBackground();
    unawaited(live?.stop());
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
      final look = await _look();
      if (_disposed) return;
      final info = look.info;
      if (info == null) {
        // Not reachable now, or not an Encore server: sync the old way meanwhile, and look again later in case it was only the line (at
        // once when the network comes back). Only a definite answer from the server ("not found") ends the finding out.
        if (look.knownPlain) _detected();
        syncTheOldWay();
        await _pauseOrUntilReachable(pause);
        pause = pause * 2 > const Duration(hours: 1)
            ? const Duration(hours: 1)
            : pause * 2;
        continue;
      }
      if (info.apiVersion.isEmpty || !info.hasRefs) {
        _detected();
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
          // `detecting` stays on: the session is rebuilt in Encore mode by the change of the server's profile, and a tap that is waiting must
          // not see "not an Encore server" in between.
          return;
        case Err(:final failure):
          _detected();
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
  Future<({EncoreInfo? info, bool knownPlain})> _look() async {
    // On a fresh sign-in no address has proved itself yet, and the address to use is then a reserved name that can never be reached: the look
    // failed without a request and the next one came two minutes later, so a new person's first minutes ran the old music-server code
    // (AUDIT F30, `b10`). Race the addresses first; when none answers the look fails honestly and the retry pause applies.
    if (!endpoints.isVerified) await endpoints.resolve();
    final probe = EncoreApi(
        dio: _probeDio(),
        baseUrl: () => endpoints.currentUrl,
        auth: client.authQuery);
    final result = await probe.info();
    // An answer that is not an Encore server's ("not found", a page that is not JSON) is a plain music server; a line that does not answer is
    // not known yet.
    return (
      info: result.valueOrNull,
      knownPlain: result.failureOrNull != null &&
          result.failureOrNull is! NetworkFailure,
    );
  }

  /// Waits [pause], or until the network comes back, whichever is first.
  Future<void> _pauseOrUntilReachable(Duration pause) {
    final done = Completer<void>();
    final sub = endpoints.reachability.listen((up) {
      if (up && !done.isCompleted) done.complete();
    });
    final timer = Timer(pause, () {
      if (!done.isCompleted) done.complete();
    });
    return done.future.whenComplete(() {
      timer.cancel();
      unawaited(sub.cancel());
    });
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

  /// The address of a picture. On an Encore server it is written with the cover ticket (no login of the music server in it), and is `null`
  /// until the ticket has arrived (a second after the app starts): the image cache is keyed by picture and size, so a cached cover shows
  /// either way. A plain music server is asked with its own login, as before.
  Uri? coverArtUrl(String id, {int size = 300}) {
    if (!encoreMode || id.startsWith('https://')) {
      return client.coverArtUrl(id, size: size);
    }
    return covers.urlFor(id, size);
  }

  /// Resolves once an address has proved itself (or none did). A request made before that goes to a dead address on purpose and fails, and
  /// the first moments of a session are when the one-shot asks are made (who am I, what does this server do): they wait here, so they are
  /// not lost for good by a race (QA round 1, R1-1: an owner without Invite and People until the app was restarted, which then did the same).
  Future<void> whenAddressKnown() async {
    if (!endpoints.isVerified) await endpoints.resolve();
  }

  Future<void> dispose() async {
    _disposed = true;
    unawaited(covers.dispose());
    upgrade.dispose();
    detecting.dispose();
    await _addressChanges?.cancel();
    await _liveEvents?.cancel();
    await _liveConnection?.cancel();
    await live?.dispose();
    await scheduler.dispose();
    await outbox.dispose();
    await sync.dispose();
    await endpoints.dispose();
  }
}
