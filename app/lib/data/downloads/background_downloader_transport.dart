import 'dart:async';
import 'dart:io';

import 'package:background_downloader/background_downloader.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';

import '../../core/logger.dart';
import 'download_transport.dart';

/// [DownloadTransport] on `background_downloader` (WorkManager on Android): the transfers are handed to the operating system, honour "Wi-Fi only" there,
/// and are carried on by it for the files already handed over.
///
/// **It posts no notification of its own** (docs/33 PB-38, docs/design S-95, P2-29): no group card is configured, so none exists. The one card of a
/// download is the app's (`DownloadCardPresenter`): it says both stages, which a card of the phone's stage alone could not.
///
/// **What survives the app being killed is only the files already handed over** (at most `DownloadPolicy.maxInFlight`, four; read in the code of the
/// downloader and of the manager, not run): the manager that feeds the downloader lives in the app's own process, and nothing else starts it (the
/// periodic job syncs and never runs it). The rest waits for the app to be opened again. Board item N-40 ("A download keeps going after you close the
/// app") is the proper fix; until it is built nothing here may say that downloads carry on with the app closed (audit row B-135 is about the sentence that used to be here).
class BackgroundDownloaderTransport implements DownloadTransport {
  BackgroundDownloaderTransport({this.group = 'encore-downloads'}) {
    _sub = FileDownloader().updates.listen(_forward);
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
