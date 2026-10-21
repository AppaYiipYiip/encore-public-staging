import 'package:flutter/foundation.dart';

/// One playable source handed to the audio backend.
@immutable
class AudioSourceSpec {
  const AudioSourceSpec({
    required this.uid,
    required this.uri,
    this.isLocal = false,
  });

  /// `QueueItem.uid` this source belongs to (also the tag on the platform
  /// side, so events can be mapped back to the queue).
  final int uid;
  final Uri uri;

  /// A file on this phone (a finished download).
  final bool isLocal;

  @override
  String toString() => 'AudioSourceSpec($uid, ${isLocal ? 'file' : 'stream'})';
}

enum BackendProcessing { idle, loading, buffering, ready, completed }

@immutable
class BackendState {
  const BackendState({
    this.playing = false,
    this.processing = BackendProcessing.idle,
  });

  final bool playing;
  final BackendProcessing processing;

  @override
  bool operator ==(Object other) =>
      other is BackendState &&
      other.playing == playing &&
      other.processing == processing;

  @override
  int get hashCode => Object.hash(playing, processing);

  @override
  String toString() => 'BackendState(playing: $playing, $processing)';
}

/// A playback failure reported by the platform player.
@immutable
class BackendError {
  const BackendError(this.message, {this.index, this.cause});

  final String message;

  /// Window index the error belongs to, when known.
  final int? index;
  final Object? cause;

  @override
  String toString() => 'BackendError($message, index: $index)';
}

/// The thin seam between the playback engine and a platform audio player
/// (ADR-035). The engine never imports `just_audio`; tests use a fake that
/// reproduces the *window* semantics (a short list of sources with gapless
/// auto-advance), which is where the interesting bugs live.
abstract interface class AudioBackend {
  BackendState get state;
  Stream<BackendState> get stateStream;

  Duration get position;
  Stream<Duration> get positionStream;

  Duration? get duration;
  Stream<Duration?> get durationStream;

  /// Index of the playing source within the loaded window (`null` when idle).
  int? get currentIndex;
  Stream<int?> get currentIndexStream;

  Stream<BackendError> get errors;

  /// Replaces the whole window. Playback state (play/pause) is unchanged.
  Future<void> setSources(
    List<AudioSourceSpec> sources, {
    int index = 0,
    Duration position = Duration.zero,
  });

  /// Drops the first [count] sources (they are behind us) without
  /// interrupting the one that is playing.
  Future<void> removeFirst(int count);

  /// Adds [source] after the last one.
  Future<void> append(AudioSourceSpec source);

  /// Removes the source at [index] (must not be the playing one).
  Future<void> removeAt(int index);

  /// Seeks within the current source, or jumps to [index] when given.
  Future<void> seek(Duration position, {int? index});

  Future<void> play();
  Future<void> pause();
  Future<void> stop();

  /// 0..1 (ReplayGain attenuation, fades).
  Future<void> setVolume(double volume);
  Future<void> setSpeed(double speed);

  /// Seamless single-track loop (repeat one).
  Future<void> setLoopOne(bool loop);

  /// Linear boost above 0 dB in milli-bel units is applied by the effects
  /// layer; the backend only exposes the audio session id for it.
  int? get androidAudioSessionId;

  Future<void> dispose();
}
