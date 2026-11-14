import 'dart:async';

import '../../core/result.dart';
import '../fetch/fetch_client.dart';
import 'encore_api.dart';
import 'encore_models.dart';

/// Instant play on an Encore server (docs/04 section 4, P2-03): a song that is not in the library is *resolved* to a ref (the one every
/// person gets for that recording) and played from the server's own stream. Playing is not saving: nothing is added to anybody's library,
/// and the server decides by itself whether to keep the song (a like, a playlist, a download, a second day of listening).
///
/// It speaks the app's [InstantPlayBackend] so the catalogue screens, the play runs and the Jam do not know which kind of server they
/// are on. A job is a ref that is ready at once; the work of getting the audio happens when the player opens the stream.
class EncoreInstantBackend implements InstantPlayBackend {
  EncoreInstantBackend({
    required EncoreApi api,
    required Future<void> Function(List<EncoreRef> refs) ingest,
    Duration infoFor = const Duration(seconds: 30),
    DateTime Function() now = DateTime.now,
  })  : _api = api,
        _ingest = ingest,
        _infoFor = infoFor,
        _now = now;

  final EncoreApi _api;

  /// Gives the refs their rows in the local database, so the song can be played, liked and added like any other.
  final Future<void> Function(List<EncoreRef> refs) _ingest;
  final Duration _infoFor;
  final DateTime Function() _now;

  EncoreInfo? _info;
  DateTime _infoAt = DateTime.fromMillisecondsSinceEpoch(0);
  final Map<String, Future<Result<EncoreRef>>> _resolving = {};

  static Map<String, Object?> describe(FetchRequest r) => {
        'title': r.title,
        'artists': [r.artist],
        if (r.album != null) 'album': r.album,
        if (r.trackNumber != null && r.trackNumber! > 0)
          'trackNo': r.trackNumber,
        if (r.discNumber != null && r.discNumber! > 0) 'discNo': r.discNumber,
        if (r.year != null) 'year': r.year,
        if (r.durationSec != null && r.durationSec! >= 5)
          'durationMs': r.durationSec! * 1000,
        if (r.coverUrl != null && r.coverUrl!.startsWith('https://'))
          'coverUrl': r.coverUrl,
        if (r.videoId != null) 'videoId': r.videoId,
      };

  /// The same song asked twice at once (a prepare, then the tap) is one question.
  Future<Result<EncoreRef>> _resolve(FetchRequest request) {
    final key = '${request.artist}\u0000${request.title}\u0000'
        '${request.durationSec}\u0000${request.videoId}';
    final running = _resolving[key];
    if (running != null) return running;
    final future = _api.resolve([describe(request)]).then((result) {
      final refs = result.valueOrNull;
      if (refs == null || refs.isEmpty) {
        return Result<EncoreRef>.err(result.failureOrNull ??
            const ServerFailure('The server could not find that song.'));
      }
      return Result<EncoreRef>.ok(refs.first);
    }).whenComplete(() {
      // A block: returning the removed future would make `whenComplete` wait for itself.
      _resolving.remove(key);
    });
    _resolving[key] = future;
    return future;
  }

  /// Whether the server can fetch songs it does not have right now (YouTube may have asked it to rest). Remembered for a short while.
  Future<EncoreInfo?> _look() async {
    if (_info != null && _now().difference(_infoAt) < _infoFor) return _info;
    final info = (await _api.info()).valueOrNull;
    if (info != null) {
      _info = info;
      _infoAt = _now();
    }
    return info ?? _info;
  }

