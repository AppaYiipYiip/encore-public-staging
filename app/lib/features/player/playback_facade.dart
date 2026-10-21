import 'package:flutter/foundation.dart';

import '../../data/db/app_database.dart';
import '../../playback/queue_model.dart';

/// What the UI needs to know about the playing track (a thin view; the engine
/// keeps its own richer model).
@immutable
class NowPlayingTrack {
  const NowPlayingTrack({
    required this.id,
    required this.title,
    this.artist,
    this.album,
    this.albumId,
    this.artistId,
    this.catalogueArtistId,
    this.coverArt,
    this.duration,
    this.suffix,
    this.bitRate,
    this.imageUrl,
    this.fullSong = false,
  });

  factory NowPlayingTrack.fromRow(TrackRow t) => NowPlayingTrack(
        id: t.id,
        title: t.title,
        artist: t.artist,
        album: t.album,
        albumId: t.albumId,
        artistId: t.artistId,
        coverArt: t.coverArt,
        duration:
            t.durationSec == null ? null : Duration(seconds: t.durationSec!),
        suffix: t.suffix,
        bitRate: t.bitRate,
      );

  final String id;
  final String title;
  final String? artist;
  final String? album;
  final String? albumId;
  final String? artistId;

  /// The catalogue's id of the artist, for a song that is not in the library
  /// (a sample or a song the service plays): the artist page to open.
  final String? catalogueArtistId;
  final String? coverArt;
  final Duration? duration;
  final String? suffix;
  final int? bitRate;

  /// Direct artwork URL (catalogue items without a server cover id).
  final String? imageUrl;

  /// A whole song although it has a catalogue cover: a Jam's song, or one the
  /// service streams. Without it a song with only a cover address is taken for
  /// the 30-second clip of the catalogue (no lyrics, no like).
  final bool fullSong;

  @override
  bool operator ==(Object other) => other is NowPlayingTrack && other.id == id;

  @override
  int get hashCode => id.hashCode;
}

enum RepeatKind { off, all, one }

/// A catalogue sample (30 s) that can be queued without being in the library.
@immutable
class PreviewTrack {
  const PreviewTrack({
    required this.id,
    required this.title,
    required this.uri,
    this.artist,
    this.catalogueArtistId,
    this.album,
    this.imageUrl,
    this.duration,
    this.fullSong = false,
  });

  final String id;
  final String title;
  final Uri uri;
  final String? artist;

  /// The whole song, played from the instant-play service (not a 30-second
  /// sample): heard to the end it counts as a play, as any song does.
  final bool fullSong;

  /// The catalogue's id of [artist] (see [NowPlayingTrack.catalogueArtistId]).
  final String? catalogueArtistId;
  final String? album;
  final String? imageUrl;
  final Duration? duration;
}

@immutable
class PlaybackSnapshot {
  const PlaybackSnapshot({
    this.track,
    this.isPlaying = false,
    this.isLoading = false,
    this.position = Duration.zero,
    this.duration = Duration.zero,
    this.queueIndex = -1,
    this.queueLength = 0,
    this.shuffle = false,
    this.repeat = RepeatKind.off,
    this.hasNext = false,
    this.hasPrevious = false,
    this.sourceName,
    this.sourceId,
  });

  static const PlaybackSnapshot idle = PlaybackSnapshot();

  final NowPlayingTrack? track;
  final bool isPlaying;
  final bool isLoading;
  final Duration position;
  final Duration duration;
  final int queueIndex;
  final int queueLength;
  final bool shuffle;
  final RepeatKind repeat;
  final bool hasNext;
  final bool hasPrevious;

  /// "Playing from ..." label.
  final String? sourceName;

  /// Stable id of the collection being played (`playlist:ID`, `album:ID`...),
  /// so a page can tell whether *it* is what is playing.
  final String? sourceId;

  bool get hasTrack => track != null;

  @override
  bool operator ==(Object other) =>
      other is PlaybackSnapshot &&
      other.track == track &&
      other.isPlaying == isPlaying &&
      other.isLoading == isLoading &&
      other.duration == duration &&
      other.queueIndex == queueIndex &&
      other.queueLength == queueLength &&
      other.shuffle == shuffle &&
      other.repeat == repeat &&
      other.hasNext == hasNext &&
      other.hasPrevious == hasPrevious &&
      other.sourceName == sourceName &&
      other.sourceId == sourceId;

  @override
  int get hashCode => Object.hash(
      track,
      isPlaying,
      isLoading,
      duration,
      queueIndex,
      queueLength,
      shuffle,
      repeat,
      hasNext,
      hasPrevious,
      sourceName,
      sourceId);
}

/// The queue as the UI shows it (play order, including what already played).
@immutable
class QueueSnapshot {
  const QueueSnapshot({this.items = const [], this.currentIndex = -1});

  static const QueueSnapshot empty = QueueSnapshot();

  final List<QueueItem> items;
  final int currentIndex;

  List<QueueItem> get upNext => currentIndex < 0 || currentIndex >= items.length
      ? const []
      : items.sublist(currentIndex + 1);

  @override
  bool operator ==(Object other) =>
      other is QueueSnapshot &&
      other.currentIndex == currentIndex &&
      listEquals(other.items, items);

  @override
  int get hashCode => Object.hash(currentIndex, Object.hashAll(items));
}

enum SleepTimerMode { off, countdown, endOfTrack }

@immutable
class SleepTimerStatus {
  const SleepTimerStatus(
      {this.mode = SleepTimerMode.off, this.remaining = Duration.zero});

  static const SleepTimerStatus off = SleepTimerStatus();

  final SleepTimerMode mode;
  final Duration remaining;

  @override
  bool operator ==(Object other) =>
      other is SleepTimerStatus &&
      other.mode == mode &&
      other.remaining == remaining;

