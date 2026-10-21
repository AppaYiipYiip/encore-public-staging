import 'dart:async';

import '../../core/logger.dart';
import '../../core/result.dart';
import '../../data/catalogue/catalogue_models.dart';
import '../../data/db/app_database.dart';
import '../../data/fetch/fetch_client.dart';
import '../../data/repos/request_repository.dart';

/// What a catalogue row shows while its song is being fetched (ADR-057).
enum InstantPhase { working, ready, failed }

class InstantStatus {
  const InstantStatus.working(this.stage, {this.detail})
      : phase = InstantPhase.working,
        message = null,
        error = null,
        track = null,
        streamUri = null;

  const InstantStatus.ready(this.track, {this.streamUri})
      : phase = InstantPhase.ready,
        stage = FetchState.ready,
        detail = null,
        message = null,
        error = null;

  const InstantStatus.failed(this.message, {this.error})
      : phase = InstantPhase.failed,
        stage = FetchState.failed,
        detail = null,
        track = null,
        streamUri = null;

  final InstantPhase phase;
  final FetchState stage;
  final String? detail;

  /// A sentence for a person (failed).
  final String? message;

  /// Short code from the service (failed): `not_found`, `blocked`, ...
  final String? error;

  /// The library's copy once the song is there (ready).
  final TrackRow? track;

  /// Where to play the song from when it has no library row yet (ready): the
  /// instant-play service serves it the moment it is downloaded.
  final Uri? streamUri;

  bool get isWorking => phase == InstantPhase.working;
  bool get isReady => phase == InstantPhase.ready;
  bool get isFailed => phase == InstantPhase.failed;

  /// "Looking for it", "Downloading"... for the row.
  String get label => switch (stage) {
        FetchState.queued => 'Waiting',
        FetchState.searching => 'Finding it',
        FetchState.downloading => 'Getting it',
        FetchState.tagging => 'Tagging',
        FetchState.indexing => 'Adding to your library',
        FetchState.ready => 'In your library',
        FetchState.failed => 'Could not get it',
      };
}

/// Fetches one catalogue song through the instant-play service and turns it
/// into a library track. Pure orchestration: the backend, the library and the
/// clock are injected.
class InstantPlayService {
  InstantPlayService({
    required InstantPlayBackend backend,
    required LibraryMatcher? matcher,
    required Future<TrackRow?> Function(String songId) loadSong,
    Future<String?> Function(String artist, String title)? findSongId,
    this.pollEvery = const Duration(milliseconds: 1200),
    Duration? pollEarly,
    this.earlyFor = const Duration(seconds: 10),
    this.timeout = const Duration(seconds: 150),
    this.busyWait = const Duration(seconds: 15),
    this.busyTries = 8,
    this.refusedWait = const Duration(seconds: 25),
    this.refusedTries = 3,
    Future<void> Function(Duration)? delay,
  })  : _backend = backend,
        _matcher = matcher,
        _loadSong = loadSong,
        _findSongId = findSongId,
        _pollEarly = pollEarly ??
            (pollEvery < const Duration(milliseconds: 300)
                ? pollEvery
                : const Duration(milliseconds: 300)),
        _delay = delay ?? Future<void>.delayed;

  final InstantPlayBackend _backend;
  final LibraryMatcher? _matcher;
  final Future<TrackRow?> Function(String songId) _loadSong;
  final Future<String?> Function(String artist, String title)? _findSongId;
  final Future<void> Function(Duration) _delay;
  final Duration pollEvery;

  /// How often the first [earlyFor] are asked about: the person is waiting for
  /// the first sound and the service moves from "searching" to "downloading"
  /// within seconds (a question every 1.2 s added half a second to that).
  final Duration _pollEarly;
  final Duration earlyFor;
  final Duration timeout;

  /// The service takes three songs at a time per person; a fourth is turned
  /// away ("too many songs at once, try again in a minute"). The app tries
  /// again by itself, [busyWait] apart, up to [busyTries] times (two minutes
  /// by default), showing "Waiting" meanwhile. The owner, 2026-10-17: "if it
  /// says try again in a minute I would expect the app itself to try again".
  final Duration busyWait;
  final int busyTries;

  /// YouTube sometimes refuses the server for a few minutes (it lets a visitor fetch about 300 videos an hour
  /// from one address). A tapped song is asked for again, [refusedWait] apart, up to [refusedTries] times,
  /// showing "Waiting" meanwhile; after that the person is told in the service's words (2026-10-18: "The
  /// server could not get this song just now" on a tap in the middle of a big import).
  final Duration refusedWait;
  final int refusedTries;

  static FetchRequest requestFor(CatalogueTrack t, {bool bulk = false}) =>
      FetchRequest(
        bulk: bulk,
        artist: t.artistName,
        title: t.title,
        album: t.albumTitle,
        trackNumber: t.trackNumber,
        discNumber: t.discNumber,
        durationSec: t.duration?.inSeconds,
        coverUrl: t.coverUrl,
        videoId: t.videoId,
        official: t.officialVideo,
      );