  /// Which of these songs the server already knows it cannot get (N-13), one answer per song in the order asked (`null`: no known problem).
  /// One request however many songs (at most 100). `null` when the server could not be asked (the network: ask again later); `supported: false` when
  /// the server has no such question (an older one: 404 or 405), which is "no verdicts here" and never an error. Asking changes nothing on the server.
  Future<({bool supported, List<EncoreUnavailable?> verdicts})?>
      unavailableAmong(List<FetchRequest> songs) async {
    final result = await _api.unavailable([for (final s in songs) describe(s)]);
    if (result.failureOrNull != null) return null;
    final answer = result.valueOrNull;
    if (answer == null) {
      return (supported: false, verdicts: const <EncoreUnavailable?>[]);
    }
    // An answer of the wrong length cannot be matched to the songs: it is no answer.
    if (answer.length != songs.length) return null;
    return (supported: true, verdicts: answer);
  }

  /// The same, for songs the phone has as rows of its own library: asked by ref id (B-128), in the order given. `supported: false` also when the server
  /// does not list `unavailable-ids` (it is not sent the question). `null` when the server could not be asked (or its features could not be read): later.
  Future<({bool supported, List<EncoreUnavailable?> verdicts})?>
      unavailableAmongRefs(List<String> refIds) async {
    final info = await _look();
    if (info == null) return null;
    if (!info.hasUnavailableIds) {
      return (supported: false, verdicts: const <EncoreUnavailable?>[]);
    }
    final result = await _api.unavailableByIds(refIds);
    if (result.failureOrNull != null) return null;
    final answer = result.valueOrNull;
    if (answer == null) {
      return (supported: false, verdicts: const <EncoreUnavailable?>[]);
    }
    if (answer.length != refIds.length) return null;
    return (supported: true, verdicts: answer);
  }

  @override
  Future<Result<FetchJob>> start(FetchRequest request) async {
    final resolved = await _resolve(request);
    final ref = resolved.valueOrNull;
    if (ref == null) return Result.err(resolved.failureOrNull!);
    final kept = ref.file?.navidromeSongId != null;
    // The server already knows it cannot get this song (N-13): it is not saved, not played and not tried again, and the row says why in the server's own
    // sentence. (The marked row of a list never gets here: a tap on it says so first. This is the song whose memory the server made after the list drew.)
    final unavailable = ref.unavailable;
    if (!kept && unavailable != null && unavailable.liveAt(_now())) {
      return Result.ok(FetchJob(
        id: ref.id,
        state: FetchState.failed,
        error: 'unavailable',
        message: unavailable.sentence,
      ));
    }
    if (!kept) {
      final info = await _look();
      if (info != null && info.youtubeState == 'resting') {
        return Result.ok(FetchJob(
          id: ref.id,
          state: FetchState.failed,
          error: 'resting',
          message: 'This server cannot get new songs for a while (YouTube '
              'asked it to wait). Songs already on the server still play.',
        ));
      }
    }
    try {
      await _ingest([ref]);
    } on Object catch (error) {
      return Result.err(ServerFailure('Could not save the song: $error'));
    }
    return Result.ok(FetchJob(
      id: ref.id,
      state: FetchState.ready,
      songId: ref.id,
      codec: ref.file?.codec,
      bitrateKbps: ref.file?.bitrateKbps,
    ));
  }

  @override
  Future<Result<FetchJob>> status(String id) async =>
      Result.ok(FetchJob(id: id, state: FetchState.ready, songId: id));

  /// **Does nothing on an Encore server (B-126).** It used to resolve the song ("the cheap half: a row on the server"), but a row is not cheap:
  /// every pause between two letters typed in Search and every list that was only opened left a song row on the server that no person, file or like
  /// pointed at and nothing ever retired, for every person who browsed. What it saved was one round trip at the tap, which then has to look the song
  /// up at YouTube anyway (seconds); the tap makes the ref itself. A server that can look a song up ahead of the tap would do it in
  /// `POST refs/prepare`, which the player calls for the songs of a queue (P1-04), not here.
  @override
  Future<void> prepare(FetchRequest request) async {}

  /// The audio is opened by the player from the row's ref ([streamUrlFor] is the one case with no row: a very long song).
  @override
  Uri? streamUri(FetchJob job) => null;

  @override
  Uri? streamUrlFor(FetchRequest request) => null;
}