  @override
  int get hashCode => Object.hash(mode, remaining);
}

/// Something the user should be told about (shown as a snackbar).
@immutable
class PlaybackNotice {
  const PlaybackNotice(this.message, {this.isError = false});

  final String message;
  final bool isError;
}

/// The UI's only dependency on the playback engine (ADR-012). The legacy
/// `PlayerProvider` implements it today; the engine can be refactored behind
/// this seam without touching screens.
abstract interface class PlaybackFacade {
  /// Current state; changes are announced on [snapshots]. Position updates are
  /// *not* part of [snapshots] (they would rebuild everything 4x/second) -
  /// use [positionStream] for scrubbers.
  PlaybackSnapshot get snapshot;
  Stream<PlaybackSnapshot> get snapshots;
  Stream<Duration> get positionStream;

  Future<void> playTracks(
    List<TrackRow> tracks, {
    int startIndex = 0,
    String? sourceName,
    String? sourceId,
    bool shuffle = false,
  });

  Future<void> togglePlayPause();
  Future<void> play();
  Future<void> pause();
  Future<void> seek(Duration position);
  Future<void> skipNext();
  Future<void> skipPrevious();
  void toggleShuffle();
  void cycleRepeat();

  /// Sets the repeat mode directly (the car and the lock screen ask for a
  /// mode, not for "the next one").
  void setRepeat(RepeatKind kind);
  Future<void> addToQueue(TrackRow track);
  Future<void> playNext(TrackRow track);

  /// Plays a catalogue sample that is not in the library.
  Future<void> playPreview({
    required String id,
    required String title,
    required Uri uri,
    String? artist,
    String? catalogueArtistId,
    String? album,
    String? imageUrl,
    Duration? duration,
  });

  /// Plays a run of catalogue samples one after the other, starting at
  /// [startIndex] (an album or an artist's top songs).
  Future<void> playPreviews(
    List<PreviewTrack> tracks, {
    int startIndex = 0,
    String? sourceName,
    String? sourceId,
  });

  /// Adds a song that has a stream address but no library row (a song just
  /// fetched by the instant-play service) to the end of the queue.
  Future<void> addStreamToQueue(PreviewTrack track);

  // ---- queue ------------------------------------------------------------

  QueueSnapshot get queue;
  Stream<QueueSnapshot> get queueStream;
  Future<void> jumpToQueueIndex(int index);
  Future<void> removeFromQueue(int index);
  Future<void> moveInQueue(int from, int to);
  Future<void> clearUpNext();

  /// Stops playback and empties the queue, also the saved copy (signing out:
  /// nothing of the old account may be waiting to resume).
  Future<void> stopAndClear();

  // ---- sleep timer / speed / notices -----------------------------------

  SleepTimerStatus get sleepTimer;
  Stream<SleepTimerStatus> get sleepTimerStream;

  /// Counts down [duration] then fades out and pauses; `null` cancels.
  Future<void> setSleepTimer(Duration? duration);

  /// Pauses when the current track ends.
  Future<void> setSleepAtEndOfTrack(bool enabled);

  double get speed;
  Future<void> setSpeed(double speed);

  Stream<PlaybackNotice> get notices;
}

/// Used in previews/tests and before the engine is attached.
class NoopPlaybackFacade implements PlaybackFacade {
  @override
  PlaybackSnapshot get snapshot => PlaybackSnapshot.idle;
  @override
  Stream<PlaybackSnapshot> get snapshots => const Stream.empty();
  @override
  Stream<Duration> get positionStream => const Stream.empty();
  @override
  Future<void> playTracks(List<TrackRow> tracks,
      {int startIndex = 0,
      String? sourceName,
      String? sourceId,
      bool shuffle = false}) async {}
  @override
  Future<void> togglePlayPause() async {}
  @override
  Future<void> play() async {}
  @override
  Future<void> pause() async {}
  @override
  Future<void> seek(Duration position) async {}
  @override
  Future<void> skipNext() async {}
  @override
  Future<void> skipPrevious() async {}
  @override
  void toggleShuffle() {}
  @override
  void cycleRepeat() {}
  @override
  void setRepeat(RepeatKind kind) {}
  @override
  Future<void> addToQueue(TrackRow track) async {}
  @override
  Future<void> playNext(TrackRow track) async {}
  @override
  Future<void> playPreview({
    required String id,
    required String title,
    required Uri uri,
    String? artist,
    String? catalogueArtistId,
    String? album,
    String? imageUrl,
    Duration? duration,
  }) async {}
  @override
  Future<void> playPreviews(
    List<PreviewTrack> tracks, {
    int startIndex = 0,
    String? sourceName,
    String? sourceId,
  }) async {}
  @override
  Future<void> addStreamToQueue(PreviewTrack track) async {}
  @override
  QueueSnapshot get queue => QueueSnapshot.empty;
  @override
  Stream<QueueSnapshot> get queueStream => const Stream.empty();
  @override
  Future<void> jumpToQueueIndex(int index) async {}
  @override
  Future<void> removeFromQueue(int index) async {}
  @override
  Future<void> moveInQueue(int from, int to) async {}
  @override
  Future<void> clearUpNext() async {}
  @override
  Future<void> stopAndClear() async {}
  @override
  SleepTimerStatus get sleepTimer => SleepTimerStatus.off;
  @override
  Stream<SleepTimerStatus> get sleepTimerStream => const Stream.empty();
  @override
  Future<void> setSleepTimer(Duration? duration) async {}
  @override
  Future<void> setSleepAtEndOfTrack(bool enabled) async {}
  @override
  double get speed => 1;
  @override
  Future<void> setSpeed(double speed) async {}
  @override
  Stream<PlaybackNotice> get notices => const Stream.empty();
}
