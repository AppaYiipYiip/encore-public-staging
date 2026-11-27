import 'dart:async';

import 'package:encore/data/downloads/download_transport.dart';

/// In-memory transport: tests drive completion/failure by hand.
class FakeDownloadTransport implements DownloadTransport {
  final List<TransferRequest> started = [];
  final List<String> canceled = [];
  final List<String> deleted = [];
  final List<(String, String)> renamed = [];
  final Map<String, int> files = {};

  /// First bytes per file; by default a plausible header for the extension.
  final Map<String, List<int>> heads = {};

  /// Makes [rename] fail without touching either file.
  bool failRename = false;
  Set<String> active = {};
  int resumeCalls = 0;

  /// The most tasks that were ever running at once (what a limit on transfers is held to).
  int maxActive = 0;

  final StreamController<TransferUpdate> _updates =
      StreamController<TransferUpdate>.broadcast(sync: true);

  @override
  Stream<TransferUpdate> get updates => _updates.stream;

  @override
  Future<Set<String>> activeTaskIds() async => Set.of(active);

  @override
  Future<void> start(TransferRequest request) async {
    started.add(request);
    active.add(request.taskId);
    if (active.length > maxActive) maxActive = active.length;
  }

  /// Off by default (the older tests never saw an acknowledgement). On, [cancel] answers the way the real downloader does: `cancelTaskWithId` sends one
  /// `canceled` update for a task it still knows, before it returns, and none for a task it does not know (a finished one, one never started)
  /// (background_downloader 9.6.4, BDPlugin.kt `cancelActiveTaskWithId`).
  bool acknowledgeCancels = false;

  @override
  Future<bool> cancel(String taskId) async {
    canceled.add(taskId);
    final known = active.remove(taskId);
    if (acknowledgeCancels && known) {
      _updates.add(TransferUpdate(
        taskId: taskId,
        status: TransferStatus.canceled,
      ));
    }
    return known;
  }

  @override
  Future<String> absolutePath(String relativePath) async =>
      '/app/$relativePath';

  @override
  Future<int?> fileSize(String absolutePath) async => files[absolutePath];

  @override
  Future<List<int>> readHead(String absolutePath, int count) async {
    if (!files.containsKey(absolutePath)) return const [];
    return heads[absolutePath] ?? _plausibleHead(absolutePath);
  }

  static List<int> _plausibleHead(String path) {
    final name =
        path.endsWith('.new') ? path.substring(0, path.length - 4) : path;
    final ext = name.contains('.') ? name.split('.').last : '';
    return switch (ext) {
      'flac' => 'fLaC'.codeUnits,
      'opus' || 'ogg' => 'OggS'.codeUnits,
      'mp3' => 'ID3'.codeUnits,
      'm4a' => [0, 0, 0, 0x20, ...'ftyp'.codeUnits],
      _ => const [0x41, 0x42],
    };
  }

  @override
  Future<void> deleteFile(String absolutePath) async {
    deleted.add(absolutePath);
    files.remove(absolutePath);
  }

  @override
  Future<void> rename(String from, String to) async {
    if (failRename) throw StateError('rename failed');
    renamed.add((from, to));
    final size = files.remove(from);
    if (size != null) files[to] = size;
  }

  @override
  Future<void> resume() async {
    resumeCalls++;
    // The downloader hands over what it kept while the app was not running and then returns, as the real one does: the updates are on their way (one
    // microtask each), not yet handled, when the caller goes on.
    for (final update in replayOnResume) {
      scheduleMicrotask(() => _updates.add(update));
    }
  }

  /// What the downloader kept for the app while it was not running (status updates it could not deliver): delivered by [resume].
  final List<TransferUpdate> replayOnResume = [];

  // ------------------------------------------------------------ test control

  TransferRequest requestFor(String trackId) =>
      started.lastWhere((r) => r.taskId.endsWith(':$trackId'));

  /// The task names this transport was asked to start for a song, oldest first (N-45: every attempt has a name of its own).
  List<String> attemptsOf(String trackId) => [
        for (final r in started)
          if (r.taskId.endsWith(':$trackId')) r.taskId
      ];

  /// The name of the FIRST attempt of a song: what a late word of an attempt that was stopped, switched off or replaced is about.
  String firstTaskOf(String trackId) => attemptsOf(trackId).first;

  /// The name of the newest attempt of a song: what the transfer that runs now is called.
  String latestTaskOf(String trackId) => attemptsOf(trackId).last;

  /// The name of the ONE attempt a song has had. It throws when there were several: a test that has Stopped and Resumed (or switched off and on) must
  /// say WHICH attempt it means, or a word of an earlier attempt would silently become a word of the one that runs and the test would change meaning.
  String taskOf(String trackId) {
    final all = attemptsOf(trackId);
    if (all.length != 1) {
      throw StateError(
          '$trackId has had ${all.length} attempts: say firstTaskOf or latestTaskOf');
    }
    return all.single;
  }

  void complete(String trackId, {int size = 4096}) {
    final req = requestFor(trackId);
    files['/app/${req.relativePath}'] = size;
    active.remove(req.taskId);
    _updates.add(TransferUpdate(
      taskId: req.taskId,
      status: TransferStatus.complete,
      progress: 1,
      relativePath: req.relativePath,
      // The downloader hands the task's own data back with its last word.
      qualityId: req.qualityId,
    ));
  }

  /// The task of [trackId] is cancelled by something that is not the manager (the Cancel button of the downloader's card of an older build, a reset of
  /// the downloader): the manager never asked, and learns it only from this update.
  void cancelFromOutside(String trackId) {
    final req = requestFor(trackId);
    active.remove(req.taskId);
    _updates.add(TransferUpdate(
      taskId: req.taskId,
      status: TransferStatus.canceled,
    ));
  }

  /// Any update the downloader could send, also for a task this fake never started.
  void send(TransferUpdate update) => _updates.add(update);

  void fail(String trackId, [String error = 'HTTP 500']) {
    final req = requestFor(trackId);
    active.remove(req.taskId);
    _updates.add(TransferUpdate(
      taskId: req.taskId,
      status: TransferStatus.failed,
      error: error,
    ));
  }
}
