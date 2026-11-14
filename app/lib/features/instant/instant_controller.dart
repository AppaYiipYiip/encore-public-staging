import 'dart:async';
import 'dart:convert';
import 'dart:math' show Random;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../app/session.dart' show serverCapabilities;
import '../../core/network_policy.dart';
import '../../data/catalogue/catalogue_models.dart';
import '../../data/db/app_database.dart';
import '../../data/encore/encore_instant.dart';
import '../../data/encore/encore_writer.dart';
import '../../data/fetch/fetch_client.dart';
import '../../data/repos/downloads_repository.dart';
import '../../data/repos/request_repository.dart';
import '../../data/sync/endpoint_resolver.dart';
import '../auth/login_problem.dart';
import '../catalogue/catalogue_providers.dart';
import '../downloads/download_providers.dart';
import '../jam/jam_providers.dart' show jamControllerProvider;
import '../player/playback_facade.dart';
import '../providers.dart';
import '../settings/settings_controller.dart';
import 'instant_play.dart';

/// The instant-play service's usual port.
const int kFetchPort = 8701;

/// Where to look for the instant-play service, most likely first (ADR-094): the
/// address saved earlier (path and all); then, for each address the music server
/// has, the service's own port on that host (home) and, behind an https
/// address, `/fetch` (away from home: the public address has one door,
/// and the service sits behind it the way the people service does at `/people`).
/// The public door that exists is asked before the port that usually does not.
List<Uri> fetchServiceCandidates(Iterable<Uri> serverEndpoints, {Uri? saved}) {
  final out = <Uri>[];
  final seen = <String>{};
  void add(Uri uri) {
    if (uri.host.isEmpty) return;
    final text = uri.toString().replaceAll(RegExp(r'/+$'), '');
    if (seen.add(text)) out.add(Uri.parse(text));
  }

  if (saved != null) add(saved);
  for (final endpoint in serverEndpoints) {
    final scheme = isPrivateHost(endpoint.host) ? 'http' : 'https';
    // An address typed as https is the public door (a Tailscale name is "private"
    // for the cleartext rule yet is the Funnel's public address too).
    if (endpoint.scheme == 'https') {
      final basePath = endpoint.path.replaceAll(RegExp(r'/+$'), '');
      add(Uri(
        scheme: 'https',
        host: endpoint.host,
        port: endpoint.hasPort ? endpoint.port : null,
        path: '$basePath/fetch',
      ));
    }
    add(Uri(scheme: scheme, host: endpoint.host, port: kFetchPort));
  }
  return out;
}

/// How many songs a play run keeps waiting behind the one that is playing. A
/// whole album is not fetched at once: a home line is slow, the service has a
/// disk and YouTube does not like bursts. Two songs ahead is minutes of music.
const int kRunLookahead = 2;

/// How the service is asked who it is. A provider of its own so a test can answer for it.
final fetchProbeProvider = Provider<Future<FetchServiceInfo?> Function(Uri)>(
  (ref) => (uri) => EncoreFetchClient.probe(uri),
);

/// How many rounds in a row found no service (drives the pause before the next look).
final fetchProbeMissesProvider = NotifierProvider<_Counter, int>(_Counter.new);

class _Counter extends Notifier<int> {
  @override
  int build() => 0;

  void bump() => state = state + 1;
  void reset() => state = 0;
}

/// The pause before looking for the service again, after [misses] rounds that found none: 8 s, then doubling to 2 minutes.
Duration fetchProbeRetryAfter(int misses) =>
    Duration(seconds: (8 * (1 << (misses.clamp(0, 4)))).clamp(8, 120));

/// How long to wait before the next look (a provider so a test need not wait).
final fetchProbeRetryProvider = Provider<Duration Function(int)>(
  (ref) => fetchProbeRetryAfter,
);

