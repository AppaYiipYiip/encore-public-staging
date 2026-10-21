import 'dart:async';
import 'dart:io' show Platform;

import 'package:flutter/foundation.dart';
import 'package:just_audio/just_audio.dart' as ja;

import '../core/logger.dart';
import '../core/perf.dart';
import 'audio_backend.dart';
import 'audio_units.dart';
import 'playback_engine.dart' show AudioEffects;
import 'position_pump.dart';

/// [AudioBackend] on top of `just_audio` (ExoPlayer on Android).
///
/// The platform playlist is a `ConcatenatingAudioSource` that the engine keeps
/// at one to three entries (ADR-035). The Android equaliser and loudness
/// enhancer are part of the player's audio pipeline, so they must be created
/// together with the player - they are exposed for the equaliser screen.
class JustAudioBackend implements AudioBackend, AudioEffects {
  JustAudioBackend({bool enableEffects = true}) {
    final canEffects = enableEffects && !kIsWeb && Platform.isAndroid;
    equalizer = canEffects ? ja.AndroidEqualizer() : null;
    loudness = canEffects ? ja.AndroidLoudnessEnhancer() : null;
    _player = ja.AudioPlayer(
      audioPipeline: ja.AudioPipeline(
        androidAudioEffects: [
          if (equalizer != null) equalizer!,
          if (loudness != null) loudness!,
        ],
      ),
      handleInterruptions: true,
      androidApplyAudioAttributes: true,
    );

    // The library's own positionStream polls every 16 ms while the duration
    // is unknown and never stops, even paused (~20% of a core); the pump ticks
    // only while audio plays.
    _pump = PositionPump(
      read: () => _player.position,
      emit: (p) {
        if (!_positionController.isClosed) _positionController.add(p);
      },
    );

    _subs
      ..add(_player.playerStateStream.listen((s) {
        _state = BackendState(
          playing: s.playing,
          processing: _map(s.processingState),
        );
        _stateController.add(_state);
        _pump.update(
          running: s.playing && s.processingState == ja.ProcessingState.ready,
        );
      }))
      ..add(_player.currentIndexStream.listen(_indexController.add))
      ..add(_player.durationStream.listen(_durationController.add))
      ..add(_player.playbackEventStream.listen(
        (_) => _pump.poke(),
        onError: (Object error, StackTrace stack) {
          final message =
              error is ja.PlayerException ? error.message : error.toString();
          Log.warn('audio', 'player error: $message');
          _errors.add(BackendError(message ?? 'Playback error',
              index: _player.currentIndex, cause: error));
        },
      ));
  }

  late final ja.AudioPlayer _player;
  late final PositionPump _pump;

  /// Null when the platform has no effect support.
  late final ja.AndroidEqualizer? equalizer;
  late final ja.AndroidLoudnessEnhancer? loudness;

  final List<StreamSubscription<Object?>> _subs = [];
  final StreamController<BackendState> _stateController =
      StreamController<BackendState>.broadcast();
  final StreamController<int?> _indexController =
      StreamController<int?>.broadcast();
  final StreamController<Duration?> _durationController =
      StreamController<Duration?>.broadcast();
  final StreamController<Duration> _positionController =
      StreamController<Duration>.broadcast();
  final StreamController<BackendError> _errors =
      StreamController<BackendError>.broadcast();

  ja.ConcatenatingAudioSource? _playlist;
  BackendState _state = const BackendState();

  static BackendProcessing _map(ja.ProcessingState s) => switch (s) {
        ja.ProcessingState.idle => BackendProcessing.idle,
        ja.ProcessingState.loading => BackendProcessing.loading,
        ja.ProcessingState.buffering => BackendProcessing.buffering,
        ja.ProcessingState.ready => BackendProcessing.ready,
        ja.ProcessingState.completed => BackendProcessing.completed,
      };

  static ja.AudioSource _source(AudioSourceSpec spec) =>
      ja.AudioSource.uri(spec.uri, tag: spec.uid);

  // ------------------------------------------------------------------ read

  @override
  BackendState get state => _state;

