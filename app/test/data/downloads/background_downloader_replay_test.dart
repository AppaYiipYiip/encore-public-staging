import 'dart:convert';
import 'dart:io';

import 'package:background_downloader/background_downloader.dart';
import 'package:drift/drift.dart' show Value;
import 'package:drift/native.dart';
import 'package:encore/core/clock.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/downloads/background_downloader_transport.dart';
import 'package:encore/data/downloads/download_manager.dart';
import 'package:encore/data/downloads/download_planner.dart';
import 'package:encore/data/downloads/download_transport.dart';
import 'package:encore/data/repos/downloads_repository.dart';
import 'package:encore/domain/audio_quality.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_disk_space.dart';
import '../../support/fake_download_transport.dart';

/// The downloader's own words, kept while the app was not running, as the plugin hands them over.
const _group = 'encore-downloads';
const _channel = MethodChannel('com.bbflight.background_downloader');

/// A storage that keeps nothing on disk (the plugin's own keeps its records in files).
class _MemoryStorage implements PersistentStorage {
  final records = <String, TaskRecord>{};

  /// Makes reading the records fail, as a damaged database of the downloader would.
  bool failReading = false;

  @override
  Future<void> storeTaskRecord(TaskRecord record) async =>
      records[record.taskId] = record;
  @override
  Future<TaskRecord?> retrieveTaskRecord(String taskId) async =>
      records[taskId];
  @override
  Future<List<TaskRecord>> retrieveAllTaskRecords() async {
    if (failReading) throw StateError('the records cannot be read');
    return records.values.toList();
  }

  @override
  Future<void> removeTaskRecord(String? taskId) async =>
      taskId == null ? records.clear() : records.remove(taskId);
  @override
  Future<void> storePausedTask(Task task) async {}
  @override
  Future<Task?> retrievePausedTask(String taskId) async => null;
  @override
  Future<List<Task>> retrieveAllPausedTasks() async => const [];
  @override
  Future<void> removePausedTask(String? taskId) async {}
  @override
  Future<void> storeResumeData(ResumeData resumeData) async {}
  @override
  Future<ResumeData?> retrieveResumeData(String taskId) async => null;
  @override
  Future<List<ResumeData>> retrieveAllResumeData() async => const [];
  @override
  Future<void> removeResumeData(String? taskId) async {}
  @override
  (String, int) get currentDatabaseVersion => ('memory', 1);
  @override
  Future<(String, int)> get storedDatabaseVersion async => ('memory', 1);
  @override
  Future<void> initialize() async {}
}

DownloadTask _task(int serverId, String trackId) => DownloadTask(
      taskId: 'enc:$serverId:$trackId',
      url: 'https://srv/get?id=$trackId',
      filename: '$trackId.opus',
      directory: 'downloads/$serverId',
      baseDirectory: BaseDirectory.applicationSupport,
      group: _group,
      updates: Updates.status,
    );

Future<Uri> _url(
  String id, {
  AudioQuality quality = AudioQuality.original,
  String? sourceSuffix,
  int? sourceBitRate,
}) async =>
    Uri.parse('https://srv/get?id=$id&q=${quality.id}');

