import 'dart:async';
import 'dart:io';

import 'package:background_downloader/background_downloader.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';

import '../../core/logger.dart';
import 'download_transport.dart';

/// What the notification says when the phone's queue of files has emptied. It must be true at ANY such moment, and "Downloads finished" is not: the queue
/// is fed a few files at a time and the server's stage overlaps the phone's, so it can empty while the server still holds most of a playlist (docs/33
/// PB-38). The notification covers only the phone's stage; how the whole download is going is shown in the app (docs/design S-16).
const TaskNotification kDownloadsQueueEmptiedNotification = TaskNotification(
  'Some of your music is ready offline',
  'Open Encore to see how your downloads are going',
);

/// [DownloadTransport] on `background_downloader` (WorkManager on Android):
/// transfers continue with the app in the background, survive process death,
/// honour "Wi-Fi only" at the OS level and show one grouped notification.
class BackgroundDownloaderTransport implements DownloadTransport {
  BackgroundDownloaderTransport({this.group = 'encore-downloads'}) {
    final downloader = FileDownloader();
    downloader.configureNotificationForGroup(
      group,
      // The queue is fed a few files at a time (gentle on the server), so
      // "of N" would only ever show what is enqueued right now, not what
      // the user pinned: count what is done instead.
      running: const TaskNotification(
        'Downloading music',
        '{numFinished} songs downloaded so far',
      ),
      complete: kDownloadsQueueEmptiedNotification,
      error: const TaskNotification(
        'Some downloads did not finish',
        '{numFailed} songs will be retried',
      ),
      progressBar: false,
      groupNotificationId: 'encore-downloads',
    );
    _sub = downloader.updates.listen(_forward);
  }

  final String group;
  late final StreamSubscription<TaskUpdate> _sub;
  final StreamController<TransferUpdate> _updates =
      StreamController<TransferUpdate>.broadcast();
  Directory? _root;

  @override
  Stream<TransferUpdate> get updates => _updates.stream;

  void _forward(TaskUpdate update) {
    if (update.task.group != group) return;
    switch (update) {
      case TaskStatusUpdate(:final status, :final exception, :final task):
        _updates.add(TransferUpdate(
          taskId: task.taskId,
          status: switch (status) {
            TaskStatus.enqueued => TransferStatus.enqueued,
            TaskStatus.running => TransferStatus.running,
            TaskStatus.complete => TransferStatus.complete,
            TaskStatus.notFound => TransferStatus.failed,
            TaskStatus.failed => TransferStatus.failed,
            TaskStatus.canceled => TransferStatus.canceled,
            TaskStatus.waitingToRetry => TransferStatus.enqueued,
            TaskStatus.paused => TransferStatus.paused,
          },
          error: status == TaskStatus.notFound
              ? 'The server no longer has this file'
              : exception?.description,
          relativePath: p.posix.join(task.directory, task.filename),
        ));
      case TaskProgressUpdate(:final progress, :final task):
        _updates.add(TransferUpdate(
          taskId: task.taskId,
          status: TransferStatus.running,
          progress: progress < 0 ? null : progress,
        ));
    }
  }

  Future<Directory> _appRoot() async =>
      _root ??= await getApplicationSupportDirectory();

  @override
  Future<void> resume() async {
    try {
      await FileDownloader().trackTasks();
      await FileDownloader().resumeFromBackground();
    } on Object catch (error) {
      Log.warn('downloads', 'resume from background failed', error);
    }
  }

  @override
  Future<Set<String>> activeTaskIds() async =>
      (await FileDownloader().allTaskIds(group: group)).toSet();

  // No notification permission is asked for here (ADR-R44, AUDIT F29): nothing reaches the phone's notification area unless the person
  // switched it on in Settings > Notifications. A download runs without the permission; its progress notification shows only when the
  // person has allowed notifications for Encore.
  @override
  Future<void> start(TransferRequest request) async {
    final relativeDir = p.dirname(request.relativePath);
    final name = p.basename(request.relativePath);
    final task = DownloadTask(
      taskId: request.taskId,
      url: request.url.toString(),
      filename: name,
      directory: relativeDir,
      baseDirectory: BaseDirectory.applicationSupport,
      group: group,
      updates: Updates.status,
      requiresWiFi: request.requiresWifi,
      retries: 2,
      allowPause: false,
      displayName: name,
    );
    final ok = await FileDownloader().enqueue(task);
    if (!ok) {
      _updates.add(TransferUpdate(
        taskId: request.taskId,
        status: TransferStatus.failed,
        error: 'Could not start the download',
      ));
    }
  }

  @override
  Future<void> cancel(String taskId) async {
    await FileDownloader().cancelTaskWithId(taskId);
  }

  @override
  Future<String> absolutePath(String relativePath) async =>
      p.join((await _appRoot()).path, relativePath);

  @override
  Future<int?> fileSize(String absolutePath) async {
    final file = File(absolutePath);
    return file.existsSync() ? file.lengthSync() : null;
  }

  @override
  Future<List<int>> readHead(String absolutePath, int count) async {
    final file = File(absolutePath);
    if (!file.existsSync()) return const [];
    final handle = file.openSync();
    try {
      return handle.readSync(count);
    } finally {
      handle.closeSync();
    }
  }

  @override
  Future<void> deleteFile(String absolutePath) async {
    final file = File(absolutePath);
    if (file.existsSync()) file.deleteSync();
  }

  @override
  Future<void> rename(String from, String to) async {
    // rename(2) replaces an existing file atomically: the old copy is either
    // still there or already the new one, never missing in between (B22).
    File(from).renameSync(to);
  }

  Future<void> dispose() async {
    await _sub.cancel();
    await _updates.close();
  }
}