  @override
  Stream<BackendState> get stateStream => _stateController.stream;

  @override
  Duration get position => _player.position;

  @override
  Stream<Duration> get positionStream => _positionController.stream;

  @override
  Duration? get duration => _player.duration;

  @override
  Stream<Duration?> get durationStream => _durationController.stream;

  @override
  int? get currentIndex => _player.currentIndex;

  @override
  Stream<int?> get currentIndexStream => _indexController.stream;

  @override
  Stream<BackendError> get errors => _errors.stream;

  @override
  int? get androidAudioSessionId => _player.androidAudioSessionId;

  // --------------------------------------------------------------- control

  /// Creates the platform player and the effect chain ahead of the first
  /// play, so the first tap does not pay for ExoPlayer start-up (about 1.9 s
  /// measured on the emulator, docs/11-feedback-log.md FB-004).
  Future<void> warmUp() async {
    final timer = Stopwatch()..start();
    try {
      await _player.setAudioSource(ja.ConcatenatingAudioSource(children: []));
    } on Object catch (error) {
      Log.debug('audio', 'warm-up skipped: $error');
    }
    PerfMonitor.instance.note('audio warm-up ${timer.elapsedMilliseconds}ms');
  }

  @override
  Future<void> setSources(
    List<AudioSourceSpec> sources, {
    int index = 0,
    Duration position = Duration.zero,
  }) async {
    if (sources.isEmpty) {
      await stop();
      return;
    }
    final playlist = ja.ConcatenatingAudioSource(
      children: [for (final s in sources) _source(s)],
    );
    _playlist = playlist;
    try {
      await _player.setAudioSource(
        playlist,
        initialIndex: index,
        initialPosition: position,
        preload: true,
      );
    } on ja.PlayerInterruptedException {
      // A newer load superseded this one; the engine owns what happens next.
    } on ja.PlayerException catch (error) {
      _errors.add(BackendError(error.message ?? 'Playback error',
          index: _player.currentIndex, cause: error));
    }
  }

  @override
  Future<void> removeFirst(int count) async {
    final playlist = _playlist;
    if (playlist == null || count <= 0) return;
    await playlist.removeRange(0, count);
  }

  @override
  Future<void> append(AudioSourceSpec source) async {
    await _playlist?.add(_source(source));
  }

  @override
  Future<void> removeAt(int index) async {
    await _playlist?.removeAt(index);
  }

  @override
  Future<void> seek(Duration position, {int? index}) =>
      _player.seek(position, index: index);

  @override
  Future<void> play() async {
    // `play()` completes when playback *ends*; do not await it.
    unawaited(_player.play().catchError((Object error) {
      Log.warn('audio', 'play() failed', error);
    }));
  }

  @override
  Future<void> pause() => _player.pause();

  @override
  Future<void> stop() async {
    await _player.stop();
    _playlist = null;
  }

  @override
  Future<void> setVolume(double volume) => _player.setVolume(volume);

  @override
  Future<void> setSpeed(double speed) => _player.setSpeed(speed);

  @override
  Future<void> setLoopOne(bool loop) =>
      _player.setLoopMode(loop ? ja.LoopMode.one : ja.LoopMode.off);

  // -------------------------------------------------------------- effects

  @override
  Future<void> setLoudnessBoost(double db) async {
    final enhancer = loudness;
    if (enhancer == null) return;
    try {
      if (db <= 0) {
        if (enhancer.enabled) await enhancer.setEnabled(false);
        return;
      }
      await enhancer.setTargetGain(toPlatformGain(db));
      if (!enhancer.enabled) await enhancer.setEnabled(true);
    } on Object catch (error) {
      // Effects are unavailable until the first source is loaded.
      Log.debug('audio', 'loudness boost not applied: $error');
    }
  }

  @override
  Future<void> dispose() async {
    _pump.dispose();
    for (final s in _subs) {
      await s.cancel();
    }
    await _player.dispose();
    await _stateController.close();
    await _indexController.close();
    await _durationController.close();
    await _positionController.close();
    await _errors.close();
  }
}