/// Where the instant-play service is, or `null`: the address saved earlier,
/// then the music server's own host (home and away) on its usual port. The
/// answer is remembered so later starts do not ask again (ADR-057).
///
/// A look that fails is not an answer. The service may be busy (an import is running), the line may be changing from Wi-Fi to mobile, the
/// phone may have just woken up: with one failed look remembered for the whole session every song fell back to a 30-second snippet
/// ("only a snippet plays", owner, 2026-10-22; snippets no longer exist, D-64). So a service that was found once is assumed to be still there when a look fails, and a
/// service never found is looked for again, with growing pauses, for as long as the app runs.
final fetchServiceProvider = FutureProvider<Uri?>((ref) async {
  final settings = ref.watch(settingsProvider);
  if (!settings.instantPlayEnabled) return null;
  final server = await ref.watch(activeServerProvider.future);
  if (server == null) return null;

  final saved = Uri.tryParse(settings.fetchServiceUrl ?? '');
  final endpoints = <Uri>[];
  try {
    for (final e in (jsonDecodeEndpoints(server.endpointsJson))) {
      endpoints.add(e.url);
    }
  } on Object {
    // No usable endpoint list: only the saved address can be tried.
  }
  // An Encore server plays songs itself, on the same address as everything else: there is nothing to look for.
  if (serverCapabilities(server)['encore'] == true && endpoints.isNotEmpty) {
    return endpoints.first;
  }
  final candidates = fetchServiceCandidates(
    endpoints,
    saved: saved != null && saved.host.isNotEmpty ? saved : null,
  );
  if (candidates.isEmpty) return null;
  final probe = ref.read(fetchProbeProvider);
  final infos = await Future.wait([
    for (final uri in candidates) probe(uri),
  ]);
  for (var i = 0; i < candidates.length; i++) {
    final info = infos[i];
    if (info != null && info.canPlayNow) {
      final found = candidates[i];
      if (found.toString() != saved?.toString()) {
        // Remembered outside this provider's build.
        scheduleMicrotask(() => ref
            .read(settingsProvider.notifier)
            .setFetchServiceUrl(found.toString()));
      }
      scheduleMicrotask(
          () => ref.read(fetchProbeMissesProvider.notifier).reset());
      return found;
    }
  }
  // Nobody answered "I can play now". A service that answered before is still assumed; the next look is soon either way.
  final misses = ref.read(fetchProbeMissesProvider);
  final timer = Timer(ref.read(fetchProbeRetryProvider)(misses), () {
    ref.read(fetchProbeMissesProvider.notifier).bump();
    ref.invalidateSelf();
  });
  ref.onDispose(timer.cancel);
  final answeredBefore = saved != null && saved.host.isNotEmpty;
  final someoneAnsweredAtAll = infos.any((i) => i != null);
  // A service that answered but says it cannot play now (an older one) is not assumed.
  return answeredBefore && !someoneAnsweredAtAll ? saved : null;
});

/// Whether each service address could stream the last time it answered.
final Map<String, bool> _knownStreaming = {};

/// The backend, once the service answered and a music-server session exists.
final instantBackendProvider = FutureProvider<InstantPlayBackend?>((ref) async {
  final uri = await ref.watch(fetchServiceProvider.future);
  if (uri == null) return null;
  final session = await ref.watch(sessionProvider.future);
  if (session == null) return null;
  if (session.encoreMode) {
    final writer = EncoreWriter(ref.watch(databaseProvider), session.server.id,
        ownerName: session.server.username);
    return EncoreInstantBackend(api: session.encore, ingest: writer.upsertRefs);
  }
  final info = await ref.read(fetchProbeProvider)(uri);
  // A look that failed leaves what was known: a service that could stream can still.
  if (info != null) _knownStreaming[uri.toString()] = info.canStream;
  return EncoreFetchClient(
      baseUrl: uri,
      auth: session.client.authQuery,
      canStream: info?.canStream ?? _knownStreaming[uri.toString()] ?? false);
});

/// Whether rows may offer "play now" (service found and switched on).
final instantAvailableProvider = Provider<bool>(
  (ref) => ref.watch(instantBackendProvider).value != null,
);

/// Whether the old request portal (Settings > "Get new music", the Request chips, the download-service sheets) may be offered: only on a plain
/// music server that has no instant-play service. **Never on an Encore server**, whatever "Play songs your server does not have" says: that switch
/// decides how a tap plays, not which kind of server this is (AUDIT A-7, UX-REVIEW M3). Until it is known which kind of server this is, the
/// portal is not offered.
final requestPortalOfferedProvider = Provider<bool>((ref) {
  final encore = ref.watch(onEncoreServerProvider);
  if (!encore.hasValue || (encore.value ?? false)) return false;
  return !ref.watch(instantAvailableProvider);
});

