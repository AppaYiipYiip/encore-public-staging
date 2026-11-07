import 'dart:async';
import 'dart:math';

import 'package:flutter/foundation.dart';

import '../core/clock.dart';
import '../core/logger.dart';
import '../core/perf.dart';
import '../data/db/app_database.dart';
import '../features/player/playback_facade.dart';
import 'audio_backend.dart';
import 'playback_state_store.dart';
import 'queue_model.dart';
import 'reach_look.dart';
import 'replay_gain.dart';
import 'source_resolver.dart';

/// Receives listening events (scrobble + local history).
abstract interface class PlayRecorder {
  /// Playback of [item] has started (Navidrome's "now playing").
  Future<void> nowPlaying(QueueItem item);

  /// [item] was listened to for [listened] (already filtered by the
  /// scrobble rules: at least 30 s and half the track or 4 minutes).
  Future<void> played(QueueItem item,
      {required Duration listened, String? source});
}

/// Loudness boost on top of the player volume (equaliser / enhancer layer).
abstract interface class AudioEffects {
  Future<void> setLoudnessBoost(double db);
}

/// ReplayGain preferences, read when a track becomes current.
class ReplayGainSettings {
  const ReplayGainSettings({
    this.mode = ReplayGainMode.off,
    this.preampDb = 0,
    this.untaggedDb = 0,
    this.allowBoost = false,
  });

  final ReplayGainMode mode;
  final double preampDb;
  final double untaggedDb;

  /// Whether a quiet song may be made louder. By default levelling only turns loud songs down: the phone's volume buttons are the
  /// only thing that makes anything louder (P1-13).
  final bool allowBoost;
}

typedef PeriodicTimerFactory = Timer Function(
    Duration period, void Function(Timer timer) callback);

/// The playback engine (ADR-035): queue + a *window* of at most three
/// sources in the platform player + persistence, scrobbling, sleep timer and
/// error recovery. Implements [PlaybackFacade], so screens never see it.
///
/// Concurrency: every mutation runs through [_run], a FIFO chain, so two
/// quick taps can never interleave their window updates. Long operations
/// re-check [_generation] after each `await` and abandon themselves when a
/// newer "play this" request superseded them.
class PlaybackEngine implements PlaybackFacade {
  PlaybackEngine({
    required AudioBackend backend,
    required SourceResolver resolver,
    required PlaybackStateStore store,
    required Future<Map<String, TrackRow>> Function(List<String> ids)
        lookupTracks,
    PlayRecorder? recorder,
    AudioEffects? effects,
    ReplayGainSettings Function()? replayGain,
    Clock clock = const SystemClock(),
    Random? random,
    this.restartThreshold = const Duration(seconds: 3),
    this.persistEvery = const Duration(seconds: 2),
    this.maxConsecutiveFailures = 3,
    this.loadTimeout = const Duration(seconds: 12),
    PeriodicTimerFactory? periodicTimer,
    bool Function()? moreComing,
    bool Function()? canReachServer,
    bool Function()? networkPresent,
    bool Function()? internetFound,
    Future<bool> Function()? serverAnswers,
    this.serverRetryDelays = const [
      Duration(seconds: 1),
      Duration(seconds: 1),
      Duration(seconds: 2),
      Duration(seconds: 3),
    ],
    this.catalogueLookupBudget = const Duration(seconds: 4),
    Future<TrackRow?> Function(String artist, String title, String? album)?
        findByName,
    Future<void> Function(List<QueueItem> upcoming)? prepareAhead,
  })  : _prepareAhead = prepareAhead,
        _moreComing = moreComing ?? (() => false),
        _canReach = canReachServer ?? (() => true),
        _networkPresent = networkPresent ?? (() => false),
        _internetFound = internetFound ?? (() => true),
        _serverAnswers = serverAnswers ?? (() async => true),
        _findByName = findByName,
        _backend = backend,
        _resolver = resolver,
        _store = store,
        _lookupTracks = lookupTracks,
        _recorder = recorder,
        _effects = effects,
        _replayGain = replayGain ?? (() => const ReplayGainSettings()),
        _clock = clock,
        _random = random ?? Random(),
        _periodicTimer = periodicTimer ?? Timer.periodic {
    _queue = QueueModel(random: _random);
    _subscriptions
      ..add(_backend.stateStream.listen(_onBackendState))
      ..add(_backend.currentIndexStream.listen(_onBackendIndex))
      ..add(_backend.durationStream.listen((_) => _emitSnapshot()))
      ..add(_backend.errors.listen(_onBackendError))
      ..add(_backend.positionStream.listen(_onPosition));
    _last = _build();
  }

  final AudioBackend _backend;
  final SourceResolver _resolver;

  /// Told which songs come next, as soon as there is a song to play and as soon as a next one is queued, so the server can make them ready before Next
  /// is pressed (P1-04, audit B-107: the player itself only asks for a song when it is wanted, and the platform player loads its next source as late as
  /// possible). Best effort.
  final Future<void> Function(List<QueueItem> upcoming)? _prepareAhead;

  /// The queue entries already handed over (by uid), so each song is named once however often the queue changes. A catalogue album is queued one song
  /// at a time behind the first (audit B-83), so the next songs often do not exist yet when the first one starts: they are handed over as they arrive.
  final Set<int> _handedOver = {};
  final PlaybackStateStore _store;
  final Future<Map<String, TrackRow>> Function(List<String> ids) _lookupTracks;
  final Future<TrackRow?> Function(String artist, String title, String? album)?
      _findByName;
  final PlayRecorder? _recorder;
  final AudioEffects? _effects;
  final ReplayGainSettings Function() _replayGain;
  final Clock _clock;
  final Random _random;
  late final QueueModel _queue;
  final PeriodicTimerFactory _periodicTimer;

  /// "Previous" restarts the track when it has played longer than this.
  final Duration restartThreshold;

  /// How often the position is written while playing: a kill (the system
  /// ending the app, a swipe from the recent apps) gives no warning, so this
  /// is the most that can be lost (J-08 asks for 2 s). Only the small progress
  /// record is written this often, never the whole queue (`PlaybackProgress`).
  final Duration persistEvery;

  /// After this many tracks in a row fail, playback stops with a notice.
  final int maxConsecutiveFailures;

  /// How long loading a song may take before it is given up. A load whose network went away neither finishes nor fails: without
  /// this limit it held the command queue for good, so every later tap waited behind it and the player looked frozen (E1).
  final Duration loadTimeout;

  /// How long restoring the queue may spend looking streamed songs up in the library: the player must not wait on a dead network.
  final Duration catalogueLookupBudget;

  /// Whether the server can be reached right now (the phone has a network). A song that is not downloaded can only play with it.
  final bool Function() _canReach;
  final bool Function() _networkPresent;

  /// Whether Android itself found internet on the network in use (the strip's test, D-45 amended): `true` when that is not known.
  final bool Function() _internetFound;

  /// Asks the server whether it answers *now* (one fresh look at its addresses). A phone with a network and a server that does not answer is
  /// not a phone with a bad song (docs/33 PB-F7, PB-F8, G-1).
  final Future<bool> Function() _serverAnswers;

  /// How long to wait before asking again while a song waits for its server; the last value repeats for two minutes, then it is every
  /// 15 s, and after ten minutes the engine stops asking by itself (pressing play, or the server being seen again, still start the song).
  final List<Duration> serverRetryDelays;

  Timer? _serverRetry;
  int _serverRetries = 0;
  DateTime? _serverWaitSince;

  /// A song that could not load for lack of a connection waits for it: the value of [_intent] when it started waiting, so that
  /// pausing (or starting something else) since cancels the wait. `null` when nothing waits.
  int? _waitingSince;

