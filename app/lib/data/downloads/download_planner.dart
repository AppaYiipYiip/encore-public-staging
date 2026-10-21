import 'dart:math';

import '../db/app_database.dart';

/// What a pin asks for one track.
class DesiredDownload {
  const DesiredDownload({
    required this.trackId,
    required this.quality,
    this.audioKey = '',
  });

  final String trackId;

  /// `AudioQuality.id`.
  final String quality;

  /// Current `Tracks.audioKey` (empty when unknown).
  final String audioKey;
}

/// The set of changes needed to make local files match what is pinned.
class DownloadPlan {
  const DownloadPlan({
    this.toQueue = const [],
    this.toRefresh = const [],
    this.toOrphan = const [],
    this.toRescue = const [],
    this.toDelete = const [],
  });

  /// Missing (or failed and due for retry) -> start a download.
  final List<String> toQueue;

  /// Downloaded copy is stale (source audio changed on the server) ->
  /// download again and replace.
  final List<String> toRefresh;

  /// No pin wants it any more -> start the grace period.
  final List<String> toOrphan;

  /// Wanted again before the grace period ended -> keep.
  final List<String> toRescue;

  /// Grace over (or user removed the pin) -> delete file and row.
  final List<String> toDelete;

  bool get isEmpty =>
      toQueue.isEmpty &&
      toRefresh.isEmpty &&
      toOrphan.isEmpty &&
      toRescue.isEmpty &&
      toDelete.isEmpty;

  @override
  String toString() => 'DownloadPlan(queue: ${toQueue.length}, '
      'refresh: ${toRefresh.length}, orphan: ${toOrphan.length}, '
      'rescue: ${toRescue.length}, delete: ${toDelete.length})';
}

/// Download state values stored in `Downloads.state`.
abstract final class DownloadState {
  static const queued = 0;
  static const downloading = 1;
  static const done = 2;
  static const failed = 3;
}

/// Pure planning step of the download reconciler (docs/02-architecture.md
/// section 5.3). No I/O, no clock: everything arrives as arguments so every
/// branch is unit-testable.
///
/// [graceMs] is how long a track that lost its pin stays on disk. Pass `0`
/// for an explicit user action ("Remove download"): the user expects the
/// space back immediately. Server-side changes (a smart playlist was
/// regenerated) use a grace period so churn does not delete and re-download
/// the same files.
DownloadPlan planDownloads({
  required Map<String, DesiredDownload> desired,
  required Map<String, DownloadRow> existing,
  required int nowMs,
  int graceMs = 24 * 60 * 60 * 1000,
  int retryBaseMs = 5 * 60 * 1000,
  int retryMaxMs = 6 * 60 * 60 * 1000,
}) {
  final toQueue = <String>[];
  final toRefresh = <String>[];
  final toOrphan = <String>[];
  final toRescue = <String>[];
  final toDelete = <String>[];

  for (final entry in desired.entries) {
    final id = entry.key;
    final want = entry.value;
    final row = existing[id];
    if (row == null) {
      toQueue.add(id);
      continue;
    }
    if (row.orphanedAtMs != null) toRescue.add(id);

    switch (row.state) {
      case DownloadState.done:
        final changed = row.stale ||
            (want.audioKey.isNotEmpty &&
                row.sourceAudioKey.isNotEmpty &&
                row.sourceAudioKey != want.audioKey);
        if (changed) toRefresh.add(id);
      case DownloadState.failed:
        // Exponential back-off: 5 min, 10, 20, ... capped at 6 h.
        final wait = min(
            retryMaxMs, retryBaseMs * pow(2, min(row.attempts, 10)).toInt());
        if (nowMs - row.updatedAtMs >= wait) toQueue.add(id);
      case DownloadState.queued:
      case DownloadState.downloading:
        break;
    }
  }

  for (final entry in existing.entries) {
    if (desired.containsKey(entry.key)) continue;
    final row = entry.value;
    final orphanedAt = row.orphanedAtMs;
    if (graceMs <= 0) {
      toDelete.add(entry.key);
    } else if (orphanedAt == null) {
      toOrphan.add(entry.key);
    } else if (nowMs - orphanedAt >= graceMs) {
      toDelete.add(entry.key);
    }
  }

  return DownloadPlan(
    toQueue: toQueue,
    toRefresh: toRefresh,
    toOrphan: toOrphan,
    toRescue: toRescue,
    toDelete: toDelete,
  );
}
