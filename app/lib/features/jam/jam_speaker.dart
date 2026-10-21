import 'dart:async';

import 'package:encore_session/encore_session.dart';

import '../player/playback_facade.dart';
import 'jam_providers.dart';

/// Starts a Jam entry on this phone: finds the song in this person's own
/// library by title and artist, or has the server fetch it, and plays it.
abstract interface class JamSongPlayer {
  /// `false` when the song cannot be found or fetched.
  Future<bool> play(QueueEntry entry);

  /// Gets [entry] ahead of its turn (a song this phone does not have is
  /// fetched while the one before it plays), so that when its turn comes it is
  /// there. Never plays anything; never fails loudly.
  Future<void> preload(QueueEntry entry);

  /// This phone is already playing that very song (a Jam begun on a song that
  /// was playing): it goes on, it is not started again.
  bool alreadyPlaying(QueueEntry entry);
}

/// The phone that plays in a Jam (docs/30: "one speaker": everybody else is a
/// remote). It does what the Jam says, tells the Jam what really happens (the
/// song ended, somebody paused it from the lock screen, where the music really
/// is after a slow start) and says out loud when it cannot play a song.
class JamSpeaker {
  JamSpeaker({
    required this.facade,
    required this.songs,
    required this.send,
    required this.positionNowMs,
    required this.notify,
    this.onLoading,
    this.settleFor = const Duration(milliseconds: 1500),
    this.silenceOldAfter = const Duration(milliseconds: 400),
  });

  final PlaybackFacade facade;
  final JamSongPlayer songs;

  /// Sends a command to the Jam.
  final Future<bool> Function(Command command) send;

  /// Where the current song is by the hub's clock.
  final int Function() positionNowMs;

  /// Tells the person something (a snackbar).
  final void Function(String message) notify;

  /// Told when this phone starts and stops getting the Jam's song (a song it
  /// does not have is fetched first): the player shows it is loading.
  final void Function(bool loading)? onLoading;

  /// When a song is not there within this long, the song before it is stopped:
  /// the new title must not be played over the old song for the half minute a
  /// fetch takes (seen on a real phone, 2026-10-17).
  final Duration silenceOldAfter;

  /// How long snapshots that still show the old state are taken as "an older
  /// picture of it" after this phone told the player to play or pause.
  final Duration settleFor;

  /// How close to the end counts as "the song ended".
  static const _endSlack = Duration(milliseconds: 800);

  /// How far off the music may be before it is moved.
  static const _seekAbove = 1500;

  /// How many songs after the current one are got ahead of time: a few minutes
  /// of music, and not a whole queue that may be changed in a minute.
  static const _preloadAhead = 2;

  /// The songs already asked for, by their place's id in the Jam.
  final Set<int> _preloaded = {};

  StreamSubscription<Duration>? _positions;
  StreamSubscription<PlaybackSnapshot>? _snapshots;

  bool _speaking = false;

  /// This phone does not play in the Jam and has been told to be quiet once.
  bool _silenced = false;
  int? _uid;
  int? _lastRev;
  Anchor? _lastAnchor;
  int? _reportedEnd;
  bool? _expectedPlaying;
  bool _started = false;
  bool _aligning = false;

  /// Set when this phone told the player to play or pause: snapshots that still
  /// show the old state are on their way and are not the person's doing.
  final Stopwatch _commandedAt = Stopwatch();
  bool _settling = false;
  bool _loading = false;
  int _generation = 0;

  /// The last place this phone moved the music to, and when: the hub's own
  /// confirmation of the same seek, a moment later, must not move it again.
  int _seekedTo = 0;
  final Stopwatch _seekedAt = Stopwatch();
  Duration _position = Duration.zero;
  Duration _duration = Duration.zero;

  /// Starts listening to the player (call once).
  void attach() {
    _duration = facade.snapshot.duration;
    _positions = facade.positionStream.listen(_onPosition);
    _snapshots = facade.snapshots.listen(_onSnapshot);
  }

  void dispose() {
    _positions?.cancel();
    _snapshots?.cancel();
  }

  void _forget() {
    _uid = null;
    _lastRev = null;
    _lastAnchor = null;
    _reportedEnd = null;
    _expectedPlaying = null;
    _started = false;
    _aligning = false;
    _settling = false;
    _setLoading(false);
    _preloaded.clear();
    _seekedAt
      ..stop()
      ..reset();
    _generation++;
    _duration = Duration.zero;
  }

  /// The Jam changed (or the person left it): do what it now says.
  Future<void> onSession(JamSession session) async {
    final state = session.state;
    final plays = session.iPlay && state != null && !state.ended;
    if (!plays) {
      if (_speaking) {
        _speaking = false;
        _forget();
        await facade.pause();
      }
      // A phone that listens along does not play: whatever it was playing for
      // itself must not go on under the Jam. Told once, when it joins.
      if (session.inJam && state != null && !state.ended) {
        if (!_silenced) {
          _silenced = true;
          await facade.pause();
        }
      } else {
        _silenced = false;
      }
      return;
    }
    _silenced = false;
    _speaking = true;
    final entry = state.current;
    if (entry == null) {
      if (_uid != null) {
        _forget();
        await facade.pause();
      }
      return;
    }
    if (state.rev == _lastRev && entry.uid == _uid) {
      return; // the same state again
    }
    _lastRev = state.rev;
    final anchorMoved = state.anchor != _lastAnchor;
    _lastAnchor = state.anchor;
    if (entry.uid != _uid) {
      await _load(entry, state);
    } else {
      await _follow(state, anchorMoved: anchorMoved);
    }
    _getComingUp(state);
  }

