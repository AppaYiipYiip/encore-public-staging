import 'dart:async';

import 'package:drift/drift.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/clock.dart';
import '../core/logger.dart';
import '../data/db/app_database.dart';
import '../data/encore/signed_addresses.dart' show withQuality;
import '../data/repos/downloads_repository.dart';
import '../data/sync/outbox.dart';
import '../data/sync/sync_state_store.dart';
import '../features/common/cover_art.dart' show coverCacheManager;
import '../features/instant/instant_controller.dart'
    show instantControllerProvider;
import '../features/instant/library_resolver.dart'
    show SessionLibraryResolver, libraryResolverProvider;
import '../features/settings/settings_controller.dart';
import '../playback/encore_audio_handler.dart';
import '../playback/equalizer_service.dart';
import '../playback/just_audio_backend.dart';
import '../playback/library_browser.dart';
import '../playback/media_art.dart';
import '../playback/playback_engine.dart';
import '../playback/playback_state_store.dart';
import '../playback/queue_model.dart';
import '../playback/source_resolver.dart';
import 'connection.dart' show recheckServer, serverReachabilityProvider;
import 'providers.dart';
import 'session.dart';

/// The platform audio player: one per process, shared by every engine that is
/// built for a server (overridden in `bootstrap()` / tests).
final audioBackendProvider = Provider<JustAudioBackend>(
  (ref) => throw UnimplementedError('audioBackendProvider must be overridden'),
);

/// Android media session bridge, initialised once at start-up.
final audioHandlerProvider = Provider<Future<EncoreAudioHandler>>(
  (ref) => throw UnimplementedError('audioHandlerProvider must be overridden'),
);

/// How many coming songs the phone has the server make ready while one plays: two, or only the next one while Data saver is in force (P4-24).
int prepareAheadSongs({required bool dataSaverInForce}) =>
    dataSaverInForce ? 1 : 2;

