import 'dart:async';

import 'package:encore/playback/audio_backend.dart';

/// Deterministic stand-in for the platform player that reproduces the
/// *window* semantics the engine relies on: a short list of sources,
/// gapless auto-advance, index shifting when sources are removed.
///
/// All streams are synchronous so a test sees events in the exact order the
/// engine caused them.
class FakeAudioBackend implements AudioBackend {
  final List<AudioSourceSpec> sources = [];
  int? _index;
  BackendState _state = const BackendState();
  Duration _position = Duration.zero;
  Duration? _duration = const Duration(minutes: 3);
  double volume = 1;
  double speed = 1;
  bool loopOne = false;
  bool disposed = false;

  /// When set, [setSources] waits for it: a slow network load (docs/23, B8).
  Completer<void>? setSourcesGate;

  // Call log for assertions.
  final List<String> calls = [];
  int setSourcesCount = 0;

  final _state$ = StreamController<BackendState>.broadcast(sync: true);
  final _position$ = StreamController<Duration>.broadcast(sync: true);
  final _duration$ = StreamController<Duration?>.broadcast(sync: true);
  final _index$ = StreamController<int?>.broadcast(sync: true);
  final _errors$ = StreamController<BackendError>.broadcast(sync: true);

  // ------------------------------------------------------------ AudioBackend

  @override
  BackendState get state => _state;
  @override
  Stream<BackendState> get stateStream => _state$.stream;
  @override
  Duration get position => _position;
  @override
  Stream<Duration> get positionStream => _position$.stream;
  @override
  Duration? get duration => _duration;
  @override
  Stream<Duration?> get durationStream => _duration$.stream;
  @override
  int? get currentIndex => _index;
  @override
  Stream<int?> get currentIndexStream => _index$.stream;
  @override
  Stream<BackendError> get errors => _errors$.stream;
  @override
  int? get androidAudioSessionId => 7;

  @override
  Future<void> setSources(
    List<AudioSourceSpec> newSources, {
    int index = 0,
    Duration position = Duration.zero,
  }) async {
    calls.add('setSources(${newSources.map((s) => s.uid).join(',')} '
        '@$index +${position.inSeconds}s)');
    setSourcesCount++;
    await setSourcesGate?.future;
    sources
      ..clear()
      ..addAll(newSources);
    _position = position;
    _setIndex(newSources.isEmpty ? null : index);
    _setState(BackendState(
      playing: _state.playing,
      processing:
          newSources.isEmpty ? BackendProcessing.idle : BackendProcessing.ready,
    ));
  }

  @override
  Future<void> removeFirst(int count) async {
    calls.add('removeFirst($count)');
    sources.removeRange(0, count);
    if (_index != null) _setIndex(_index! - count);
  }

  @override
  Future<void> append(AudioSourceSpec source) async {
    calls.add('append(${source.uid})');
    sources.add(source);
  }

  @override
  Future<void> removeAt(int index) async {
    calls.add('removeAt($index)');
    sources.removeAt(index);
    if (_index != null && index < _index!) _setIndex(_index! - 1);
  }

  @override
  Future<void> seek(Duration position, {int? index}) async {
    calls
        .add('seek(${position.inSeconds}s${index == null ? '' : ', @$index'})');
    if (index != null) _setIndex(index);
    _position = position;
    _position$.add(position);
    // Like the real player (just_audio): a seek takes a finished player out of "completed". Without this a test cannot tell a player that has
    // finished again from one that never left the end (P1-21, B-51).
    if (_state.processing == BackendProcessing.completed) {
      _setState(BackendState(
          playing: _state.playing, processing: BackendProcessing.ready));
    }
  }

  @override
  Future<void> play() async {
    calls.add('play');
    _setState(BackendState(playing: true, processing: _state.processing));
  }

  @override
  Future<void> pause() async {
    calls.add('pause');
    _setState(BackendState(playing: false, processing: _state.processing));
  }

  @override
  Future<void> stop() async {
    calls.add('stop');
    sources.clear();
    _setIndex(null);
    _setState(const BackendState());
  }

  @override
  Future<void> setVolume(double v) async {
    calls.add('volume(${v.toStringAsFixed(2)})');
    volume = v;
  }

  @override
  Future<void> setSpeed(double s) async {
    calls.add('speed($s)');
    speed = s;
  }

  @override
  Future<void> setLoopOne(bool loop) async {
    loopOne = loop;
  }

  @override
  Future<void> dispose() async {
    disposed = true;
    await _state$.close();
    await _position$.close();
    await _duration$.close();
    await _index$.close();
    await _errors$.close();
  }

  // ------------------------------------------------------------ test controls

  /// What the player reports as the length of what is loaded: a 30-second
  /// sample of a three-minute song is 29 s here, whatever the catalogue says.
  void setDuration(Duration? value) {
    _duration = value;
    _duration$.add(value);
  }

  /// Uid of the source that is playing.
  int? get currentUid =>
      _index == null || _index! >= sources.length ? null : sources[_index!].uid;

  /// The current source ends naturally (gapless advance / loop / completion).
  void finishCurrent() {
    if (loopOne) {
      _position = Duration.zero;
      _position$.add(_position);
      return;
    }
    if (_index != null && _index! + 1 < sources.length) {
      _position = Duration.zero;
      _setIndex(_index! + 1);
    } else {
      _setState(BackendState(
        playing: _state.playing,
        processing: BackendProcessing.completed,
      ));
    }
  }

  /// Pushes a playback position (and remembers it).
  void emitPosition(Duration position) {
    _position = position;
    _position$.add(position);
  }

  /// The platform player reports a failure for the current source.
  void failCurrent([String message = 'Source error']) {
    _errors$.add(BackendError(message, index: _index));
  }

  /// The platform player reports a failure for the current source and then moves on to the next source of the window by itself (just_audio
  /// on Android does: seekTo(next), prepare, play), as seen on a phone with the server stopped mid-song (docs/evidence b04).
  void failCurrentAndHop([String message = 'Source error']) {
    final from = _index;
    _errors$.add(BackendError(message, index: from));
    if (from != null && from + 1 < sources.length) {
      _position = Duration.zero;
      _setIndex(from + 1);
    }
  }

  /// The platform player reports a failure for another source of the window
  /// (typically the next one, while the current song plays fine).
  void failSlot(int index, [String message = 'Source error']) {
    _errors$.add(BackendError(message, index: index));
  }

  void emitState(BackendState state) => _setState(state);

  /// The platform player announcing that its current item changed (it also
  /// does so for its own start-up, with nothing of ours loaded).
  void emitIndex(int? index) => _setIndex(index);

  void _setIndex(int? index) {
    final changed = index != _index;
    _index = index;
    if (changed) _index$.add(index);
  }

  void _setState(BackendState state) {
    if (state == _state) return;
    _state = state;
    _state$.add(state);
  }
}