/// N-39: what the manager relies on when the app starts, run on the plugin's REAL Dart code (background_downloader 9.6.4) with only the native side
/// faked (the method channels the plugin talks to, answered by the test after one timer turn: a real answer is never faster, it crosses from the
/// native side through the event loop).
///
/// What is proved here: `resume()` of the transport returns only after every update the downloader kept while the app was not running has been handed
/// to the transport's `updates` (the contract the manager's start relies on: it handles those updates before it puts the rows whose task is gone back
/// in the queue). Run in a throwaway copy with the code mutated: `resume()` that does not wait for the plugin (three tests red); the two steps of
/// `resume()` under one `try` again, as before (only the failing-read test red: the updates the downloader kept were skipped); the one turn of the
/// event loop taken out of `resume()` (only the contract test in the schedule where the plugin's last answer comes at once, red). That last result is
/// the honest one: in 9.6.4 the plugin hands the status updates on through two stream controllers (a microtask each) and then makes one more round
/// trip to the native side (the progress updates), which already gives the event loop its turn, so awaiting the plugin is enough today and the turn in
/// `resume()` is a second layer for a plugin that would not. It is the guard of a plugin upgrade: the order is a property of the plugin's code.
///
/// What is NOT proved here: the native side (Kotlin: what it stores while the app is dead, and what `popStatusUpdates` answers), the real timing of the
/// platform channel, WorkManager, a notification of an older build. Those are read in the plugin's sources and are the walk row of docs/33 PB-F22.
/// The last two tests show the plugin's replay reaching a real manager (a cancel kept while the app was closed ends as a failed song and nothing is
/// started) and the harness seeing a start (the control); they do not decide the order: the cancel file's tests do (`download_manager_cancel_test.dart`:
/// without the manager's wait for the replay they are red, these are not, because the real channel's round trip of `allTasks` gives the queue time).
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  final calls = <String>[]; // every call the plugin makes to the native side
  final storage = _MemoryStorage();
  late Directory appDir;
  var stored =
      <String, String>{}; // what the native side kept: taskId -> update json
  var running = <Task>[]; // what the native side still runs

  /// The adversarial schedule: the answer to the plugin's LAST pop (the progress updates, asked after the status updates were replayed) comes at once.
  /// In 9.6.4 that pop is a real round trip of its own and gives the event loop a turn for free; a plugin that asked in another order, or answered
  /// that one from a cache, would not, and then only the turn in `resume()` keeps the replay ahead of the manager's start.
  var lastPopAtOnce = false;
  late BackgroundDownloaderTransport transport;
  late AppDatabase db;
  late FakeClock clock;
  late DownloadsRepository repo;
  late int serverId;

  setUpAll(() async {
    appDir = Directory.systemTemp.createTempSync('n39-replay-');
    final messenger =
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(_channel, (call) async {
      calls.add(call.method);
      switch (call.method) {
        case 'popStatusUpdates':
        case 'popResumeData':
        case 'popProgressUpdates':
          // A real answer crosses from the native side through the event loop, never within the microtasks of the call: it takes at least one timer
          // turn. A fake that answered in microtasks would hide a `resume()` that does not wait for the plugin.
          if (!(lastPopAtOnce && call.method == 'popProgressUpdates')) {
            await Future<void>.delayed(const Duration(milliseconds: 5));
          }
          if (call.method != 'popStatusUpdates') return '{}';
          final answer = stored;
          stored = {};
          return jsonEncode(answer);
        case 'allTasks':
          return [for (final t in running) jsonEncode(t.toJson())];
        case 'enqueue':
          return true;
        default:
          return null;
      }
    });
    messenger.setMockMethodCallHandler(
        const MethodChannel('plugins.flutter.io/path_provider'),
        (call) async => appDir.path);
    messenger.setMockMethodCallHandler(
        const MethodChannel('dev.fluttercommunity.plus/connectivity'),
        (call) async => ['wifi']);
    messenger.setMockMessageHandler(
        'dev.fluttercommunity.plus/connectivity_status',
        (message) async => null);

    // The plugin picks its implementation from the platform at the first call.
    debugDefaultTargetPlatformOverride = TargetPlatform.android;
    FileDownloader(persistentStorage: storage);
    debugDefaultTargetPlatformOverride = null;
    await FileDownloader().ready;
    transport = BackgroundDownloaderTransport();
  });

  setUp(() async {
    calls.clear();
    storage.records.clear();
    storage.failReading = false;
    stored = {};
    running = [];
    lastPopAtOnce = false;
    FileDownloader().downloaderForTesting.retrievedLocallyStoredData = false;
    db = AppDatabase(NativeDatabase.memory());
    clock = FakeClock(DateTime.utc(2026, 11, 17, 6));
    serverId = await db.into(db.servers).insert(ServersCompanion.insert(
        name: 'T', username: 'u', endpointsJson: '[]', createdAtMs: 0));
    for (var i = 1; i <= 4; i++) {
      await db.into(db.tracks).insert(TracksCompanion.insert(
            serverId: serverId,
            id: 't$i',
            title: 'Song $i',
            albumId: const Value('al1'),
            suffix: const Value('flac'),
            bitRate: const Value(900),
            audioKey: Value('key$i'),
          ));
    }
    repo = DownloadsRepository(db, serverId, clock: clock);
  });

  tearDown(() async => db.close());
  tearDownAll(() => appDir.deleteSync(recursive: true));

  for (final atOnce in [false, true]) {
    final schedule = atOnce ? "at once" : "after a timer turn";
    test(
        "N-39: the contract of resume(): when it returns, every update the downloader kept has already been handed to the transport's updates (the plugin's last step answers $schedule)",
        () async {
      lastPopAtOnce = atOnce;
      stored = {
        for (final id in ['t1', 't2'])
          'enc:$serverId:$id': jsonEncode(
              TaskStatusUpdate(_task(serverId, id), TaskStatus.canceled)
                  .toJson()),
        'enc:$serverId:t3': jsonEncode(TaskStatusUpdate(_task(serverId, 't3'),
                TaskStatus.failed, TaskException('HTTP 500'))
            .toJson()),
      };
      final seen = <TransferUpdate>[];
      final sub = transport.updates.listen(seen.add);

      await transport.resume();

      expect(
        [for (final u in seen) (u.taskId.split(':').last, u.status)],
        [
          ('t1', TransferStatus.canceled),
          ('t2', TransferStatus.canceled),
          ('t3', TransferStatus.failed),
        ],
        reason:
            'resume() returned while replayed updates were still on their way',
      );
      expect(seen.first.relativePath, 'downloads/$serverId/t1.opus',
          reason: 'a replayed update carries the path of its own task');
      await sub.cancel();
    });
  }

  test(
      "N-39: when the downloader's records cannot be read, the updates it kept still reach the manager before resume() returns",
      () async {
    storage.failReading = true;
    stored = {
      'enc:$serverId:t1': jsonEncode(
          TaskStatusUpdate(_task(serverId, 't1'), TaskStatus.canceled)
              .toJson()),
    };
    final seen = <TransferUpdate>[];
    final sub = transport.updates.listen(seen.add);

    await transport.resume();

    expect(
      [for (final u in seen) (u.taskId.split(':').last, u.status)],
      [('t1', TransferStatus.canceled)],
      reason:
          'one failing step skipped the replay, and the next start put the cancelled song back in the queue',
    );
    await sub.cancel();
  });

  // The process that ended had handed four songs to the downloader; a new process starts a manager on the real transport.
  Future<DownloadManager> newProcess() async {
    final before = FakeDownloadTransport();
    final first = DownloadManager(
      db: db,
      serverId: serverId,
      repository: repo,
      transport: before,
      clock: clock,
      policy: () => const DownloadPolicy(),
      urlBuilder: _url,
      diskSpace: FakeDiskSpace(100 * 1024 * 1024 * 1024),
    );
    await first.start();
    await repo.pin(PinTargetType.album, 'al1', quality: AudioQuality.high);
    await first.reconcile();
    expect(before.started.length, 4);
    await first.dispose();

    final manager = DownloadManager(
      db: db,
      serverId: serverId,
      repository: repo,
      transport: transport,
      clock: clock,
      policy: () => const DownloadPolicy(),
      urlBuilder: _url,
      diskSpace: FakeDiskSpace(100 * 1024 * 1024 * 1024),
    );
    await manager.start();
    await manager.reconcile();
    await manager.settled();
    return manager;
  }

  test(
      "N-39: on the plugin's real code, a cancel kept while the app was closed ends the song as one that did not come, and nothing is started again",
      () async {
    // While the app was closed: Cancel was pressed on the card of an older build for t1 and t2; t3 and t4 still run.
    stored = {
      for (final id in ['t1', 't2'])
        'enc:$serverId:$id': jsonEncode(
            TaskStatusUpdate(_task(serverId, id), TaskStatus.canceled)
                .toJson()),
    };
    running = [_task(serverId, 't3'), _task(serverId, 't4')];

    final manager = await newProcess();

    expect(calls, contains('popStatusUpdates'));
    expect(calls, isNot(contains('enqueue')),
        reason: 'the next start put the cancelled songs back in the queue');
    for (final id in ['t1', 't2']) {
      final r = (await repo.rowsFor([id])).single;
      expect(r.state, DownloadState.failed, reason: id);
      expect(r.lastError, kDownloadStoppedReason, reason: id);
    }
    for (final id in ['t3', 't4']) {
      expect((await repo.rowsFor([id])).single.state, DownloadState.downloading,
          reason: id);
    }
    await manager.dispose();
  });

  test(
      "N-39: the control: with nothing kept by the downloader, the two rows whose task is gone are put back in the queue and handed to it again (the harness sees a start)",
      () async {
    running = [_task(serverId, 't3'), _task(serverId, 't4')];

    final manager = await newProcess();

    expect(calls.where((c) => c == 'enqueue').length, 2);
    for (final id in ['t1', 't2']) {
      expect((await repo.rowsFor([id])).single.state, DownloadState.downloading,
          reason: id);
    }
    await manager.dispose();
  });
}