/// The playback engine for the configured server.
///
/// Depends on the server *id* only: a server row that is merely updated must
/// never tear down what is playing.
final playbackEngineProvider = FutureProvider<PlaybackEngine?>((ref) async {
  final serverId = await ref.watch(activeServerIdProvider.future);
  if (serverId == null) return null;

  final db = ref.watch(databaseProvider);
  final backend = ref.watch(audioBackendProvider);
  final clock = ref.watch(clockProvider);

  ServerSession? session() => ref.read(sessionProvider).value;

  // Kept alive for as long as the engine is: the first tap must read the answer, not "still loading".
  ref.listen(serverReachabilityProvider, (_, __) {});

  // A car that starts the app cold asks for the browse tree before the engine
  // has restored its queue. The library only needs the database and the server
  // id, so hand it to the media session now (docs/23, B12).
  final handler = await ref.watch(audioHandlerProvider);
  final browser = DbLibraryBrowser(db: db, serverId: serverId);
  // Only a local file is ever published to the media session; the credentialed
  // server URL is used to fetch into the cache and for nothing else (B24).
  final art = MediaArtResolver(
    serverId: serverId,
    cachedFile: (key) async =>
        (await coverCacheManager.getFileFromCache(key))?.file,
    download: (url, key) async =>
        (await coverCacheManager.downloadFile(url, key: key)).file,
    urlFor: (id, size) => session()?.coverArtUrl(id, size: size)?.toString(),
    // The lock screen asks for the small picture too while Data saver is in force.
    smallOnly: () => ref.read(dataSaverInForceProvider),
  );
  handler.setBrowser(browser, coverArt: art.resolve);

  final downloads = DownloadsRepository(db, serverId, clock: clock);
  final resolver = DefaultSourceResolver(
    localPath: downloads.localPathFor,
    streamUrl: (id, {maxBitRate, format}) async {
      final s = session() ??
          await ref
              .read(sessionProvider.future)
              .timeout(const Duration(seconds: 8));
      if (s == null) {
        throw StateError('Not signed in to a server');
      }
      // No address of the server has proved itself yet (a cold start, a change of network): the first look is part of getting the song,
      // so a tap in the first second waits a round trip instead of failing. When nothing proves itself the server is not answering.
      if (!s.endpoints.isVerified && await s.endpoints.resolve() == null) {
        throw const ServerNotAnswering();
      }
      if (s.encoreMode) {
        // A song is a ref, and the server signs one address for it: it picks where the audio comes from (its own kept file, or YouTube), and
        // the phone needs no login of the music server. The address is kept until just before it ends; the quality rides on it.
        return withQuality(await s.streams.forRef(id),
            maxBitRate: maxBitRate, format: format);
      }
      return s.client.streamUrl(id, maxBitRate: maxBitRate, format: format);
    },
    // The choice for this link, held to Data saver quality while that is in force (one derived value: `streamQualityProvider`).
    streamQuality: () => ref.read(streamQualityProvider),
  );

  final engine = PlaybackEngine(
    backend: backend,
    resolver: resolver,
    store: DbPlaybackStateStore(SyncStateStore(db, serverId)),
    lookupTracks: (ids) => _lookupTracks(db, serverId, ids),
    // A song that was streamed from the catalogue is found again in the library by what it is, when the queue is restored.
    findByName: (artist, title, album) async {
      // The session is made from what is stored on the phone (no network); the library lookup needs it.
      await ref.read(sessionProvider.future);
      return SessionLibraryResolver(ref)
          .find(artist: artist, title: title, album: album);
    },
    recorder: SessionPlayRecorder(
      db: db,
      serverId: serverId,
      session: session,
      clock: clock,
      isPrivate: () => ref.read(settingsProvider).privateListening,
      // A song played from the instant-play service's stream has no id of the
      // music server's own: it counts under the library's copy of it, by what
      // it is, once the library lists it.
      resolveStreamed: (item) async {
        final artist = item.artist;
        final resolver = ref.read(libraryResolverProvider);
        if (artist == null || resolver == null) return null;
        final row = await resolver
            .find(artist: artist, title: item.title, album: item.album)
            .onError((_, __) => null);
        return row?.id;
      },
    ),
    effects: backend,
    clock: clock,
    // Next on the last song while an album's songs are still being fetched
    // waits for the next one instead of stopping the music.
    moreComing: () => ref.read(instantControllerProvider.notifier).fetchingMore,
    // The next songs of the queue are made ready on the server while this one plays, so Next finds them at once (P1-04): only on an Encore
    // server, only for songs that will be streamed. Best effort; the engine swallows a failure.
    // Two songs ahead; one while Data saver is in force (the one derived value, read each time).
    prepareAheadCount: () =>
        prepareAheadSongs(dataSaverInForce: ref.read(dataSaverInForceProvider)),
    prepareAhead: (upcoming) async {
      final s = session();
      if (s == null || !s.encoreMode) return;
      final ids = await idsToPrepare(upcoming, downloads.localPathFor);
      if (ids.isEmpty) return;
      await s.encore.prepare(ids);
    },
    // A stream that failed is asked about once: the server says why (no matching upload, removed, age check), and a song it cannot have is
    // not tried a second time. Only on an Encore server, which writes that answer.
    songRefusal: (address) async {
      final s = session();
      if (s == null || !s.encoreMode) return null;
      final why = await s.encore.streamRefusal(address);
      return why == null
          ? null
          : (message: why.message, permanent: why.permanent);
    },
    // Songs that are not downloaded need the server: without it they are not tried (and not skipped through). The ONE state is read each time
    // (`unknown`, the first second of the app or just after a change of network, is "may try"); a FRESH look is asked only before a song is
    // refused or waited for (docs/33 G-1, PB-F7), and it also tells the state.
    reachability: () => ref.read(serverReachabilityProvider),
    recheck: () => recheckServer(ref),
    replayGain: () {
      final s = ref.read(settingsProvider);
      return ReplayGainSettings(
        mode: s.replayGainMode,
        allowBoost: s.replayGainBoost,
      );
    },
  );
  await engine.restore();
  unawaited(backend.warmUp());
  // A song that waited for the connection or for its server plays by itself the moment the state leaves "away" (the network is back, the server
  // answers again; the engine also asks by itself every few seconds while it waits, so this only makes it quicker).
  ref.listen(
    serverReachabilityProvider,
    (previous, next) {
      if ((previous?.isAway ?? false) && !next.isAway) {
        unawaited(engine.networkChanged(online: true));
      }
    },
  );
  // The preferred speed applies to everything, including after a restart.
  unawaited(engine.setSpeed(ref.read(settingsProvider).playbackSpeed));
  ref.listen(
    settingsProvider.select((s) => s.playbackSpeed),
    (_, speed) => unawaited(engine.setSpeed(speed)),
  );

  handler.attach(
    engine,
    browser: browser,
    coverArt: art.resolve,
  );

  ref.onDispose(() {
    handler.detach();
    unawaited(engine.dispose());
  });
  return engine;
});