final instantPlayServiceProvider =
    FutureProvider<InstantPlayService?>((ref) async {
  final backend = await ref.watch(instantBackendProvider.future);
  final repo = ref.watch(libraryRepositoryProvider);
  final serverId = ref.watch(activeServerIdProvider).value;
  final session = await ref.watch(sessionProvider.future);
  if (backend == null || repo == null || serverId == null || session == null) {
    return null;
  }
  final db = ref.watch(databaseProvider);

  Future<TrackRow?> load(String songId) async {
    final result = await session.client.getSong(songId);
    final song = result.valueOrNull;
    if (song == null) return repo.trackOnce(songId);
    final album = song.albumId == null
        ? null
        : (await session.client.getAlbum(song.albumId!)).valueOrNull;
    await repo.ingest([song], album: album);
    return repo.trackOnce(song.id);
  }

  return InstantPlayService(
    backend: backend,
    matcher: LibraryMatcher(db, serverId),
    // On an Encore server the song's row was made when it was resolved (its id is the ref's), so there is nothing to ask the music server.
    loadSong: session.encoreMode ? repo.trackOnce : load,
    findSongId: (artist, title) async {
      final page = await session.client.search3(query: title, songCount: 20);
      final songs = page.valueOrNull?.songs ?? const [];
      for (final s in songs) {
        if (s.title.toLowerCase() == title.toLowerCase() &&
            (s.artist ?? '').toLowerCase().contains(artist.toLowerCase())) {
          return s.id;
        }
      }
      return null;
    },
  );
});

/// State of every song being fetched, keyed by the catalogue track id.
class InstantController extends Notifier<Map<String, InstantStatus>> {
  /// Bumped whenever a new play run starts, so an older run stops queueing.
  int _generation = 0;

  /// The run that is still fetching songs (`-1`: none).
  int _runningGeneration = -1;

  /// Whether more songs of the current run are still on their way to the queue
  /// (the player uses it: Next on the last song waits for the next one instead
  /// of stopping the music).
  bool get fetchingMore => _runningGeneration == _generation;

  @override
  Map<String, InstantStatus> build() => const {};

  void _set(String trackId, InstantStatus status) =>
      state = {...state, trackId: status};

  final Map<String, Future<InstantStatus?>> _inFlight = {};
  final Set<String> _prepared = {};

  /// Looks [track] up on the service ahead of a tap (the first song of a
  /// page that was just opened). Once per song and session; never an error.
  Future<void> prepare(CatalogueTrack track) async {
    if (!_prepared.add(track.id)) return;
    final service = await ref.read(instantPlayServiceProvider.future);
    await service?.prepare(track);
  }

  /// Fetches [track]; the result is its last status (`ready` carries the
  /// library row and/or the stream address, `failed` the reason). Plays
  /// nothing by itself. Asking again while a fetch of the same song is on
  /// its way joins that fetch.
  ///
  /// [bulk] marks a song nobody is waiting for (the rest of an album being
  /// added): the service takes the songs people are waiting for first.
  Future<InstantStatus?> fetch(CatalogueTrack track, {bool bulk = false}) =>
      _inFlight.putIfAbsent(
        track.id,
        // The callback must not return the removed future: `whenComplete`
        // would wait for it, and it is that very future.
        () => _fetch(track, bulk: bulk).whenComplete(() {
          _inFlight.remove(track.id);
        }),
      );

  Future<InstantStatus?> _fetch(CatalogueTrack track,
      {bool bulk = false}) async {
    final service = await ref.read(instantPlayServiceProvider.future);
    if (service == null) {
      const unavailable =
          InstantStatus.failed('Instant play is not available here.');
      _set(track.id, unavailable);
      return unavailable;
    }
    InstantStatus? last;
    await for (final status in service.fetch(track, bulk: bulk)) {
      last = status;
      _set(track.id, status);
      if (status.isFailed && status.error == 'login') {
        ref.read(loginProblemProvider.notifier).rejected(fromAction: true);
      } else if (status.isFailed && status.error == null) {
        // Possibly the service moved (the phone changed network): look again
        // the next time.
        ref.invalidate(fetchServiceProvider);
      }
    }
    return last;
  }

