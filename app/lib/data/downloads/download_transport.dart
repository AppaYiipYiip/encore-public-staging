import 'package:flutter/foundation.dart';

/// What the manager asks the platform to fetch.
@immutable
class TransferRequest {
  const TransferRequest({
    required this.taskId,
    required this.url,
    required this.relativePath,
    this.requiresWifi = true,
  });

  /// Stable id (`enc:<server>:<track>`), also used to cancel.
  final String taskId;
  final Uri url;

  /// Path under the app's private storage (`downloads/1/abc.opus`).
  final String relativePath;
  final bool requiresWifi;
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
  });

  final String taskId;
  final TransferStatus status;

  /// 0..1 while running.
  final double? progress;
  final String? error;

  /// Where the task writes (the platform remembers it across process death),
  /// so a completion that arrives after a restart still knows its file (B21).
  final String? relativePath;
}

/// Platform file transfer (ADR-038). The manager owns *what* to download;
/// this seam owns *how*: background execution, retries, notifications.
abstract interface class DownloadTransport {
  Stream<TransferUpdate> get updates;

  /// Task ids the platform still knows about (running / queued), used after
  /// an app restart to reconcile database state.
  Future<Set<String>> activeTaskIds();

  Future<void> start(TransferRequest request);
  Future<void> cancel(String taskId);

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
  /// not running.
  Future<void> resume();
}