Future<Map<String, TrackRow>> _lookupTracks(
  AppDatabase db,
  int serverId,
  List<String> ids,
) async {
  final result = <String, TrackRow>{};
  // Stay well below SQLite's bound-variable limit for huge queues.
  for (var i = 0; i < ids.length; i += 500) {
    final chunk = ids.sublist(i, i + 500 > ids.length ? ids.length : i + 500);
    final rows = await (db.select(db.tracks)
          ..where((t) => t.serverId.equals(serverId) & t.id.isIn(chunk)))
        .get();
    for (final r in rows) {
      result[r.id] = r;
    }
  }
  return result;
}

/// Sends "now playing" to the server and writes finished plays to the local
/// history + scrobble outbox (works offline; delivered later).
///
/// With [isPrivate] true (Settings > Home, library & privacy) nothing is
/// sent or kept: no now-playing ping, no scrobble, no local history.
class SessionPlayRecorder implements PlayRecorder {
  SessionPlayRecorder({
    required AppDatabase db,
    required int serverId,
    required ServerSession? Function() session,
    Clock clock = const SystemClock(),
    bool Function() isPrivate = _never,
    this.resolveStreamed,
  })  : _db = db,
        _serverId = serverId,
        _session = session,
        _clock = clock,
        _isPrivate = isPrivate;

  /// The library id of a song that was played from the instant-play service's
  /// stream (it has no id of the music server's own), by what it is; `null`
  /// when the library cannot say yet.
  final Future<String?> Function(QueueItem item)? resolveStreamed;

  static bool _never() => false;

  final AppDatabase _db;
  final int _serverId;
  final ServerSession? Function() _session;
  final Clock _clock;
  final bool Function() _isPrivate;

  @override
  Future<void> nowPlaying(QueueItem item) async {
    if (_isPrivate()) return;
    final s = _session();
    if (s == null) return;
    final result = await s.client.scrobble(item.id, submission: false);
    if (!result.isOk) {
      Log.debug('playback', 'now-playing not delivered (will not retry)');
    }
  }

  @override
  Future<void> played(
    QueueItem item, {
    required Duration listened,
    String? source,
  }) async {
    if (_isPrivate()) return;
    var trackId = item.id;
    if (!item.isLibraryTrack) {
      final resolved = await resolveStreamed?.call(item);
      if (resolved == null) {
        Log.debug('playback', 'a streamed play the library cannot place yet');
        return;
      }
      trackId = resolved;
    }
    final s = _session();
    final mutations = s?.mutations ??
        MutationService(db: _db, serverId: _serverId, clock: _clock);
    await mutations.recordPlay(
      trackId: trackId,
      listenedMs: listened.inMilliseconds,
      source: source,
    );
  }
}

/// The Android equaliser. Built at start-up (`EncoreApp` watches it) so the
/// saved curve is applied after every restart; it used to be built only when
/// the person opened the equaliser screen (docs/23, B10).
final equalizerServiceProvider = Provider<EqualizerService>((ref) {
  final backend = ref.watch(audioBackendProvider);
  final service = EqualizerService(backend.equalizer);
  // The platform equaliser exists once the player has been created (the
  // warm-up in the engine provider does that); init waits for it.
  unawaited(ref.watch(playbackEngineProvider.future).then((_) async {
    await service.init();
  }));
  ref.onDispose(() => unawaited(service.dispose()));
  return service;
});