  /// A queue item for a song that has no library row (it plays from the
  /// service's stream).
  static StreamedTrack _streamItem(CatalogueTrack t, Uri uri) => StreamedTrack(
        id: t.id,
        title: t.title,
        uri: uri,
        artist: t.artistName,
        catalogueArtistId: t.artistId,
        album: t.albumTitle,
        imageUrl: t.coverUrl,
        duration: t.duration,
        videoId: t.videoId,
      );

  /// In a Jam the song that was tapped plays in the Jam, by name, at once: it is
  /// not fetched on this phone (the phone that makes the sound gets it, and the
  /// music server already has it for the next person). `false` outside a Jam.
  Future<bool> _intoTheJam(PlaybackFacade facade, CatalogueTrack t) async {
    if (!ref.read(jamControllerProvider).inJam) return false;
    await facade.playStreamed([_streamItem(t, Uri.parse('jam:${t.id}'))]);
    return true;
  }

  /// "Play this": fetches the song and starts it as soon as it is ready,
  /// unless the person started something else in the meantime.
  ///
  /// In a Jam a tapped song goes into the Jam. [onThisPhone] is for the phone
  /// that makes the sound, asked by the Jam to play a song it does not have:
  /// it fetches it and plays it itself (adding it to the Jam again would ask it
  /// to play it again, for ever).
  Future<void> play(CatalogueTrack track,
      {String? sourceName, String? sourceId, bool onThisPhone = false}) async {
    final facade = ref.read(
        onThisPhone ? enginePlaybackFacadeProvider : playbackFacadeProvider);
    if (!onThisPhone && await _intoTheJam(facade, track)) return;
    final before = ++_generation;
    final status = await fetch(track);
    if (status == null || !status.isReady || before != _generation) return;
    final name = sourceName ?? track.albumTitle ?? track.artistName;
    final id = sourceId ?? 'instant:${track.id}';
    final row = status.track;
    if (row != null) {
      await facade.playTracks([row], sourceName: name, sourceId: id);
    } else if (status.streamUri != null) {
      await facade.playStreamed(
        [_streamItem(track, status.streamUri!)],
        sourceName: name,
        sourceId: id,
      );
    }
  }

  /// Plays [tracks] from [startIndex]: the first song starts when it arrives,
  /// the rest are fetched one after the other, [lookahead] songs ahead of
  /// the one playing, and appended in order as they come in. Stops when the
  /// person starts something else or trims the queue.
  ///
  /// With [shuffle] the list is put in random order first, before any song is asked for, and starts from its first song ([startIndex] is
  /// ignored, as the player's Shuffle on a list starts anywhere). The queue is built one song at a time, so the player's own shuffle mode
  /// is not switched on: the songs simply come in the random order. [random] is for tests.
  Future<void> playRun(
    List<CatalogueTrack> tracks, {
    required int startIndex,
    required String sourceName,
    required String sourceId,
    int lookahead = kRunLookahead,
    bool shuffle = false,
    Random? random,
  }) async {
    if (tracks.isEmpty) return;
    final list = shuffle ? ([...tracks]..shuffle(random)) : tracks;
    final start = shuffle ? 0 : startIndex;
    final facade = ref.read(playbackFacadeProvider);
    if (await _intoTheJam(facade, list[start.clamp(0, list.length - 1)])) {
      return;
    }
    final generation = ++_generation;
    _runningGeneration = generation;
    try {
      await _run(
          list, start, sourceName, sourceId, lookahead, facade, generation);
    } finally {
      if (_runningGeneration == generation) _runningGeneration = -1;
    }
  }