  /// Whether the open `play.audible` span was begun by a Next/Previous (a skip) and not by a tap: the number is then "from the press to sound", which is what
  /// J-03 asks of every change (audit B-106: nothing but a tap began it, so a Next could not be timed by the app itself).
  bool _audibleBySkip = false;

  /// Where the song being loaded comes from, for the `play.audible` measurement: a file on this phone or a stream.
  String _sourceKind = 'stream';

  final List<StreamSubscription<Object?>> _subscriptions = [];
  final StreamController<PlaybackSnapshot> _snapshots =
      StreamController<PlaybackSnapshot>.broadcast();
  final StreamController<QueueSnapshot> _queueChanges =
      StreamController<QueueSnapshot>.broadcast();
  final StreamController<Duration> _positions =
      StreamController<Duration>.broadcast();
  final StreamController<SleepTimerStatus> _sleepChanges =
      StreamController<SleepTimerStatus>.broadcast();
  final StreamController<PlaybackNotice> _notices =
      StreamController<PlaybackNotice>.broadcast();

  late PlaybackSnapshot _last;
  QueueSnapshot _lastQueue = QueueSnapshot.empty;

  /// Uids of the sources currently loaded in the backend, in window order.
  List<int> _window = const [];

  /// The backend holds sources for the current queue entry.
  bool _loaded = false;

  /// Position to resume from the next time audio is loaded (restore/seek
  /// while nothing is loaded).
  Duration _resumePosition = Duration.zero;

  int _generation = 0;

  /// Completed when a newer "play this" request arrives: a load still in progress is of no interest then, and must not hold the
  /// command queue until its time limit (latest tap wins).
  Completer<void>? _loadSuperseded;

  int _newGeneration() {
    final pending = _loadSuperseded;
    if (pending != null && !pending.isCompleted) pending.complete();
    return ++_generation;
  }

  /// Counts the person's "stop the music" intents (each pause). A command
  /// remembers the value when it was QUEUED ([_opIntent] while it runs); if a
  /// pause happened since, it must not start audio, even though it is still
  /// loading or waiting its turn (docs/23, B8).
  int _intent = 0;

  /// Whether more songs are still on their way to the end of the queue (an
  /// instant-play run fetches them one after the other).
  final bool Function() _moreComing;

  /// The person pressed Next on the last song while more were on their way: the
  /// next one that arrives is started. Cancelled when the person pauses
  /// (`_intent` moves).
  int? _nextWaitingSince;
  int _opIntent = 0;

  /// Loads in progress that will start playing: the play/pause button must
  /// pause these rather than queue another play.
  int _loadingToPlay = 0;

  /// Increments every time the backend window is replaced; lets the
  /// completion handler ignore repeated/stale `completed` events.
  int _loadSerial = 0;

  /// Counts loads *started* (the serial above counts loads finished). A
  /// failure report belongs to the load that was running when it arrived, so
  /// the same failure reported twice can be told from two failures (B15).
  int _loadAttempt = 0;
  int _handledErrorAttempt = -1;
  int _completedSerial = -1;

  /// The list played to its end (or Next was pressed on its last song) and the player waits on that last song: the next Play starts the list over
  /// (P1-21, B-51). Only a true end sets it; every new load, skip, seek or jump clears it.
  bool _endedQueue = false;
  Future<void> _serial = Future<void>.value();
  int? _expectedIndex;
  int? _lastIndex;
  String? _sourceName;
  String? _sourceId;
  double _speed = 1;
  bool _disposed = false;

  // Listening accounting (scrobble rules).
  DateTime? _playingSince;
  Duration _listened = Duration.zero;
  bool _nowPlayingSent = false;
  int _consecutiveFailures = 0;
  final Set<int> _retried = <int>{};

  // Persistence.
  Timer? _persistDebounce;
  DateTime? _lastPersist;
  Duration _lastPosition = Duration.zero;

  // Sleep timer.
  SleepTimerStatus _sleep = SleepTimerStatus.off;
  Timer? _sleepTicker;
  bool _sleepAtEnd = false;
  static const Duration _fadeWindow = Duration(seconds: 10);
  double _gainVolume = 1;

  // ------------------------------------------------------------ facade: read

  @override
  PlaybackSnapshot get snapshot => _last;

  @override
  Stream<PlaybackSnapshot> get snapshots => _snapshots.stream;

  @override
  Stream<Duration> get positionStream => _positions.stream;

  @override
  QueueSnapshot get queue => _lastQueue;

  @override
  Stream<QueueSnapshot> get queueStream => _queueChanges.stream;

  @override
  SleepTimerStatus get sleepTimer => _sleep;

  @override
  Stream<SleepTimerStatus> get sleepTimerStream => _sleepChanges.stream;

  @override
  Stream<PlaybackNotice> get notices => _notices.stream;

  @override
  double get speed => _speed;

  /// Audio session id for effect processors (Android).
  int? get audioSessionId => _backend.androidAudioSessionId;

  // -------------------------------------------------------------- lifecycle

  /// Loads the saved queue (paused). Call once at start-up.
  Future<void> restore() => _run(() async {
        try {
          await _restoreSaved();
        } on TypeError catch (error, stack) {
          await _discardSavedQueue(error, stack);
        } on FormatException catch (error, stack) {
          await _discardSavedQueue(error, stack);
        }
      });

  Future<void> _restoreSaved() async {
    final saved = await _store.load();
    if (saved == null) return;
    final ids = ((saved.queue['ids'] as List?) ?? const []).cast<String>();
    if (ids.isEmpty) return;
    final tracks = Map.of(await _lookupTracks(ids));
    await _findCatalogueSongs(saved.queue, tracks);
    _queue.restore(saved.queue, tracks);
    if (_queue.isEmpty) return;
    _sourceName = saved.sourceName;
    _sourceId = saved.sourceId;
    // The progress record is newer than the snapshot's position (it is written
    // every couple of seconds and on every seek); it counts only if it is for
    // the song that is current now.
    var resume = Duration(milliseconds: saved.positionMs);
    final progress = await _store.loadProgress();
    final current = _queue.current;
    if (progress != null && current != null && progress.itemId == current.id) {
      resume = Duration(milliseconds: progress.positionMs);
    }
    _resumePosition = resume;
    _loaded = false;
    _emitAll();
  }

  /// A song that was streamed from the catalogue has no library id the next launch knows: the queue saved what it is (artist,
  /// title, album) and the library is asked for it by that. The server keeps a song once it has been played, so most are found.
  /// Those it does not have are left out, and the rest of the queue comes back (E6: it used to come back empty).
  Future<void> _findCatalogueSongs(
      Map<String, Object?> saved, Map<String, TrackRow> tracks) async {
    final find = _findByName;
    final named = saved['named'];
    if (find == null || named is! Map) return;
    final spent = Stopwatch()..start();
    for (final entry in named.entries) {
      final id = entry.key;
      final what = entry.value;
      if (id is! String || what is! Map || tracks.containsKey(id)) continue;
      final artist = what['artist'];
      final title = what['title'];
      final album = what['album'];
      if (artist is! String || title is! String) continue;
      final left = catalogueLookupBudget - spent.elapsed;
      if (left <= Duration.zero) break;
      try {
        final row = await find(artist, title, album is String ? album : null)
            .timeout(left);
        if (row != null) tracks[id] = row;
      } on TimeoutException {
        Log.warn('playback',
            'looking up the streamed songs of the saved queue took too long; the rest is left out');
        break;
      } on Object catch (error) {
        Log.warn('playback',
            'looking up a streamed song of the saved queue failed', error);
      }
    }
  }

