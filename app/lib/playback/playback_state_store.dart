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

abstract interface class PlaybackStateStore {
  Future<PersistedPlayback?> load();
  Future<void> save(PersistedPlayback state);
  Future<void> clear();
}

/// Stores the snapshot as one small JSON value in `sync_state` (ids only, a
/// few KB even for a 5,000-song queue - the legacy engine wrote full track
/// objects on every change).
class DbPlaybackStateStore implements PlaybackStateStore {
  DbPlaybackStateStore(this._store);

  final SyncStateStore _store;

  static const key = 'playback.state';

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
  Future<void> clear() => _store.set(key, null);
}

/// In-memory store for tests.
class MemoryPlaybackStateStore implements PlaybackStateStore {
  PersistedPlayback? value;
  int saves = 0;

  @override
  Future<PersistedPlayback?> load() async => value;

  @override
  Future<void> save(PersistedPlayback state) async {
    value = state;
    saves++;
  }

  @override
  Future<void> clear() async => value = null;
}
