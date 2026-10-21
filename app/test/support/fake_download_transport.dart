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
  }

  @override
  Future<void> cancel(String taskId) async {
    canceled.add(taskId);
    active.remove(taskId);
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
  Future<void> resume() async => resumeCalls++;

  // ------------------------------------------------------------ test control

  TransferRequest requestFor(String trackId) =>
      started.lastWhere((r) => r.taskId.endsWith(':$trackId'));

  void complete(String trackId, {int size = 4096}) {
    final req = requestFor(trackId);
    files['/app/${req.relativePath}'] = size;
    active.remove(req.taskId);
    _updates.add(TransferUpdate(
      taskId: req.taskId,
      status: TransferStatus.complete,
      progress: 1,
      relativePath: req.relativePath,
    ));
  }

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