  /// A saved queue that cannot be read (older build, damaged data) must not
  /// take playback down with it: it threw inside the command queue, failed the
  /// engine provider and left no playback at every launch (docs/23, B11).
  /// The queue was not touched (all casts happen before anything is changed).
  Future<void> _discardSavedQueue(Object error, StackTrace stack) async {
    Log.warn('playback', 'the saved queue is damaged; starting empty', error);
    _loaded = false;
    await _store.clear();
    _emitAll();
  }

  Future<void> dispose() async {
    if (_disposed) return;
    _disposed = true;
    _finishItem();
    await _persistNow();
    _persistDebounce?.cancel();
    _sleepTicker?.cancel();
    _serverRetry?.cancel();
    for (final s in _subscriptions) {
      await s.cancel();
    }
    // The backend outlives the engine (it is shared across server
    // switches); just make sure nothing keeps playing.
    await _backend.stop();
    await _snapshots.close();
    await _queueChanges.close();
    await _positions.close();
    await _sleepChanges.close();
    await _notices.close();
  }

  // ----------------------------------------------------------- facade: play

  @override
  Future<void> playTracks(
    List<TrackRow> tracks, {
    int startIndex = 0,
    String? sourceName,
    String? sourceId,
    bool shuffle = false,
    bool skipUnavailable = false,
  }) {
    if (tracks.isEmpty) return Future<void>.value();
    PerfMonitor.instance.begin('play.tap->playing');
    PerfMonitor.instance.begin('play.audible');
    _audibleBySkip = false;
    final generation = _newGeneration();
    return _run(() async {
      if (generation != _generation) return;
      final items = [for (final t in tracks) _queue.itemFor(t)];
      // "Shuffle" on a collection starts anywhere, like Spotify; tapping a
      // specific row (shuffle false) keeps that track as the start.
      var start = shuffle && startIndex == 0
          ? _random.nextInt(items.length)
          : startIndex;
      // Play and Shuffle on a list ask for the list, not for one song: without a connection they pass over what is not downloaded (field
      // test 2026-10-31: one missing song and nothing played). A tapped row still asks for that song.
      if (skipUnavailable && !await _canReachNow()) {
        final order = [for (var i = 0; i < items.length; i++) i];
        if (shuffle && startIndex == 0) {
          order.shuffle(_random);
        } else {
          order.removeRange(0, startIndex.clamp(0, items.length));
          order.addAll(
              [for (var i = 0; i < startIndex.clamp(0, items.length); i++) i]);
        }
        for (final i in order) {
          if (await _playable(items[i])) {
            start = i;
            break;
          }
        }
      }
      // Without a connection a song that is not downloaded cannot play: say so and change nothing. What is playing goes on, the queue
      // stays as it was, and nothing starts by itself when the network returns - the person asked for a song that was not there, and
      // minutes later a different one starting would be a surprise (Q30, D-42). Losing the network in the middle of a song is another
      // case: that one waits ([_waitForConnection]) and carries on.
      if (!await _canReachNow() && !await _playable(items[start])) {
        PerfMonitor.instance.cancel('play.tap->playing');
        PerfMonitor.instance.cancel('play.audible');
        _notify(PlaybackNotice(_notDownloadedWords(), isError: false));
        return;
      }
      _finishItem();
      _sourceName = sourceName;
      _sourceId = sourceId;
      _queue.replace(items,
          startIndex: start, shuffle: shuffle || _queue.shuffle);
      _consecutiveFailures = 0;
      _retried.clear();
      await _loadCurrent(autoplay: true, generation: generation);
      _emitAll();
      _schedulePersist(immediate: true);
    });
  }

  @override
  Future<void> playStreamed(
    List<StreamedTrack> tracks, {
    int startIndex = 0,
    String? sourceName,
    String? sourceId,
  }) {
    if (tracks.isEmpty) return Future<void>.value();
    PerfMonitor.instance.begin('play.tap->playing');
    PerfMonitor.instance.begin('play.audible');
    _audibleBySkip = false;
    final generation = _newGeneration();
    return _run(() async {
      if (generation != _generation) return;
      _finishItem();
      final start = startIndex.clamp(0, tracks.length - 1);
      _sourceName = sourceName ?? 'Streaming';
      _sourceId = sourceId ?? 'stream:${tracks[start].id}';
      _queue.replace([
        for (final t in tracks)
          QueueItem.streamed(
            uid: _queue.newUid(),
            id: t.id,
            title: t.title,
            uri: t.uri,
            artist: t.artist,
            catalogueArtistId: t.catalogueArtistId,
            album: t.album,
            imageUrl: t.imageUrl,
            durationSec: t.duration?.inSeconds,
            videoId: t.videoId,
          ),
      ], startIndex: start, shuffle: false);
      _consecutiveFailures = 0;
      _retried.clear();
      await _loadCurrent(autoplay: true, generation: generation);
      _emitAll();
      // Songs streamed from the catalogue are not restored after a restart: the saved ids
      // do not exist in the library, so a restore drops them.
      _schedulePersist();
    });
  }

  @override
  Future<void> play() => _run(() async {
        if (_queue.current == null) return;
        if (!_loaded) {
          await _loadCurrent(autoplay: true, position: _resumePosition);
        } else if (_endedQueue) {
          // The list is over and the player waits on its last song. Play starts it again from the first song, same source and same shuffle
          // setting, at every entry point (the album page, the mini player, the lock screen, a headset): this is the one place they all reach.
          // If songs were added after the end, the first of those is what comes next instead.
          _endedQueue = false;
          if (!_queue.skipNext()) _queue.jumpTo(0);
          _consecutiveFailures = 0;
          _retried.clear();
          await _loadCurrent(autoplay: true);
          _emitAll();
          _schedulePersist();
        } else {
          await _backend.play();
          // The same load plays on: when it ends, that is a new end. Reset only here, in the operations a person makes, never from the
          // backend's own events: pausing a finished player re-announces "completed", and handling that again would pause -> completed ->
          // pause for ever.
          _completedSerial = -1;
        }
      });

  /// Pausing does not wait in the command queue: on a slow link a load can take
  /// seconds (or until its timeout) and the lock-screen / headset pause must act
  /// now. It records the intent so that the load in progress, and any command
  /// queued before this one, does not start playing afterwards (docs/23, B8).
  /// Structural commands (load, skip, queue edits) keep their strict order.
  @override
  Future<void> pause() async {
    if (_disposed) return;
    _intent++;
    await _pause('the person paused');
  }

  @override
  Future<void> togglePlayPause() {
    final soundingOrAboutTo = _sounding || _loadingToPlay > 0;
    return soundingOrAboutTo ? pause() : play();
  }

  /// Whether sound is coming out. The platform player keeps `playing` true when it reaches the end of the last source, so "playing" alone is not
  /// enough: it must not have completed. The snapshot (and so the notification, the lock screen and the mini player) and the play/pause button
  /// share this one check, so none can say "playing" while the others say Play (P1-21, B-51).
  bool get _sounding {
    final state = _backend.state;
    return state.playing && state.processing != BackendProcessing.completed;
  }

  /// One line of what the engine decided, kept in the Diagnostics log (info level, so it exists in the release build too): the stall of audit B-106 (the player
  /// ended paused on a song nobody chose, with no word shown) left nothing to read. It says where the engine is, not what the song is called.
  void _trace(String what) => Log.info('playback',
      '$what [slot ${_lastIndex ?? '-'}, window ${_window.length}, load $_loadSerial, cursor ${_queue.cursor}]');

  /// Pauses the platform player and says why (see [_trace]).
  Future<void> _pause(String why) {
    _trace('pause: $why');
    return _backend.pause();
  }

  /// Whether a finished load or skip may start audio: only when nobody paused
  /// since the command was queued.
  bool _mayStartPlaying(bool autoplay) {
    if (!autoplay) return false;
    if (_opIntent == _intent) return true;
    PerfMonitor.instance.cancel('play.tap->playing');
    PerfMonitor.instance.cancel('play.audible');
    return false;
  }

