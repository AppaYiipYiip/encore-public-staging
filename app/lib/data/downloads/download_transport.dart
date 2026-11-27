import 'package:flutter/foundation.dart';

/// What the manager asks the platform to fetch.
@immutable
class TransferRequest {
  const TransferRequest({
    required this.taskId,
    required this.url,
    required this.relativePath,
    this.requiresWifi = true,
    this.qualityId,
  });

  /// Stable id (`enc:<server>:<track>`), also used to cancel.
  final String taskId;
  final Uri url;

  /// Path under the app's private storage (`downloads/1/abc.opus`).
  final String relativePath;
  final bool requiresWifi;

  /// What the file of this transfer is made at (`AudioQuality.id`). The downloader keeps it with the task and hands it back with every update of the
  /// task ([TransferUpdate.qualityId]), also after the process was killed, as it does the path (B21). A completion records what the file IS, not what the
  /// database says the song wants NOW: the person's Stop ends a refresh's intent (the row stops saying what it was asked at) while its transfer can still
  /// finish (N-39, review of PR 119, round 2).
  final String? qualityId;
}

enum TransferStatus { enqueued, running, complete, failed, canceled, paused }

@immutable
class TransferUpdate {
  const TransferUpdate({
    required this.taskId,
    required this.status,
    this.progress,
    this.error,
    this.relativePath,
    this.qualityId,
  });

  final String taskId;
  final TransferStatus status;

  /// 0..1 while running.
  final double? progress;
  final String? error;

  /// Where the task writes (the platform remembers it across process death),
  /// so a completion that arrives after a restart still knows its file (B21).
  final String? relativePath;

  /// What the file of the task is made at, as [TransferRequest.qualityId] asked (the platform keeps it with the task, like the path). `null` for a task
  /// that was handed over without one (a build before this field) and for updates that carry no task data (progress).
  final String? qualityId;
}

/// Platform file transfer (ADR-038). The manager owns *what* to download;
/// this seam owns *how*: background execution, retries, notifications.
abstract interface class DownloadTransport {
  Stream<TransferUpdate> get updates;

  /// Task ids the platform still knows about (running / queued), used after
  /// an app restart to reconcile database state.
  Future<Set<String>> activeTaskIds();

  Future<void> start(TransferRequest request);

  /// Cancels the task. Answers `true` when the downloader had it and the attempt ends with a last word that is still to come (`canceled`, or the
  /// `complete` or `failed` of a transfer that ended in the very moment), and `false` when it knew no such task: then it sent nothing and no word will
  /// come for this cancel (the Stop's memory of late words counts on it, see `DownloadManager.stop`). Read in `BDPlugin.kt`: the downloader sends one
  /// `canceled` for EVERY unfinished work it still holds under the task id, so for an id that was cancelled before (the work is not enqueued as unique
  /// work) it can be more than one word. Since N-45 every attempt has a name of its own, so a cancel of one attempt cannot bring words about another.
  Future<bool> cancel(String taskId);

  /// Absolute path for [relativePath].
  Future<String> absolutePath(String relativePath);

  Future<int?> fileSize(String absolutePath);

  /// The first [count] bytes of the file (to recognise what it is, B23).
  Future<List<int>> readHead(String absolutePath, int count);
  Future<void> deleteFile(String absolutePath);

  /// Replaces [to] with [from] in one step (used to swap in a refreshed
  /// copy); when it cannot, [to] must be left exactly as it was (B22).
  Future<void> rename(String from, String to);

  /// Called once at start-up: replay updates that arrived while the app was
  /// not running (a finished file, a cancel pressed on a notification of an
  /// older build). It completes only after every replayed update has been
  /// handed to [updates]: the manager handles them before it decides what a
  /// row whose task is gone means (N-39).
  Future<void> resume();
}
