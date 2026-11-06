import 'dart:convert';

import '../data/sync/sync_state_store.dart';

/// What survives an app restart: the queue, where we were in it, and what
/// the user was playing from.
class PersistedPlayback {
  const PersistedPlayback({
    required this.queue,
    required this.positionMs,
    this.sourceName,
    this.sourceId,
  });

  /// `QueueModel.toJson()`.
  final Map<String, Object?> queue;
  final int positionMs;
  final String? sourceName;
  final String? sourceId;

  Map<String, Object?> toJson() => {
        'queue': queue,
        'positionMs': positionMs,
        'sourceName': sourceName,
        'sourceId': sourceId,
      };

  static PersistedPlayback? fromJson(Object? json) {
    if (json is! Map) return null;
    final queue = json['queue'];
    if (queue is! Map) return null;
    return PersistedPlayback(
      queue: queue.cast<String, Object?>(),
      positionMs: (json['positionMs'] as num?)?.toInt() ?? 0,
      sourceName: json['sourceName'] as String?,
      sourceId: json['sourceId'] as String?,
    );
  }
}

/// Where the song that is current has got to: written often (every couple of
/// seconds while it plays, and at once on a seek or a pause), because the app
/// can be killed at any moment and the person expects to come back to where
/// they were. It is deliberately tiny (an id and a number): the queue snapshot
/// above is the whole queue and is written only when the queue changes.
class PlaybackProgress {
  const PlaybackProgress({required this.itemId, required this.positionMs});

  /// The queue item this position belongs to. A progress whose item is no
  /// longer the current one (the queue was changed since) is ignored.
  final String itemId;
  final int positionMs;

  Map<String, Object?> toJson() => {'id': itemId, 'ms': positionMs};

  static PlaybackProgress? fromJson(Object? json) {
    if (json is! Map) return null;
    final id = json['id'];
    final ms = json['ms'];
    if (id is! String || ms is! num) return null;
    return PlaybackProgress(itemId: id, positionMs: ms.toInt());
  }
}

abstract interface class PlaybackStateStore {
  Future<PersistedPlayback?> load();
  Future<void> save(PersistedPlayback state);
  Future<PlaybackProgress?> loadProgress();
  Future<void> saveProgress(PlaybackProgress progress);

  /// Forgets the queue AND the progress.
  Future<void> clear();
}

/// Stores the snapshot as one small JSON value in `sync_state` (ids only, a
/// few KB even for a 5,000-song queue - the legacy engine wrote full track
/// objects on every change).
class DbPlaybackStateStore implements PlaybackStateStore {
  DbPlaybackStateStore(this._store);

  final SyncStateStore _store;

  static const key = 'playback.state';
  static const progressKey = 'playback.progress';

  @override
  Future<PlaybackProgress?> loadProgress() async {
    final raw = await _store.get(progressKey);
    if (raw == null) return null;
    try {
      return PlaybackProgress.fromJson(jsonDecode(raw));
    } on FormatException {
      return null; // a damaged progress is only a position: the snapshot has one
    }
  }

  @override
  Future<void> saveProgress(PlaybackProgress progress) =>
      _store.set(progressKey, jsonEncode(progress.toJson()));

  @override
  Future<PersistedPlayback?> load() async {
    final raw = await _store.get(key);
    if (raw == null) return null;
    try {
      return PersistedPlayback.fromJson(jsonDecode(raw));
    } on FormatException {
      return null; // corrupt snapshot: start with an empty queue
    }
  }

  @override
  Future<void> save(PersistedPlayback state) =>
      _store.set(key, jsonEncode(state.toJson()));

  @override
  Future<void> clear() async {
    await _store.set(key, null);
    await _store.set(progressKey, null);
  }
}

/// In-memory store for tests.
class MemoryPlaybackStateStore implements PlaybackStateStore {
  PersistedPlayback? value;
  int saves = 0;

  /// The latest progress, and how many times one was written (a test can tell
  /// "the position is saved often" from "the whole queue is rewritten often").
  PlaybackProgress? progress;
  int progressSaves = 0;

  @override
  Future<PersistedPlayback?> load() async => value;

  @override
  Future<void> save(PersistedPlayback state) async {
    value = state;
    saves++;
  }

  @override
  Future<PlaybackProgress?> loadProgress() async => progress;

  @override
  Future<void> saveProgress(PlaybackProgress p) async {
    progress = p;
    progressSaves++;
  }

  @override
  Future<void> clear() async {
    value = null;
    progress = null;
  }
}