  @override
  Future<void> seek(Duration position) => _run(() async {
        var target = position < Duration.zero ? Duration.zero : position;
        if (!_loaded) {
          _resumePosition = target;
          _lastPosition = target;
          _positions.add(target);
          _emitSnapshot();
          unawaited(_persistProgress());
          return;
        }
        // Never ask for a position the player does not have. What is loaded can
        // be shorter than anybody else claims: a lyric line stamped 2:51, a stale
        // saved position (docs/23, B34).
        final length = _backend.duration;
        if (length != null && target > length) target = length;
        await _backend.seek(target);
        _lastPosition = target;
        // The person is back inside this song (after the end, or anywhere): it is theirs to play from here, and its next end is a new end.
        // Reset after the backend has moved, so a "completed" the seek itself might echo is still taken for the old end.
        _endedQueue = false;
        _completedSerial = -1;
        // Where the person has put the song is where a kill must bring them back to: written now, not at the next tick (a seek, then the system
        // ending the app within a few seconds, used to bring the song back at the old position: 2:28 became 4:01 in the 6 Nov 2026 walk).
        unawaited(_persistProgress());
      });

  @override
  Future<void> skipNext() => _run(() async {
        if (_queue.current == null) return;
        if (!_queue.hasNext && _moreComing()) {
          // Not the end: the next song is still being fetched. Keep playing,
          // and start it when it arrives.
          _nextWaitingSince = _intent;
          return;
        }
        final hadNext = _queue.hasNext;
        if (hadNext && !await _canReachNow()) {
          // Without a connection only downloaded songs can play: Next goes to the next one of those, or does nothing at all.
          if (!await _stepToPlayable(_queue.skipNext)) {
            _notify(const PlaybackNotice(
                'The next songs are not downloaded. Connect to play them.'));
            return;
          }
          _finishItem();
          await _advanceTo(autoplay: true);
          return;
        }
        _finishItem();
        if (!_queue.skipNext()) {
          // End of the queue: stop on the last track; the next Play starts the list over.
          await _pause('Next on the last song: the list ended');
          if (_loaded) await _backend.seek(Duration.zero);
          _endedQueue = true;
          _emitAll();
          return;
        }
        await _advanceTo(autoplay: true);
      });

  @override
  Future<void> skipPrevious() => _run(() async {
        if (_queue.current == null) return;
        final position = _loaded ? _backend.position : _resumePosition;
        if (position > restartThreshold || !_queue.hasPrevious) {
          if (_loaded) {
            await _backend.seek(Duration.zero);
            _endedQueue = false;
            _completedSerial = -1; // a restarted song's end is a new end
          } else {
            _resumePosition = Duration.zero;
          }
          _emitSnapshot();
          return;
        }
        _finishItem();
        if (_queue.skipPrevious()) {
          _audibleBySkip = true;
          PerfMonitor.instance.begin('play.audible');
          _trace('previous: rebuild the window');
          await _loadCurrent(autoplay: true);
        }
      });

  @override
  void toggleShuffle() {
    _fire(() async {
      _queue.setShuffle(!_queue.shuffle);
      await _syncWindowTail();
      _emitAll();
      _schedulePersist();
    });
  }

  @override
  void cycleRepeat() => _applyRepeat((current) => switch (current) {
        QueueRepeat.off => QueueRepeat.all,
        QueueRepeat.all => QueueRepeat.one,
        QueueRepeat.one => QueueRepeat.off,
      });

  @override
  void setRepeat(RepeatKind kind) => _applyRepeat((_) => switch (kind) {
        RepeatKind.off => QueueRepeat.off,
        RepeatKind.all => QueueRepeat.all,
        RepeatKind.one => QueueRepeat.one,
      });

  void _applyRepeat(QueueRepeat Function(QueueRepeat current) next) {
    _fire(() async {
      _queue.setRepeat(next(_queue.repeat));
      await _backend.setLoopOne(_loopOne);
      await _syncWindowTail();
      _emitAll();
      _schedulePersist();
    });
  }

  @override
  Future<void> setSpeed(double speed) => _run(() async {
        _speed = speed.clamp(0.5, 2.0);
        await _backend.setSpeed(_speed);
      });

  // ---------------------------------------------------------- facade: queue

  @override
  Future<void> addToQueue(TrackRow track) => _run(() async {
        final wasEmpty = _queue.isEmpty;
        _queue.addToEnd(_queue.itemFor(track));
        if (wasEmpty) {
          await _loadCurrent(autoplay: true);
        } else {
          await _syncWindowTail();
          await _startWaitedForNext();
        }
        _emitAll();
        _schedulePersist();
      });

  @override
  Future<void> addStreamToQueue(StreamedTrack track) => _run(() async {
        final wasEmpty = _queue.isEmpty;
        _queue.addToEnd(QueueItem.streamed(
          uid: _queue.newUid(),
          id: track.id,
          title: track.title,
          uri: track.uri,
          artist: track.artist,
          catalogueArtistId: track.catalogueArtistId,
          album: track.album,
          imageUrl: track.imageUrl,
          durationSec: track.duration?.inSeconds,
          videoId: track.videoId,
        ));
        if (wasEmpty) {
          await _loadCurrent(autoplay: true);
        } else {
          await _syncWindowTail();
          await _startWaitedForNext();
        }
        _emitAll();
      });

  /// The song that Next was pressed for has arrived: go to it.
  Future<void> _startWaitedForNext() async {
    final since = _nextWaitingSince;
    _nextWaitingSince = null;
    if (since == null || since != _intent || !_moreComing()) return;
    _finishItem();
    if (_queue.skipNext()) await _advanceTo(autoplay: true);
  }

  @override
  Future<void> playNext(TrackRow track) => _run(() async {
        final wasEmpty = _queue.isEmpty;
        _queue.playNext(_queue.itemFor(track));
        if (wasEmpty) {
          await _loadCurrent(autoplay: true);
        } else {
          await _syncWindowTail();
        }
        _emitAll();
        _schedulePersist();
      });

  @override
  Future<void> jumpToQueueIndex(int index) => _run(() async {
        if (!_queue.jumpTo(index)) return;
        _finishItem();
        await _advanceTo(autoplay: true);
      });

  @override
  Future<void> removeFromQueue(int index) => _run(() async {
        final wasCurrent = _queue.removeAt(index);
        if (_queue.isEmpty) {
          _finishItem();
          await _backend.stop();
          _window = const [];
          _loaded = false;
        } else if (wasCurrent) {
          _finishItem();
          await _loadCurrent(autoplay: _backend.state.playing);
        } else {
          await _syncWindowTail();
        }
        _emitAll();
        _schedulePersist();
      });

  @override
  Future<void> moveInQueue(int from, int to) => _run(() async {
        _queue.move(from, to);
        await _syncWindowTail();
        _emitAll();
        _schedulePersist();
      });

  @override
  Future<void> clearUpNext() => _run(() async {
        _queue.clearUpNext();
        await _syncWindowTail();
        _emitAll();
        _schedulePersist();
      });

  @override
  Future<void> stopAndClear() => _run(() async {
        _persistDebounce?.cancel();
        _queue.replace(const []);
        _window = const [];
        _loaded = false;
        _resumePosition = Duration.zero;
        await _backend.stop();
        _emitAll();
        await _store.clear();
      });

  // ----------------------------------------------------------- sleep timer

