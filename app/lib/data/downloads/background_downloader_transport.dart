import 'dart:async';
import 'dart:io';

import 'package:background_downloader/background_downloader.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';

import '../../core/logger.dart';
import 'download_transport.dart';

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
      complete: const TaskNotification(
        'Downloads finished',
        'Your music is ready offline',
      ),
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

  bool _askedForNotifications = false;

  /// Android 13+ shows download progress only with the notification
  /// permission; ask once, in context (the user just pinned something).
  Future<void> _ensureNotificationPermission() async {
    if (_askedForNotifications) return;
    _askedForNotifications = true;
    try {
      final permissions = FileDownloader().permissions;
      final status = await permissions.status(PermissionType.notifications);
      if (status != PermissionStatus.granted) {
        await permissions.request(PermissionType.notifications);
      }
    } on Object catch (error) {
      Log.debug('downloads', 'notification permission check failed: $error');
    }
  }

  @override
  Future<void> start(TransferRequest request) async {
    await _ensureNotificationPermission();
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