  /// Gets the next few songs while this one plays. Not while the current song
  /// is still being got: the line is slow and the song people are waiting for
  /// comes first.
  void _getComingUp(SessionState state) {
    if (_loading || !_speaking) return;
    final from = state.index + 1;
    final to = (state.index + _preloadAhead).clamp(0, state.queue.length - 1);
    for (var i = from; i <= to; i++) {
      final next = state.queue[i];
      if (_preloaded.add(next.uid)) unawaited(songs.preload(next));
    }
  }

  Future<void> _load(QueueEntry entry, SessionState state) async {
    final generation = ++_generation;
    _uid = entry.uid;
    _reportedEnd = null;
    _started = false;
    _duration = Duration.zero;
    // While the song loads the player does what it likes (it starts playing the
    // moment it is ready, whatever the Jam says): that is not the person's doing
    // and the settling clock must not run out during it (found on the real
    // server: a slow load of a paused song told the Jam "play").
    _setLoading(true);
    // A song that takes more than a blink to get silences the old one.
    final silence = Timer(silenceOldAfter, () {
      if (generation == _generation) unawaited(facade.pause());
    });
    final bool ok;
    try {
      ok = songs.alreadyPlaying(entry) || await songs.play(entry);
    } finally {
      silence.cancel();
    }
    if (generation != _generation) return; // the Jam moved on while it loaded
    _setLoading(false);
    _expect(state.playing);
    if (!ok) {
      notify('Could not play "${entry.title ?? 'a song'}" on this phone. '
          'Skipping it.');
      await send(state.playing ? Ended(entry.uid) : const Next());
      return;
    }
    if (!state.playing) {
      await facade.pause();
    } else {
      _started = facade.snapshot.isPlaying;
      // The song may have had to be fetched: by now the Jam's clock is ahead of
      // the music. Where the music really is wins: the Jam is told.
      _aligning = true;
    }
  }

  Future<void> _follow(SessionState state, {required bool anchorMoved}) async {
    if (state.playing != _expectedPlaying) {
      _expect(state.playing);
      if (state.playing) {
        await facade.play();
      } else {
        await facade.pause();
      }
    }
    if (anchorMoved) {
      final hub = positionNowMs();
      if ((hub - _position.inMilliseconds).abs() > _seekAbove &&
          !_alreadyMovedThere(hub, state.playing)) {
        _seekedTo = hub;
        _seekedAt
          ..reset()
          ..start();
        await facade.seek(Duration(milliseconds: hub));
      }
    }
  }

  /// This phone moved the music to about [hub] a moment ago and the player has
  /// not caught up yet: the Jam is only confirming it.
  bool _alreadyMovedThere(int hub, bool playing) {
    if (!_seekedAt.isRunning ||
        _seekedAt.elapsed > const Duration(seconds: 8)) {
      return false;
    }
    final since = playing ? _seekedAt.elapsedMilliseconds : 0;
    return (hub - (_seekedTo + since)).abs() <= _seekAbove;
  }

  void _setLoading(bool value) {
    if (_loading == value) return;
    _loading = value;
    onLoading?.call(value);
  }

  void _onPosition(Duration position) {
    _position = position;
    final uid = _uid;
    if (!_speaking || uid == null) return;
    if (_aligning) {
      _aligning = false;
      final hub = positionNowMs();
      if ((hub - position.inMilliseconds).abs() > _seekAbove) {
        unawaited(send(Seek(position.inMilliseconds)));
      }
    }
    if (_expectedPlaying == false) {
      return;
    }
    if (_duration > Duration.zero &&
        position >= _duration - _endSlack &&
        _reportedEnd != uid) {
      _reportedEnd = uid;
      unawaited(send(Ended(uid)));
    }
  }

  void _expect(bool playing) {
    _expectedPlaying = playing;
    _settling = true;
    _commandedAt
      ..reset()
      ..start();
  }

  void _onSnapshot(PlaybackSnapshot snapshot) {
    _duration = snapshot.duration;
    if (!_speaking || _uid == null || _loading || snapshot.isLoading) return;
    final expected = _expectedPlaying;
    if (expected == null) return;
    if (expected && !_started) {
      // Until the song has really started, "not playing" is loading, not a pause.
      if (snapshot.isPlaying) {
        _started = true;
        _settling = false; // it is playing, as asked
      }
      return;
    }
    if (_settling) {
      if (snapshot.isPlaying == expected) {
        _settling = false; // the player caught up with what was asked
        return;
      }
      if (_commandedAt.elapsed < settleFor) return; // an older picture of it
      _settling = false;
    }
    if (snapshot.isPlaying != expected) {
      // The person did it on this phone (the lock screen, a headset button).
      _expectedPlaying = snapshot.isPlaying;
      unawaited(send(snapshot.isPlaying ? const Play() : const Pause()));
    }
  }
}