  @override
  Future<void> setSleepTimer(Duration? duration) => _run(() async {
        _cancelSleep();
        if (duration == null || duration <= Duration.zero) {
          _publishSleep(SleepTimerStatus.off);
          return;
        }
        _sleepAtEnd = false;
        var remaining = duration;
        _publishSleep(SleepTimerStatus(
            mode: SleepTimerMode.countdown, remaining: remaining));
        _sleepTicker = _periodicTimer(const Duration(seconds: 1), (timer) {
          remaining -= const Duration(seconds: 1);
          if (remaining <= Duration.zero) {
            timer.cancel();
            _sleepTicker = null;
            unawaited(_expireSleep());
            return;
          }
          if (remaining <= _fadeWindow) {
            final f = remaining.inMilliseconds / _fadeWindow.inMilliseconds;
            unawaited(_backend.setVolume((_gainVolume * f).clamp(0.0, 1.0)));
          }
          _publishSleep(SleepTimerStatus(
              mode: SleepTimerMode.countdown, remaining: remaining));
        });
      });

  @override
  Future<void> setSleepAtEndOfTrack(bool enabled) => _run(() async {
        _cancelSleep();
        _sleepAtEnd = enabled;
        _publishSleep(enabled
            ? const SleepTimerStatus(mode: SleepTimerMode.endOfTrack)
            : SleepTimerStatus.off);
        await _syncWindowTail();
      });

  void _cancelSleep() {
    _sleepTicker?.cancel();
    _sleepTicker = null;
    if (_sleepAtEnd) _sleepAtEnd = false;
    unawaited(_backend.setVolume(_gainVolume));
  }

  Future<void> _expireSleep() async {
    await _run(() async {
      await _pause('the sleep timer ran out');
      await _backend.setVolume(_gainVolume);
      _publishSleep(SleepTimerStatus.off);
    }).catchError((Object _) {});
  }

  void _publishSleep(SleepTimerStatus status) {
    _sleep = status;
    if (!_sleepChanges.isClosed) _sleepChanges.add(status);
  }

  // -------------------------------------------------- no connection

  /// The network came back (or went): a song that was waiting for it plays now, unless the person has stopped the music or asked
  /// for something else since.
  Future<void> networkChanged({required bool online}) async {
    if (!online) return;
    final waiting = _waitingSince;
    if (waiting == null) return;
    _waitingSince = null;
    _serverRetry?.cancel();
    _serverRetries = 0;
    if (waiting != _intent || _queue.current == null) return;
    try {
      await _run(() async {
        if (_loaded || waiting != _intent) return;
        await _loadCurrent(autoplay: true, position: _resumePosition);
      });
    } on Object catch (error) {
      Log.warn('playback',
          'the song that waited for the connection could not start', error);
    }
  }

  /// Whether [item] can play right now: a file on this phone always, anything else only with a connection.
  /// Whether a song that is not downloaded can be asked for. [_canReach] is what was last found out; a server that was out of reach may be
  /// back (data returned on the same network is not a network change), so when the phone has a network the server is asked once before a
  /// song is refused ([ReachLook]: callers share the look, and a look that found nobody is not repeated for a few seconds).
  /// What a tap on a song that is not downloaded says while the server cannot be reached: by cause, with the SAME test as the strip (CN-1 and
  /// CN-4b, D-45 amended). With no network, or a network on which Android found no internet (4G with no data, a sign-in page), "Connect" is the
  /// way out; only with internet found is the person connected and the server alone away.
  String _notDownloadedWords() => _networkPresent() && _internetFound()
      ? "Not downloaded. Can't reach your server."
      : 'Not downloaded. Connect to play it.';

  Future<bool> _canReachNow() async {
    if (_canReach()) return true;
    if (!_networkPresent()) return false;
    return _reach();
  }

  late final ReachLook _reach =
      ReachLook(look: () => _serverAnswers(), clock: _clock);

  Future<bool> _playable(QueueItem item) async {
    if (await _canReachNow()) return true;
    try {
      return (await _resolver.resolve(item)).isLocal;
    } on Object catch (error) {
      Log.warn(
          'playback',
          'could not tell whether ${item.id} can play without a connection',
          error);
      return false;
    }
  }

  /// Moves the queue forward with [step] (Next, or the song ended) and, while the song it landed on cannot play for lack of a
  /// connection, on to the next one that can. When none can, the cursor goes back where it was and the answer is `false`.
  Future<bool> _stepToPlayable(bool Function() step) async {
    final from = _queue.cursor;
    if (!step()) return false;
    for (var tries = 0; tries < _queue.length; tries++) {
      final item = _queue.current;
      if (item == null || await _playable(item)) return true;
      if (!_queue.skipNext()) break;
    }
    _queue.jumpTo(from);
    return false;
  }

  /// A load that cannot happen now (no connection, or one that never finished): nothing is loaded, the person is told once,
  /// and the song is tried again by itself when the network returns, or when the person presses play.
  void _waitForConnection(String message,
      {required bool isError, required Duration position}) {
    _loaded = false;
    _window = const [];
    _resumePosition = position;
    _waitingSince = _intent;
    _notify(PlaybackNotice(message, isError: isError));
    PerfMonitor.instance.cancel('play.tap->playing');
    PerfMonitor.instance.cancel('play.audible');
    _emitAll();
  }

  /// The phone has a network and the server does not answer (it restarts, the home Wi-Fi has no internet, the Funnel is down): the song is
  /// not broken. Same as [_waitForConnection], and the server is asked again by itself (after 1, 1, 2, then every 3 s: one small question each time) until it answers, so the
  /// song carries on from where it stopped without the person doing anything. Nothing hops to the next song.
  void _waitForServer({required Duration position}) {
    _waitForConnection('Waiting for your server.',
        isError: false, position: position);
    _serverWaitSince = _clock.now();
    _serverRetries = 0;
    _scheduleServerRetry();
  }

  void _scheduleServerRetry() {
    _serverRetry?.cancel();
    if (_disposed) return;
    final waited = _clock.now().difference(_serverWaitSince ?? _clock.now());
    if (waited > const Duration(minutes: 10)) return;
    final delays = serverRetryDelays;
    final wait = waited > const Duration(minutes: 2)
        ? const Duration(seconds: 15)
        : delays[min(_serverRetries, delays.length - 1)];
    _serverRetries++;
    _serverRetry = Timer(wait, () => unawaited(_retryServer()));
  }

  Future<void> _retryServer() async {
    if (_disposed) return;
    final waiting = _waitingSince;
    if (waiting == null) return;
    if (waiting != _intent) {
      // The person paused or started something else since: nothing waits any more.
      _waitingSince = null;
      _serverRetries = 0;
      return;
    }
    var answers = false;
    try {
      answers = await _serverAnswers();
    } on Object catch (error) {
      Log.warn('playback', 'asking whether the server answers failed', error);
    }
    if (_disposed || _waitingSince == null) return;
    if (answers) {
      await networkChanged(online: true);
    } else {
      _scheduleServerRetry();
    }
  }

  /// Whether [item] is a file on this phone (a song that is not cannot play while the server is away). A lookup that fails or takes
  /// long says no.
  Future<bool> _isLocal(QueueItem item) async {
    try {
      return (await _resolver.resolve(item).timeout(const Duration(seconds: 2)))
          .isLocal;
    } on Object catch (error) {
      Log.debug('playback',
          'could not tell whether ${item.id} is a file: ${error.runtimeType}');
      return false;
    }
  }

  // ------------------------------------------------------------ internals

  bool get _loopOne =>
      _queue.repeat == QueueRepeat.one ||
      (_queue.repeat == QueueRepeat.all && _queue.length == 1);

  /// Fire-and-forget [_run] for callbacks that cannot await.
  void _fire(Future<void> Function() body) {
    unawaited(_run(body).catchError((Object _) {}));
  }