  /// Has the service look [track] up now, so a tap in the next minute starts
  /// at once. Songs the library already has are skipped; never throws.
  Future<void> prepare(CatalogueTrack track) async {
    try {
      final have = await _matcher?.findTrack(track.artistName, track.title);
      if (have != null) return;
    } on Object catch (error) {
      Log.debug('instant', 'library lookup failed: $error');
    }
    await _backend.prepare(requestFor(track));
  }

  /// Emits what is happening until the song is ready or cannot be had. Never
  /// throws; the last event is `ready` or `failed`.
  Stream<InstantStatus> fetch(CatalogueTrack track,
      {bool bulk = false, int refusals = 0}) async* {
    // Already in the library: nothing to fetch.
    try {
      final have = await _matcher?.findTrack(track.artistName, track.title);
      if (have != null) {
        yield InstantStatus.ready(have);
        return;
      }
    } on Object catch (error) {
      Log.debug('instant', 'library lookup failed: $error');
    }

    yield const InstantStatus.working(FetchState.queued);
    var started = await _backend.start(requestFor(track, bulk: bulk));
    for (var tries = 0; tries < busyTries && _isBusy(started); tries++) {
      // Nothing to show but "Waiting": the person did nothing wrong and has
      // nothing to do.
      await _delay(busyWait);
      started = await _backend.start(requestFor(track, bulk: bulk));
    }
    final first = started.valueOrNull;
    if (first == null) {
      yield InstantStatus.failed(_failureText(started.failureOrNull!));
      return;
    }

    var job = first;
    var elapsed = Duration.zero;
    var errors = 0;
    while (!job.state.isDone) {
      // The song is already arriving: a player can start on the first
      // seconds while the rest downloads (a slow line plays a three-minute
      // song long before it has finished downloading).
      final live = job.songId == null ? _backend.streamUri(job) : null;
      if (live != null) {
        yield InstantStatus.ready(null, streamUri: live);
        return;
      }
      yield InstantStatus.working(job.state, detail: job.detail);
      final wait = elapsed < earlyFor ? _pollEarly : pollEvery;
      await _delay(wait);
      elapsed += wait;
      if (elapsed > timeout) {
        yield const InstantStatus.failed(
            'This is taking too long. It may still arrive in your library.',
            error: 'timeout');
        return;
      }
      final polled = await _backend.status(job.id);
      final next = polled.valueOrNull;
      if (next == null) {
        // A blip on a phone's network is not a failed song.
        if (++errors >= 4) {
          yield InstantStatus.failed(_failureText(polled.failureOrNull!));
          return;
        }
        continue;
      }
      errors = 0;
      job = next;
    }

    if (job.state == FetchState.failed) {
      if (job.error == 'blocked' && refusals < refusedTries) {
        yield const InstantStatus.working(FetchState.queued);
        await _delay(refusedWait);
        yield* fetch(track, bulk: bulk, refusals: refusals + 1);
        return;
      }
      yield InstantStatus.failed(
        job.message ?? 'The server could not get that song.',
        error: job.error,
      );
      return;
    }

    // Ready. The library's own copy is best (likes, playlists, offline);
    // when the music server has not listed the song yet, the service plays
    // it - a scan can take minutes, a person should not have to wait.
    final stream = _backend.streamUri(job);
    var songId = job.songId;
    if (songId == null && stream == null) {
      final finder = _findSongId;
      if (finder != null) {
        yield const InstantStatus.working(FetchState.indexing);
        for (var i = 0; i < 12 && songId == null; i++) {
          await _delay(const Duration(seconds: 4));
          songId = await finder(track.artistName, track.title);
        }
      }
    }
    TrackRow? row;
    if (songId != null) row = await _loadSong(songId);
    if (row != null) {
      yield InstantStatus.ready(row, streamUri: stream);
      return;
    }
    if (stream != null) {
      yield InstantStatus.ready(null, streamUri: stream);
      return;
    }
    yield InstantStatus.failed(
      songId == null
          ? 'The song is on your server; it will show up after its next '
              'library scan.'
          : 'The song is on your server but could not be opened yet. Pull '
              'to refresh your library.',
      error: songId == null ? 'indexing' : 'load',
    );
  }

  /// "Too many at once", which passes in seconds; not the day's limit, which
  /// does not.
  static bool _isBusy(Result<FetchJob> result) {
    final failure = result.failureOrNull;
    return failure is ServerFailure &&
        failure.statusCode == 429 &&
        failure.code != 'daily_limit';
  }

  static String _failureText(AppFailure failure) => switch (failure) {
        NetworkFailure() =>
          'Cannot reach your server\'s instant-play service right now.',
        AuthFailure() => 'The instant-play service did not accept your '
            'music server login.',
        _ => failure.message,
      };
}