  Future<void> _run(
    List<CatalogueTrack> tracks,
    int startIndex,
    String sourceName,
    String sourceId,
    int lookahead,
    PlaybackFacade facade,
    int generation,
  ) async {
    String? firstId; // what the queue starts with once the run has begun
    var inQueue = 0; // how many songs the run has put there
    bool live() {
      if (generation != _generation) return false;
      if (firstId == null) return true;
      final items = facade.queue.items;
      // Not loaded yet: give it the benefit of the doubt.
      if (items.isEmpty) return true;
      // Someone else started something, or took songs out of the queue.
      return items.first.id == firstId && items.length >= inQueue;
    }

    final order = [...tracks.skip(startIndex), ...tracks.take(startIndex)];
    final results = List<InstantStatus?>.filled(order.length, null);
    final done = List<bool>.filled(order.length, false);
    var appended = 0; // how many leading entries are already in the queue
    var started = false;

    Future<void> drain() async {
      while (appended < order.length && done[appended]) {
        final index = appended++;
        final status = results[index];
        if (status == null || !status.isReady || !live()) continue;
        final row = status.track;
        final stream = status.streamUri;
        if (row == null && stream == null) continue;
        if (!started) {
          started = true;
          firstId = row?.id ?? order[index].id;
          inQueue = 1;
          if (row != null) {
            await facade
                .playTracks([row], sourceName: sourceName, sourceId: sourceId);
          } else {
            await facade.playStreamed(
              [_streamItem(order[index], stream!)],
              sourceName: sourceName,
              sourceId: sourceId,
            );
          }
        } else {
          inQueue++;
          if (row != null) {
            await facade.addToQueue(row);
          } else {
            await facade.addStreamToQueue(_streamItem(order[index], stream!));
          }
        }
      }
    }

    // The song that was asked for gets the whole line to itself; the rest
    // follow one at a time, only as far ahead as the queue needs them.
    results[0] = await fetch(order[0]);
    done[0] = true;
    await drain();

    for (var i = 1; i < order.length; i++) {
      await _untilQueueNeedsSongs(facade, live, lookahead);
      if (!live()) return;
      results[i] = await fetch(order[i], bulk: true);
      done[i] = true;
      await drain();
    }
  }

  /// Completes once fewer than [lookahead] songs wait behind the one playing
  /// (or the run is no longer wanted). Event driven, with a slow safety tick
  /// for a player that is paused.
  static Future<void> _untilQueueNeedsSongs(
    PlaybackFacade facade,
    bool Function() live,
    int lookahead,
  ) async {
    bool needed() {
      final q = facade.queue;
      if (q.items.isEmpty || q.currentIndex < 0) return true;
      return q.items.length - 1 - q.currentIndex < lookahead;
    }

    if (needed() || !live()) return;
    final done = Completer<void>();
    void check() {
      if (!done.isCompleted && (needed() || !live())) done.complete();
    }

    final sub = facade.queueStream.listen((_) => check());
    final tick = Timer.periodic(const Duration(seconds: 10), (_) => check());
    try {
      await done.future;
    } finally {
      tick.cancel();
      await sub.cancel();
    }
  }

  /// "Download": gets every song into the library, then keeps the album on
  /// the phone (ADR-067). Lives here, not in the page, so it finishes even if
  /// the person has left the page. `pinnedAlbumId` is `null` when nothing was
  /// kept (no song arrived, or the library does not list the album yet).
  Future<({int added, String? pinnedAlbumId})> addAndKeepOffline(
    List<CatalogueTrack> tracks, {
    required String artist,
    required String albumTitle,
  }) async {
    final added = await addAll(tracks);
    if (added == 0) return (added: 0, pinnedAlbumId: null);
    final album =
        await ref.read(libraryMatcherProvider)?.findAlbum(artist, albumTitle);
    if (album == null) return (added: added, pinnedAlbumId: null);
    await ref.read(downloadActionsProvider).pin(PinTargetType.album, album.id);
    return (added: added, pinnedAlbumId: album.id);
  }

  /// Gets every song into the library without playing any.
  Future<int> addAll(List<CatalogueTrack> tracks) async {
    var ok = 0;
    var next = 0;
    Future<void> worker() async {
      while (true) {
        final i = next++;
        if (i >= tracks.length) return;
        if ((await fetch(tracks[i], bulk: true))?.isReady ?? false) ok++;
      }
    }

    await Future.wait([worker(), worker()]);
    return ok;
  }
}

final instantControllerProvider =
    NotifierProvider<InstantController, Map<String, InstantStatus>>(
  InstantController.new,
);

/// One row's status.
final instantStatusProvider = Provider.family<InstantStatus?, String>(
  (ref, trackId) =>
      ref.watch(instantControllerProvider.select((m) => m[trackId])),
);

/// Endpoints stored in a server row (kept here so the feature does not depend
/// on the session being up).
List<ServerEndpoint> jsonDecodeEndpoints(String json) => [
      for (final e in jsonDecode(json) as List)
        ServerEndpoint.fromJson((e as Map).cast<String, dynamic>()),
    ];