  Future<T> _run<T>(Future<T> Function() body) {
    final completer = Completer<T>();
    final queuedAt = _intent;
    _serial = _serial.then((_) async {
      if (_disposed) {
        completer.completeError(StateError('engine disposed'));
        return;
      }
      _opIntent = queuedAt;
      try {
        completer.complete(await body());
      } on Object catch (error, stack) {
        Log.error('playback', 'operation failed', error, stack);
        completer.completeError(error, stack);
      }
    });
    // Swallow here: callers that care await the returned future.
    return completer.future;
  }

  /// Loads the current entry (and the following one) into the backend.
  Future<void> _loadCurrent({
    required bool autoplay,
    Duration position = Duration.zero,
    int? generation,
  }) async {
    if (autoplay) _loadingToPlay++;
    try {
      await _loadCurrentBody(
        autoplay: autoplay,
        position: position,
        generation: generation,
      );
    } finally {
      if (autoplay) _loadingToPlay--;
    }
  }

  Future<void> _loadCurrentBody({
    required bool autoplay,
    Duration position = Duration.zero,
    int? generation,
  }) async {
    final item = _queue.current;
    if (item == null) {
      await _backend.stop();
      _window = const [];
      _loaded = false;
      _emitAll();
      return;
    }
    _loadAttempt++;
    final timer = Stopwatch()..start();
    final next = _loopOne || _sleepAtEnd ? null : _queue.peekNext;
    final List<AudioSourceSpec> results;
    try {
      // The next song is only a preload: when its address cannot be made (the server is away and it is not a file) this one still plays.
      final nextSpec = next == null
          ? Future<AudioSourceSpec?>.value()
          : _resolver
              .resolve(next)
              .then<AudioSourceSpec?>((s) => s, onError: (Object _) => null);
      final first = await _resolver.resolve(item);
      final second = await nextSpec;
      results = [first, if (second != null) second];
    } on Object catch (error) {
      Log.warn('playback', 'could not resolve ${item.id}', error);
      // The address of the song could not be made because the server does not answer: wait for it (the song stays, nothing is skipped).
      if (_canReach() &&
          (error is ServerNotAnswering || !await _serverAnswers())) {
        await _pause('the server does not answer (resolving the song)');
        _waitForServer(position: position);
        return;
      }
      _notify(const PlaybackNotice(
          "Can't reach your server yet. Check your connection and try again.",
          isError: true));
      PerfMonitor.instance.cancel('play.tap->playing');
      PerfMonitor.instance.cancel('play.audible');
      _emitAll();
      return;
    }
    if (generation != null && generation != _generation) return;
    final resolveMs = timer.elapsedMilliseconds;
    _sourceKind = results.first.isLocal ? 'file' : 'stream';

    // Without a connection a song that is not downloaded cannot play: say so at once, instead of trying and hopping on.
    if (!results.first.isLocal && !await _canReachNow()) {
      await _pause('no connection and the song is not downloaded');
      _waitForConnection(_notDownloadedWords(),
          isError: false, position: position);
      return;
    }
    // The next song is only queued behind this one when it can play too.
    final specs = [
      results.first,
      if (results.length > 1 && (results[1].isLocal || _canReach())) results[1],
    ];

    _expectedIndex = 0;
    _lastIndex = 0;
    // A finished/stopped player keeps its "playing" intent; make sure a
    // load that should not start audio really does not.
    if (!autoplay) await _pause('a load that must not start audio');
    await _backend.setLoopOne(_loopOne);
    final load = _backend.setSources(specs, index: 0, position: position);
    final superseded = _loadSuperseded = Completer<void>();
    try {
      await Future.any([load, superseded.future]).timeout(loadTimeout);
      if (superseded.isCompleted) {
        // Something newer was asked for while this was loading: leave the load to end by itself and let the new command run.
        unawaited(load.then<void>((_) {}, onError: (Object _) {}));
        return;
      }
    } on TimeoutException {
      Log.warn('playback',
          'loading ${item.id} took longer than ${loadTimeout.inSeconds} s; giving up for now');
      // The platform load is still pending: its eventual end (or failure) is nobody's business now.
      unawaited(load.then<void>((_) {}, onError: (Object _) {}));
      unawaited(_backend
          .stop()
          .timeout(const Duration(seconds: 2), onTimeout: () {})
          .onError((_, __) {}));
      _waitForConnection('Taking too long to load. Check your connection.',
          isError: true, position: position);
      return;
    }
    final loadMs = timer.elapsedMilliseconds - resolveMs;
    _window = [for (final r in specs) r.uid];
    _loadSerial++;
    _endedQueue = false;
    _loaded = true;
    _resumePosition = Duration.zero;
    _nowPlayingSent = false;
    _listened = Duration.zero;
    _playingSince = _backend.state.playing ? _clock.now() : null;
    await _applyGain(item);
    await _backend.setSpeed(_speed);
    if (_mayStartPlaying(autoplay)) await _backend.play();
    PerfMonitor.instance.note('load ${item.id} resolve=${resolveMs}ms '
        'setSources=${loadMs}ms total=${timer.elapsedMilliseconds}ms');
    _handOverTheNextSongs();
    _emitAll();
  }

  /// After the queue cursor moved by hand (skip / jump): reuse the gapless
  /// next source when it is already loaded, otherwise rebuild the window.
  Future<void> _advanceTo({required bool autoplay}) async {
    final item = _queue.current;
    if (item == null) return;
    _endedQueue = false; // the cursor moved by hand
    // A Next: the app times it itself (`play.audible`, "skip"); a pause meanwhile or a failure cancels it like it cancels a tap's.
    _audibleBySkip = true;
    PerfMonitor.instance.begin('play.audible');
    final index = _lastIndex ?? 0;
    final nextIndex = index + 1;
    if (_loaded &&
        nextIndex < _window.length &&
        _window[nextIndex] == item.uid) {
      _trace('skip: seek to window slot $nextIndex');
      _expectedIndex = nextIndex;
      await _backend.seek(Duration.zero, index: nextIndex);
      if (_mayStartPlaying(autoplay)) await _backend.play();
      // The index event slides the window and applies the loudness plan;
      // show the new track immediately.
      _emitAll();
      return;
    }
    _trace('skip: the next song is not in the window, rebuild it');
    await _loadCurrent(autoplay: autoplay);
  }

  /// Makes the loaded window match "current + next".
  Future<void> _syncWindowTail() async {
    if (!_loaded) {
      return;
    }
    final item = _queue.current;
    if (item == null) return;
    _handOverTheNextSongs();
    await _backend.setLoopOne(_loopOne);
    final index = _lastIndex ?? 0;

    // Drop everything behind the playing source.
    if (index > 0 && index <= _window.length) {
      _trace('window: drop the $index source(s) behind the playing one');
      await _backend.removeFirst(index);
      _window = _window.sublist(index);
      _lastIndex = 0;
      _expectedIndex = null;
    }

    final next = _loopOne || _sleepAtEnd ? null : _queue.peekNext;
    final wantUid = next?.uid;
    final haveUid = _window.length > 1 ? _window[1] : null;
    if (wantUid == haveUid) return;

    if (_window.length > 1) {
      _trace('window: the second source is not the next song, remove it');
      await _backend.removeAt(1);
      _window = [_window.first];
    }
    if (next != null) {
      final spec = await _resolver.resolve(next);
      if (spec.isLocal || _canReach()) {
        _trace('window: append the next song');
        await _backend.append(spec);
        _window = [..._window, spec.uid];
      }
    }
  }

  // ---------------------------------------------------- backend callbacks

  BackendState? _tracedState;

