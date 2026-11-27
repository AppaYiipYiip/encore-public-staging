import 'dart:math';

import '../../domain/audio_quality.dart';
import '../db/app_database.dart';
import '../sync/fingerprint.dart';

/// What a pin asks for one track.
class DesiredDownload {
  const DesiredDownload({
    required this.trackId,
    required this.quality,
    this.audioKey = '',
    this.legacyAudioKey = '',
    this.held = false,
  });

  final String trackId;

  /// `AudioQuality.id`.
  final String quality;

  /// Current `Tracks.audioKey` (empty when unknown).
  final String audioKey;

  /// What the key of this track's file would be by the app's OLD formula (it contains the file's size), from the same columns: what a copy downloaded before the server
  /// served keys is checked against, so that it is not downloaded again because the formula changed (N-38, [downloadAudioKeyVerdict]).
  final String legacyAudioKey;

  /// Every pin that wants this song is stopped by the person (N-39): the song stays desired, so it is never orphaned and its file is never deleted, but
  /// it is not queued, refreshed or tried again until a pin that wants it goes on.
  final bool held;
}

/// The set of changes needed to make local files match what is pinned.
class DownloadPlan {
  const DownloadPlan({
    this.toQueue = const [],
    this.toRefresh = const [],
    this.toOrphan = const [],
    this.toRescue = const [],
    this.toDelete = const [],
    this.toAdopt = const {},
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

  /// A downloaded copy that is current and carries the old kind of key while the server now serves a key of the audio: the copy stays, its row takes the new key
  /// (track id -> the key). Nothing is fetched (N-38).
  final Map<String, String> toAdopt;

  bool get isEmpty =>
      toQueue.isEmpty &&
      toRefresh.isEmpty &&
      toOrphan.isEmpty &&
      toRescue.isEmpty &&
      toDelete.isEmpty &&
      toAdopt.isEmpty;

  @override
  String toString() => 'DownloadPlan(queue: ${toQueue.length}, '
      'refresh: ${toRefresh.length}, orphan: ${toOrphan.length}, '
      'rescue: ${toRescue.length}, delete: ${toDelete.length}, '
      'adopt: ${toAdopt.length})';
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
///
/// [upgradeCapped] (P4-24): the phone is on Wi-Fi and Data saver is not in force, so a copy that Data saver made smaller than the person's own
/// choice is made again at that choice (in [DownloadPlan.toRefresh], which keeps the old copy until the new one is complete). It is
/// deliberately narrow: only a copy that is exactly what the cap makes of the wanted quality is touched, so copies that differ for any other
/// reason (a second pin asked for more) stay as they are today. A refresh that failed waits the back-off of a failed download.
DownloadPlan planDownloads({
  required Map<String, DesiredDownload> desired,
  required Map<String, DownloadRow> existing,
  required int nowMs,
  int graceMs = 24 * 60 * 60 * 1000,
  int retryBaseMs = 5 * 60 * 1000,
  int retryMaxMs = 6 * 60 * 60 * 1000,
  bool upgradeCapped = false,
}) {
  final toQueue = <String>[];
  final toRefresh = <String>[];
  final toOrphan = <String>[];
  final toRescue = <String>[];
  final toDelete = <String>[];
  final toAdopt = <String, String>{};

  // Exponential back-off: 5 min, 10, 20, ... capped at 6 h.
  int backoffMs(int attempts) =>
      min(retryMaxMs, retryBaseMs * pow(2, min(attempts, 10)).toInt());

  for (final entry in desired.entries) {
    final id = entry.key;
    final want = entry.value;
    final row = existing[id];
    if (row == null) {
      // A song added to a stopped download waits for Resume: no row is made for it.
      if (!want.held) toQueue.add(id);
      continue;
    }
    if (row.orphanedAtMs != null) toRescue.add(id);

    switch (row.state) {
      case DownloadState.done:
        final verdict = downloadAudioKeyVerdict(
          stored: row.sourceAudioKey,
          live: want.audioKey,
          liveLegacy: want.legacyAudioKey,
        );
        final changed = row.stale || verdict == AudioKeyVerdict.changed;
        // The copy is the file it was when it was downloaded: keep it and give its row the key the server serves now (no fetch, no state change).
        if (!changed && verdict == AudioKeyVerdict.adopt) {
          toAdopt[id] = want.audioKey;
        }
        // A refresh that did not arrive leaves the copy playable and counts an attempt: the next try waits the back-off of a failed download,
        // so a refresh that keeps failing is not started again at every network change, sync or pin edit.
        final mayTry = row.attempts == 0 ||
            nowMs - row.updatedAtMs >= backoffMs(row.attempts);
        final upgrade = upgradeCapped &&
            wasLoweredByDataSaver(madeAt: row.quality, wanted: want.quality);
        if ((changed || upgrade) && mayTry && !want.held) toRefresh.add(id);
      case DownloadState.failed:
        // A held song that did not come stays failed and counted (S-16: "7 of 10 on this phone · 3 songs did not come"); Resume lets the back-off
        // do its work again.
        if (!want.held && nowMs - row.updatedAtMs >= backoffMs(row.attempts)) {
          toQueue.add(id);
        }
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
    toAdopt: toAdopt,
  );
}

/// Whether a copy made at [madeAt] is what Data saver makes of [wanted] and [wanted] is a quality the cap lowers: the copy was (as far as the
/// row can tell) made under the cap and is now worth making again at the quality the person asked for.
bool wasLoweredByDataSaver({required String madeAt, required String wanted}) {
  final want = AudioQuality.byId(wanted);
  return want.isLoweredByDataSaver &&
      AudioQuality.byId(madeAt) == want.cappedForDataSaver();
}