  void _onBackendState(BackendState state) {
    final now = _clock.now();
    if (_tracedState != state) {
      _tracedState = state;
      _trace(
          'platform player: playing ${state.playing}, ${state.processing.name}');
    }
    if (state.playing) {
      _playingSince ??= now;
      if (!_nowPlayingSent && _loaded) {
        _nowPlayingSent = true;
        final item = _queue.current;
        if (item != null && item.isLibraryTrack) {
          unawaited(_safeNowPlaying(item));
        }
      }
      if (state.processing == BackendProcessing.ready) {
        // Audio is really running: the retry / failure budget resets.
        final item = _queue.current;
        if (item != null) _retried.remove(item.uid);
        _consecutiveFailures = 0;
        if (PerfMonitor.instance.isOpen('play.tap->playing')) {
          PerfMonitor.instance.end('play.tap->playing', detail: item?.title);
        }
      }
    } else if (_playingSince != null) {
      _listened += now.difference(_playingSince!);
      _playingSince = null;
      _schedulePersist(immediate: true);
    }
    if (state.processing == BackendProcessing.completed && _loaded) {
      final serial = _loadSerial;
      if (state.playing && _completedSerial == serial) {
        // This end was already handled (the player was paused at it) and the platform player says it is playing again: that is the silent
        // "playing" of B-51. It is shown as paused; a person's Play or seek starts a new end.
        Log.warn('playback',
            'the player says playing after it finished; shown as paused');
      }
      _fire(() => _onCompleted(serial));
    }
    _emitSnapshot();
  }

  /// The backend moved to another source of the window.
  void _onBackendIndex(int? index) {
    if (index == null || index == _lastIndex) return;
    _trace(
        'platform player moved to slot $index (expected ${_expectedIndex ?? 'none'})');
    // The platform player hopped on by itself while a failure is being judged: hold it now, not when the judging is done.
    if (_judgingFailure && _loaded) {
      unawaited(
          _pause('the platform player hopped on while a failure is judged'));
    }
    // Nothing of ours is loaded (a restored queue waiting for play, or the
    // platform player starting up): an index event is the player's own, not
    // a gapless advance. Acting on it skipped a song after every restart (J-11).
    if (!_loaded) return;
    final serial = _loadSerial;
    _fire(() async {
      // A load finished meanwhile: this event describes the window that was
      // replaced, and acting on it would skip a song (B15).
      if (serial != _loadSerial) return;
      // An earlier queued operation may have taken the window away: a song that waits for its server or its connection has nothing loaded.
      // The platform player moves on to the next source by itself after a failure (just_audio does on Android); that is not a song that
      // ended, and the queue must not follow it (G-1).
      if (!_loaded) return;
      // Re-check: an earlier queued operation may have re-based the window.
      if (index == _lastIndex) return;
      if (_expectedIndex == index) {
        // We asked for this (skip/jump): the model is already there.
        _expectedIndex = null;
        _lastIndex = index;
      } else {
        // Gapless auto-advance: finish the old entry, move the model.
        _trace('the platform player went on by itself: the queue follows');
        _finishItem();
        _lastIndex = index;
        if (!_queue.advanceAuto()) {
          _emitAll();
          return;
        }
        if (_sleepAtEnd) {
          // Should not happen (window has no next), but never play on.
          await _pause('sleep at the end of the song: never play on');
        }
      }
      final item = _queue.current;
      if (item != null) {
        _nowPlayingSent = false;
        _listened = Duration.zero;
        _playingSince = _backend.state.playing ? _clock.now() : null;
        await _applyGain(item);
      }
      await _syncWindowTail();
      _emitAll();
      _schedulePersist(immediate: true);
    });
  }

  Future<void> _onCompleted(int serial) async {
    // Only reached when the window ran out (no next source) or sleep armed.
    // Pausing a finished player re-announces "completed": handle each
    // window's completion once.
    if (!_loaded || serial != _loadSerial || _completedSerial == serial) return;
    _completedSerial = serial;
    _trace('the window ran out');
    _finishItem();
    if (_sleepAtEnd) {
      _sleepAtEnd = false;
      _publishSleep(SleepTimerStatus.off);
      _queue.skipNext();
      await _loadCurrent(autoplay: false);
      return;
    }
    if (await _stepToPlayable(_queue.advanceAuto)) {
      await _loadCurrent(autoplay: true);
    } else {
      // End of the queue (or nothing ahead can play without a connection): wait on the last track. At a true end the next Play starts
      // the list over; with songs ahead that cannot play now it only plays this one again.
      await _pause('the list ended: nothing ahead can play');
      if (_loaded) await _backend.seek(Duration.zero);
      _endedQueue = !_queue.hasNext;
      _emitAll();
    }
  }

  void _onBackendError(BackendError error) {
    final attempt = _loadAttempt;
    _fire(() async {
      final item = _queue.current;
      if (item == null) return;
      // The preload of the next song failed while this one plays fine: leave
      // this one alone; the failure shows again if playback ever gets there.
      final last = _lastIndex;
      if (error.index != null && last != null && error.index != last) {
        Log.warn('playback',
            'backend error for window slot ${error.index}: ${error.message}');
        return;
      }
      // One failure is reported by more than one path (the error event and
      // the exception of the load); count it once.
      if (_handledErrorAttempt == attempt) return;
      _handledErrorAttempt = attempt;
      Log.warn('playback', 'backend error for ${item.id}: ${error.message}');
      // The platform player may already have hopped on to the next source by itself and be playing it, or hop in a moment, while the
      // network is being looked at (which can take seconds): hold it, so what is heard is never another song than the one shown (owner,
      // 2026-10-31: the next song plays under the title and cover of the previous one, "all covers"). A retry or a skip starts it again.
      final index = _backend.currentIndex;
      if (index != null && last != null && index != last) {
        await _pause('a failure: the platform player had already hopped on');
      }
      _judgingFailure = true;
      try {
        await _judgeFailure(item);
      } finally {
        _judgingFailure = false;
      }
    });
  }

  /// Whether the engine is deciding what a failure means (it may look at the network for seconds): a hop of the platform player meanwhile
  /// is held at once ([_onBackendIndex]).
  bool _judgingFailure = false;

  Future<void> _judgeFailure(QueueItem item) async {
    if (!await _playable(item)) {
      // The network is gone, the song is not broken: wait for it, never hop on to the next song.
      await _pause('no connection (a failure is judged)');
      _waitForConnection('Waiting for a connection.',
          isError: false, position: _lastPosition);
      return;
    }
    // The phone has a network. Before judging the song, look once at whether its server answers at all (the stream may have died
    // because the server restarted, or because the line changed): a server that does not answer is waited for, not hopped over.
    if (!await _serverAnswers() && !await _isLocal(item)) {
      await _pause('the server does not answer (a failure is judged)');
      _waitForServer(position: _lastPosition);
      return;
    }
    if (_retried.add(item.uid)) {
      // One quiet retry: the endpoint may have just switched networks, or
      // the platform player hit a transient start-up failure.
      await _loadCurrent(autoplay: true, position: _lastPosition);
      return;
    }
    _consecutiveFailures++;
    _notify(PlaybackNotice("Couldn't play ${item.title}", isError: true));
    if (_consecutiveFailures >= maxConsecutiveFailures || !_queue.skipNext()) {
      await _pause('too many failures, or the end of the queue');
      if (_consecutiveFailures >= maxConsecutiveFailures) {
        _notify(const PlaybackNotice(
            'Playback stopped: several tracks in a row failed. '
            'Check your connection.',
            isError: true));
      }
      _emitAll();
      return;
    }

    await _loadCurrent(autoplay: true);
  }

  /// The next two songs of the queue are handed to [_prepareAhead], each song once: when a song is loaded (the tap), when the queue changes (an
  /// album's next songs are queued one by one behind the first), and as a safety at every position tick once the music is moving (cheap: it looks
  /// at two entries). Nothing when the song repeats itself or the sleep timer ends the music after it (there is no next song to wait for).
  /// Owner, 7 Nov 2026: do not wait for the first song to be audible, a person skips (taps the 5th song while the 1st plays) and a little more asking
  /// is accepted; the server paces it.
  void _handOverTheNextSongs() {
    final hand = _prepareAhead;
    if (hand == null || _queue.current == null || !_loaded) return;
    if (_loopOne || _sleepAtEnd) return;
    final next = [
      for (final item in _queue.peekAhead(2))
        if (!_handedOver.contains(item.uid)) item,
    ];
    if (next.isEmpty) return;
    if (_handedOver.length > 400) _handedOver.clear();
    _handedOver.addAll(next.map((i) => i.uid));
    _trace('hand the next ${next.length} song(s) to the server to prepare');
    unawaited(hand(next).onError<Object>((error, _) {
      Log.debug('playback', 'preparing the next songs failed: $error');
    }));
  }

  void _onPosition(Duration position) {
    _lastPosition = position;
    // What the person waits for ends when the music is really moving: the position has passed 200 ms while the player plays (P1-06; the span
    // `play.tap->playing` ends earlier, when the player only says it plays).
    if (position > const Duration(milliseconds: 200) &&
        _backend.state.playing &&
        PerfMonitor.instance.isOpen('play.audible')) {
      PerfMonitor.instance.end('play.audible',
          detail: _audibleBySkip
              ? 'skip id=${_queue.current?.id}'
              : 'source=$_sourceKind id=${_queue.current?.id}');
    }
    if (position > const Duration(milliseconds: 200) &&
        _backend.state.playing) {
      _handOverTheNextSongs();
    }
    if (!_positions.isClosed) _positions.add(position);
    final last = _lastPersist;
    if (_backend.state.playing &&
        (last == null || _clock.now().difference(last) >= persistEvery)) {
      // Only the position: the queue has not changed (a change writes the
      // snapshot itself), and the snapshot of a long queue is not something
      // to rewrite every couple of seconds for hours.
      unawaited(_persistProgress());
    }
  }

  // ------------------------------------------------------------ bookkeeping

  /// Closes the listening accounting of the entry that is ending.
  void _finishItem() {
    final item = _queue.current;
    final now = _clock.now();
    if (_playingSince != null) {
      _listened += now.difference(_playingSince!);
      _playingSince = null;
    }
    final listened = _listened;
    _listened = Duration.zero;
    if (item == null || _recorder == null) return;
    final length = item.duration;
    final threshold = length == null
        ? const Duration(seconds: 30)
        : Duration(
            milliseconds:
                min(length.inMilliseconds ~/ 2, 240000).clamp(30000, 1 << 30),
          );
    if (listened >= threshold) {
      unawaited(_safePlayed(item, listened));
    }
  }

  Future<void> _safeNowPlaying(QueueItem item) async {
    try {
      await _recorder?.nowPlaying(item);
    } on Object catch (error) {
      Log.warn('playback', 'nowPlaying failed', error);
    }
  }

  Future<void> _safePlayed(QueueItem item, Duration listened) async {
    try {
      await _recorder?.played(item, listened: listened, source: _sourceName);
    } on Object catch (error) {
      Log.warn('playback', 'recordPlay failed', error);
    }
  }

  Future<void> _applyGain(QueueItem item) async {
    final s = _replayGain();
    final plan = planReplayGain(
      mode: s.mode,
      trackGain: item.rgTrackGain,
      albumGain: item.rgAlbumGain,
      trackPeak: item.rgTrackPeak,
      albumPeak: item.rgAlbumPeak,
      preampDb: s.preampDb,
      untaggedDb: s.untaggedDb,
      maxBoostDb: s.allowBoost ? 9 : 0,
    );
    _gainVolume = plan.volume;
    await _backend.setVolume(plan.volume);
    await _effects?.setLoudnessBoost(plan.boostDb);
  }

  void _notify(PlaybackNotice notice) {
    if (!_notices.isClosed) _notices.add(notice);
  }

  // -------------------------------------------------------------- emitting

  PlaybackSnapshot _build() {
    final item = _queue.current;
    final state = _backend.state;
    final duration = _backend.duration ?? item?.duration ?? Duration.zero;
    return PlaybackSnapshot(
      track: item == null
          ? null
          : NowPlayingTrack(
              id: item.id,
              title: item.title,
              artist: item.artist,
              album: item.album,
              albumId: item.albumId,
              artistId: item.artistId,
              catalogueArtistId: item.catalogueArtistId,
              coverArt: item.coverArt,
              duration: item.duration,
              suffix: item.suffix,
              bitRate: item.bitRate,
              imageUrl: item.imageUrl,
              videoId: item.videoId,
            ),
      isPlaying:
          state.playing && state.processing != BackendProcessing.completed,
      isLoading: state.processing == BackendProcessing.loading ||
          state.processing == BackendProcessing.buffering,
      position: _loaded ? _backend.position : _resumePosition,
      duration: duration,
      queueIndex: _queue.cursor,
      queueLength: _queue.length,
      shuffle: _queue.shuffle,
      repeat: switch (_queue.repeat) {
        QueueRepeat.off => RepeatKind.off,
        QueueRepeat.all => RepeatKind.all,
        QueueRepeat.one => RepeatKind.one,
      },
      hasNext: _queue.hasNext,
      // "Previous" always does something: restart or go back.
      hasPrevious: item != null,
      sourceName: _sourceName,
      sourceId: _sourceId,
    );
  }

  void _emitSnapshot() {
    if (_disposed) return;
    final next = _build();
    if (next == _last) return;
    _last = next;
    if (!_snapshots.isClosed) _snapshots.add(next);
  }

  void _emitAll() {
    _emitSnapshot();
    if (_disposed) return;
    final q = QueueSnapshot(items: _queue.ordered, currentIndex: _queue.cursor);
    if (q != _lastQueue) {
      _lastQueue = q;
      if (!_queueChanges.isClosed) _queueChanges.add(q);
    }
  }

  // ------------------------------------------------------------ persistence

  void _schedulePersist({bool immediate = false}) {
    if (_disposed) return;
    _persistDebounce?.cancel();
    if (immediate) {
      unawaited(_persistNow());
      return;
    }
    _persistDebounce =
        Timer(const Duration(seconds: 2), () => unawaited(_persistNow()));
  }

  Future<void> _persistNow() async {
    _lastPersist = _clock.now();
    if (_queue.isEmpty) {
      await _store.clear();
      return;
    }
    final position = _loaded ? _backend.position : _resumePosition;
    try {
      await _store.save(PersistedPlayback(
        queue: _queue.toJson(),
        positionMs: position.inMilliseconds,
        sourceName: _sourceName,
        sourceId: _sourceId,
      ));
    } on Object catch (error) {
      Log.warn('playback', 'could not save queue', error);
    }
    // The progress record must never be older than the snapshot just written
    // (a restore prefers it): refresh it with the same position.
    await _persistProgress();
  }

  /// Writes where the current song has got to, and only that (see
  /// [PlaybackProgress]): on every seek, with every snapshot, and every
  /// [persistEvery] while playing.
  Future<void> _persistProgress() async {
    _lastPersist = _clock.now();
    final current = _queue.current;
    if (current == null) return;
    final position = _loaded ? _backend.position : _resumePosition;
    try {
      await _store.saveProgress(PlaybackProgress(
          itemId: current.id, positionMs: position.inMilliseconds));
    } on Object catch (error) {
      Log.warn('playback', 'could not save position', error);
    }
  }

  @visibleForTesting
  List<int> get debugWindow => List.unmodifiable(_window);

  @visibleForTesting
  QueueModel get debugQueue => _queue;
}
