import 'package:drift/drift.dart' show Value;
import 'package:drift/native.dart';
import 'package:encore/core/clock.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/downloads/download_manager.dart';
import 'package:encore/data/downloads/download_planner.dart';
import 'package:encore/data/downloads/download_transport.dart';
import 'package:encore/data/repos/downloads_repository.dart';
import 'package:encore/domain/audio_quality.dart';
import 'package:encore/domain/download_line.dart' show phoneFailureWords;
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_disk_space.dart';
import '../../support/fake_download_transport.dart';

Future<Uri> _url(
  String id, {
  AudioQuality quality = AudioQuality.original,
  String? sourceSuffix,
  int? sourceBitRate,
}) async =>
    Uri.parse('https://srv/get?id=$id&q=${quality.id}');

/// N-39 / audit row B-134: what the manager does when a transfer ends as `canceled`.
///
/// Read in the code (app/lib and background_downloader 9.6.4), then shown here with the REAL manager, the REAL repository and a fake transport:
///  * the manager itself cancels a transfer in one place only, `_delete` (a pin the person removed, or the grace of a song that left a list ran out):
///    the same pass deletes the row, and the downloader answers the cancel with one `canceled` update, which the manager handles after the pass;
///  * a `canceled` the manager did not ask for (the Cancel button of the downloader's card of an older build, a reset of the downloader, an update the
///    downloader kept while the app was dead) used to be forgotten: the row stayed `downloading` for ever with no task behind it, the pin and the one
///    card never ended, the free place stayed empty, and the next START of the app put the row back in the queue at once (the restart the item feared,
///    at the next start and not at the next pump).
/// A person can no longer reach an outside cancel from this app: the card that carried the button is gone (P2-29), apart from the tasks an older build
/// handed over and that are still unfinished after the upgrade. A real Stop that keeps the files is the open part of N-39 (it needs a drawing).
void main() {
  late AppDatabase db;
  late FakeClock clock;
  late DownloadsRepository repo;
  late FakeDownloadTransport transport;
  late DownloadManager manager;
  late int serverId;
  var policy = const DownloadPolicy();

  DownloadManager newManager(FakeDownloadTransport on) => DownloadManager(
        db: db,
        serverId: serverId,
        repository: repo,
        transport: on,
        clock: clock,
        policy: () => policy,
        urlBuilder: _url,
        diskSpace: FakeDiskSpace(100 * 1024 * 1024 * 1024),
      );

  setUp(() async {
    policy = const DownloadPolicy();
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
    transport = FakeDownloadTransport();
    manager = newManager(transport);
    await manager.start();
  });

  tearDown(() async {
    await manager.dispose();
    await db.close();
  });

  Future<DownloadRow> row(String id) async => (await repo.rowsFor([id])).single;
  int startsOf(String id) =>
      transport.started.where((r) => r.taskId.endsWith(':$id')).length;
  Future<PinState> albumState() =>
      repo.watchPinState(PinTargetType.album, 'al1').first;
  String taskOf(String id) => 'enc:$serverId:$id';

  group("a transfer cancelled by something that is not the manager", () {
    test(
        "N-39: it ends as a song that did not come, with a reason, not as a download that never ends",
        () async {
      await repo.pin(PinTargetType.album, 'al1', quality: AudioQuality.high);
      await manager.reconcile();

      transport.cancelFromOutside('t1');
      await manager.settled();

      final r = await row('t1');
      expect(r.state, DownloadState.failed,
          reason: 'it stayed "downloading" with no task behind it');
      expect(r.lastError, kDownloadStoppedReason);
      expect(r.attempts, 1);
      expect(manager.debugInFlight, isNot(contains('t1')));

      for (final id in ['t2', 't3', 't4']) {
        transport.complete(id);
      }
      await manager.settled();
      final s = await albumState();
      expect(s.active, 0,
          reason:
              'the pin and the one card wait for a song that is not coming');
      expect(s.failed, 1);
      expect(s.phase, PinPhase.attention);
    });

    test(
        "N-39: the reason it records reads as the plain sentence of every other song the phone could not take, and no raw text",
        () {
      expect(phoneFailureWords(kDownloadStoppedReason),
          'Could not be saved on this phone.');
    });

    test(
        "N-39: it is started again only when the back-off of a failed song allows, never at once and never in a loop",
        () async {
      await repo.pin(PinTargetType.album, 'al1', quality: AudioQuality.high);
      await manager.reconcile();
      expect(startsOf('t1'), 1);

      transport.cancelFromOutside('t1');
      await manager.settled();
      for (var pass = 0; pass < 5; pass++) {
        await manager.reconcile();
      }
      expect(startsOf('t1'), 1, reason: 'no restart however many passes run');

      clock.advance(const Duration(minutes: 11)); // 5 min * 2^1 = 10 min
      await manager.reconcile();
      expect(startsOf('t1'), 2, reason: 'once, when the back-off is over');
      expect((await row('t1')).state, DownloadState.downloading);

      // Cancelled again: the wait doubles (5 min * 2^2 = 20 min).
      transport.cancelFromOutside('t1');
      await manager.settled();
      clock.advance(const Duration(minutes: 11));
      await manager.reconcile();
      expect(startsOf('t1'), 2, reason: 'the second wait is longer');
      clock.advance(const Duration(minutes: 10));
      await manager.reconcile();
      expect(startsOf('t1'), 3);
    });

    test("N-39: the place it leaves goes to the next song at once", () async {
      policy = const DownloadPolicy(maxInFlight: 2);
      await repo.pin(PinTargetType.album, 'al1', quality: AudioQuality.high);
      await manager.reconcile();
      expect(transport.started.length, 2);
      final first = transport.started.first.taskId.split(':').last;

      transport.cancelFromOutside(first);
      await manager.settled();

      expect(transport.started.length, 3,
          reason: 'the free place stayed empty until some other trigger came');
      expect(transport.started.last.taskId, isNot(endsWith(':$first')));
    });

    test(
        "N-39: a cancel of a refresh leaves the old copy done and playable, and the refresh is tried again later",
        () async {
      await repo.pin(PinTargetType.album, 'al1', quality: AudioQuality.high);
      await manager.reconcile();
      transport.complete('t1', size: 5000);
      await manager.settled();
      final oldPath = (await row('t1')).localPath!;
      await (db.update(db.tracks)..where((t) => t.id.equals('t1')))
          .write(const TracksCompanion(audioKey: Value('key1-NEW')));
      await manager.reconcile();
      expect(transport.requestFor('t1').relativePath, endsWith('.opus.new'));
      expect((await row('t1')).state, DownloadState.downloading);

      transport.cancelFromOutside('t1');
      await manager.settled();

      final r = await row('t1');
      expect(r.state, DownloadState.done,
          reason: 'the copy on the phone is still the song');
      expect(r.localPath, oldPath);
      expect(r.bytes, 5000);
      expect(r.lastError, kDownloadStoppedReason);
      expect(
          transport.deleted, contains('/app/downloads/$serverId/t1.opus.new'),
          reason: 'the half-made new file is not left behind');
      expect(transport.deleted, isNot(contains(oldPath)));

      // Two starts so far: the first download and the refresh that was cancelled.
      expect(startsOf('t1'), 2);
      await manager.reconcile();
      expect(startsOf('t1'), 2, reason: 'the refresh waits its back-off');
      clock.advance(const Duration(minutes: 11));
      await manager.reconcile();
      expect(startsOf('t1'), 3);
    });

    test(
        "N-39: the next start of the app does not put it back in the queue (the restart of the item)",
        () async {
      await repo.pin(PinTargetType.album, 'al1', quality: AudioQuality.high);
      await manager.reconcile();
      transport.cancelFromOutside('t1');
      await manager.settled();
      await manager.dispose(); // the process ends

      // The new process: the downloader remembers no task.
      final next = FakeDownloadTransport();
      final fresh = newManager(next);
      await fresh.start();
      await fresh.reconcile();
      await fresh.settled();

      final restarted = {
        for (final r in next.started) r.taskId.split(':').last,
      };
      expect(restarted, isNot(contains('t1')),
          reason: 'the cancelled song was started again by the next start');
      expect(restarted, containsAll(['t2', 't3', 't4']),
          reason: 'start() still puts back what was in flight when the '
              'process died (the gap of N-40, untouched here)');
      expect((await row('t1')).state, DownloadState.failed);
      await fresh.dispose();
    });

    test(
        "N-39: an update for a song with no row, or whose row is not downloading, changes nothing",
        () async {
      await repo.pin(PinTargetType.album, 'al1', quality: AudioQuality.high);
      await manager.reconcile();
      transport.complete('t1', size: 5000);
      await manager.settled();

      transport.cancelFromOutside('t1'); // t1 is done: a stale word
      transport.send(TransferUpdate(
        taskId: 'enc:$serverId:nobody',
        status: TransferStatus.canceled,
      ));
      transport.send(const TransferUpdate(
        taskId: 'enc:999:t2', // another server's task: not ours
        status: TransferStatus.canceled,
      ));
      await manager.settled();

      final r = await row('t1');
      expect(r.state, DownloadState.done);
      expect(r.lastError, isNull);
      expect(r.attempts, 0);
      expect(await repo.rowsFor(['nobody']), isEmpty);
      expect((await row('t2')).state, DownloadState.downloading);
      expect(manager.debugInFlight, containsAll(['t2', 't3', 't4']));
    });
  });

  group("a cancel the downloader kept while the app was not running", () {
    // The case that reaches a person today: a task an older build handed over, its card's Cancel pressed with the app swiped away. The downloader
    // keeps the `canceled` updates and hands them over at the next start, from `resume()`; they must be handled before the start looks for rows
    // whose task is gone (those go back in the queue).
    test(
        "N-39: a cancel pressed while the app was closed is not undone by the next start",
        () async {
      await repo.pin(PinTargetType.album, 'al1', quality: AudioQuality.high);
      await manager.reconcile();
      await manager.dispose(); // the process ends with four songs in flight

      final next = FakeDownloadTransport()
        ..replayOnResume.addAll([
          for (final id in ['t1', 't2', 't3', 't4'])
            TransferUpdate(taskId: taskOf(id), status: TransferStatus.canceled),
        ]);
      final fresh = newManager(next);
      await fresh.start();
      await fresh.reconcile();
      await fresh.settled();

      expect(next.started, isEmpty,
          reason: 'the next start put the cancelled songs back in the queue');
      for (final id in ['t1', 't2', 't3', 't4']) {
        final r = await row(id);
        expect(r.state, DownloadState.failed, reason: id);
        expect(r.lastError, kDownloadStoppedReason, reason: id);
      }
      expect((await albumState()).phase, PinPhase.attention);
      await fresh.dispose();
    });

    test(
        "N-39: what the replay says about the other songs is kept: one done, one cancelled, two still running",
        () async {
      await repo.pin(PinTargetType.album, 'al1', quality: AudioQuality.high);
      await manager.reconcile();
      final path2 = transport.requestFor('t2').relativePath;
      await manager.dispose();

      final next = FakeDownloadTransport()
        ..files['/app/$path2'] = 4096
        ..active = {taskOf('t3'), taskOf('t4')}
        ..replayOnResume.addAll([
          TransferUpdate(taskId: taskOf('t1'), status: TransferStatus.canceled),
          TransferUpdate(
            taskId: taskOf('t2'),
            status: TransferStatus.complete,
            relativePath: path2,
          ),
        ]);
      final fresh = newManager(next);
      await fresh.start();
      await fresh.reconcile();
      await fresh.settled();

      expect(next.started, isEmpty);
      expect((await row('t1')).state, DownloadState.failed);
      expect((await row('t2')).state, DownloadState.done);
      expect((await row('t3')).state, DownloadState.downloading);
      expect((await row('t4')).state, DownloadState.downloading);
      expect(fresh.debugInFlight, {'t3', 't4'});
      await fresh.dispose();
    });
  });

  group("what the replay at the start must not break", () {
    test(
        "N-39: a replayed song that finished or was cancelled does not start more songs than the limit allows: nothing is pumped until the start has counted what still runs",
        () async {
      for (var i = 5; i <= 8; i++) {
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
      await repo.pin(PinTargetType.album, 'al1', quality: AudioQuality.high);
      await manager.reconcile();
      expect(transport.started.length, 4,
          reason: 't1 to t4 in flight, t5 to t8 queued');
      final path1 = transport.requestFor('t1').relativePath;
      await manager.dispose(); // the process ends

      // While the app was closed: t1 finished, t2 was cancelled, t3 and t4 are still running in the downloader.
      final next = FakeDownloadTransport()
        ..files['/app/$path1'] = 4096
        ..active = {taskOf('t3'), taskOf('t4')}
        ..replayOnResume.addAll([
          TransferUpdate(
            taskId: taskOf('t1'),
            status: TransferStatus.complete,
            relativePath: path1,
          ),
          TransferUpdate(taskId: taskOf('t2'), status: TransferStatus.canceled),
        ]);
      final fresh = newManager(next);
      await fresh.start();
      expect(next.started, isEmpty,
          reason:
              'the start only counts; nothing is started before it is done');
      await fresh.reconcile();
      await fresh.settled();

      expect(fresh.debugInFlight.length, lessThanOrEqualTo(4),
          reason: 'the limit that keeps a home server gentle');
      expect(fresh.debugInFlight, {'t3', 't4', 't5', 't6'});
      expect(next.started.map((r) => r.taskId.split(':').last), ['t5', 't6'],
          reason: 'two places were free: four slots, t3 and t4 still run');
      expect((await row('t1')).state, DownloadState.done);
      expect((await row('t2')).state, DownloadState.failed);
      await fresh.dispose();
    });

    test(
        "N-39: a refresh cancelled while the app was closed leaves the old copy and the half-made new file is deleted, though the new process never planned it",
        () async {
      await repo.pin(PinTargetType.album, 'al1', quality: AudioQuality.high);
      await manager.reconcile();
      transport.complete('t1', size: 5000);
      await manager.settled();
      final oldPath = (await row('t1')).localPath!;
      await (db.update(db.tracks)..where((t) => t.id.equals('t1')))
          .write(const TracksCompanion(audioKey: Value('key1-NEW')));
      await manager.reconcile();
      final partial = transport.requestFor('t1').relativePath;
      expect(partial, endsWith('.opus.new'));
      await manager.dispose(); // the process ends mid-refresh

      final next = FakeDownloadTransport()
        ..files['/app/$partial'] = 100
        ..active = {taskOf('t2'), taskOf('t3'), taskOf('t4')}
        ..replayOnResume.add(TransferUpdate(
          taskId: taskOf('t1'),
          status: TransferStatus.canceled,
          relativePath: partial,
        ));
      final fresh = newManager(next);
      await fresh.start();
      await fresh.settled();

      final r = await row('t1');
      expect(r.state, DownloadState.done,
          reason: 'the copy on the phone is still the song');
      expect(r.localPath, oldPath);
      expect(next.deleted, ['/app/$partial'],
          reason: 'only the half-made new file goes, never the old copy');
      await fresh.dispose();
    });
  });

  // A word about the song's task that is not about the transfer in flight (the acknowledgement of an OLD task with the same id, see item N-45) can
  // carry the path of the copy that is ON the phone. The manager must never delete that file because of such a word: it deletes the half-made `.new` file
  // of a refresh and nothing else. These tests begin after a restart, or with a song that is done: only there is the manager's own plan of the `.new`
  // path unknown, and only the path the update carries is left to decide (in a running app the planned path is deleted first and the guard is not reached).
  group("a stale word that names the copy that is on the phone", () {
    late String livePath; // relative, as an update carries it
    late String oldPath; // absolute, as the row and the fake's files have it

    // t1 is on the phone (5000 bytes), the server says the song changed, and the refresh is in flight at `.new`: the row is a refresh and `downloading`.
    Future<void> refreshInFlight() async {
      await repo.pin(PinTargetType.album, 'al1', quality: AudioQuality.high);
      await manager.reconcile();
      transport.complete('t1', size: 5000);
      await manager.settled();
      oldPath = (await row('t1')).localPath!;
      livePath = transport.requestFor('t1').relativePath.replaceAll('.new', '');
      expect(oldPath, '/app/$livePath');
      await (db.update(db.tracks)..where((t) => t.id.equals('t1')))
          .write(const TracksCompanion(audioKey: Value('key1-NEW')));
      await manager.reconcile();
      expect(transport.requestFor('t1').relativePath, '$livePath.new');
      expect((await row('t1')).state, DownloadState.downloading);
    }

    // A new process whose downloader still runs the other three songs and hands over [replay].
    Future<(FakeDownloadTransport, DownloadManager)> newProcess(
        List<TransferUpdate> replay) async {
      await manager.dispose();
      final next = FakeDownloadTransport()
        ..files[oldPath] = 5000
        ..active = {taskOf('t2'), taskOf('t3'), taskOf('t4')}
        ..replayOnResume.addAll(replay);
      final fresh = newManager(next);
      await fresh.start();
      await fresh.settled();
      return (next, fresh);
    }

    test(
        "N-39: a replayed cancel that names the old copy deletes nothing and leaves the song done",
        () async {
      await refreshInFlight();
      final (next, fresh) = await newProcess([
        TransferUpdate(
            taskId: taskOf('t1'),
            status: TransferStatus.canceled,
            relativePath: livePath),
      ]);

      expect(next.deleted, isNot(contains(oldPath)),
          reason: 'the copy the person has was deleted by a stale word');
      expect(next.files[oldPath], 5000);
      final r = await row('t1');
      expect(r.state, DownloadState.done);
      expect(r.localPath, oldPath);
      expect(r.bytes, 5000);
      await fresh.dispose();
    });

    test(
        "N-39: a replayed failure that names the old copy deletes nothing and leaves the song done",
        () async {
      await refreshInFlight();
      final (next, fresh) = await newProcess([
        TransferUpdate(
            taskId: taskOf('t1'),
            status: TransferStatus.failed,
            error: 'HTTP 500',
            relativePath: livePath),
      ]);

      expect(next.deleted, isNot(contains(oldPath)),
          reason: 'the copy the person has was deleted by a stale word');
      expect(next.files[oldPath], 5000);
      final r = await row('t1');
      expect(r.state, DownloadState.done);
      expect(r.localPath, oldPath);
      expect(r.bytes, 5000);
      await fresh.dispose();
    });

    test(
        "N-39: a late failure that names the copy of a song that is done deletes nothing",
        () async {
      await repo.pin(PinTargetType.album, 'al1', quality: AudioQuality.high);
      await manager.reconcile();
      transport.complete('t1', size: 5000);
      await manager.settled();
      final done = await row('t1');
      expect(done.state, DownloadState.done);
      final live = transport.requestFor('t1').relativePath;

      transport.send(TransferUpdate(
          taskId: taskOf('t1'),
          status: TransferStatus.failed,
          error: 'HTTP 500',
          relativePath: live));
      await manager.settled();

      expect(transport.deleted, isEmpty,
          reason: 'the copy the person has was deleted by a stale word');
      expect(transport.files[done.localPath], 5000);
      final r = await row('t1');
      expect(r.state, DownloadState.done);
      expect(r.localPath, done.localPath);
    });

    // The same word as a completion: the manager checks the file the update names against what the refresh asked for, and deleted a file that did
    // not pass, which was the copy the person has. Found on 17 Nov 2026 while looking for every other place that deletes (not in the review's list).
    test(
        "N-39: a completion that names the old copy, which does not pass the refresh's check, deletes nothing and the refresh goes on",
        () async {
      await refreshInFlight();
      // The refresh asks for the original; the copy on the phone is a lower quality, smaller than the song the server has: the check "is it all
      // there?" fails for it.
      await (db.update(db.downloads)..where((d) => d.trackId.equals('t1')))
          .write(const DownloadsCompanion(refreshQuality: Value('original')));
      await (db.update(db.tracks)..where((t) => t.id.equals('t1')))
          .write(const TracksCompanion(size: Value(30000)));

      transport.send(TransferUpdate(
          taskId: taskOf('t1'),
          status: TransferStatus.complete,
          relativePath: livePath));
      await manager.settled();

      expect(transport.deleted, isNot(contains(oldPath)),
          reason: 'the copy the person has was deleted by a stale word');
      expect(transport.files[oldPath], 5000);
      final r = await row('t1');
      expect(r.state, DownloadState.downloading,
          reason: 'the refresh is still running: the stale word ended it');
      expect(r.localPath, oldPath);
      expect(manager.debugInFlight, contains('t1'),
          reason: 'the place of a transfer that still runs was given away');
    });

    test(
        "N-39: a completion that names the old copy deletes nothing either while the refresh waits in the queue (off Wi-Fi)",
        () async {
      await repo.pin(PinTargetType.album, 'al1', quality: AudioQuality.high);
      await manager.reconcile();
      transport.complete('t1', size: 5000);
      await manager.settled();
      oldPath = (await row('t1')).localPath!;
      livePath = transport.requestFor('t1').relativePath;
      await (db.update(db.tracks)..where((t) => t.id.equals('t1'))).write(
          const TracksCompanion(
              audioKey: Value('key1-NEW'), size: Value(30000)));
      policy = const DownloadPolicy(onWifi: false); // Wi-Fi only: it waits
      await manager.reconcile();
      var r = await row('t1');
      expect(r.state, DownloadState.queued);
      expect(r.localPath, oldPath);
      await (db.update(db.downloads)..where((d) => d.trackId.equals('t1')))
          .write(const DownloadsCompanion(refreshQuality: Value('original')));

      transport.send(TransferUpdate(
          taskId: taskOf('t1'),
          status: TransferStatus.complete,
          relativePath: livePath));
      await manager.settled();

      expect(transport.deleted, isNot(contains(oldPath)),
          reason: 'the copy the person has was deleted by a stale word');
      expect(transport.files[oldPath], 5000);
      r = await row('t1');
      expect(r.state, DownloadState.queued,
          reason: 'the refresh waits: the stale word ended it');
      expect(r.localPath, oldPath);
    });

    test(
        "N-39: a completion that names the old copy and passes the check does not record the refresh as made, and the real completion still swaps the new file in",
        () async {
      await refreshInFlight();
      final before = await row('t1');

      transport.send(TransferUpdate(
          taskId: taskOf('t1'),
          status: TransferStatus.complete,
          relativePath: livePath));
      await manager.settled();

      var r = await row('t1');
      expect(r.state, DownloadState.downloading,
          reason: 'the refresh is still running: the stale word ended it');
      expect(r.quality, before.quality);
      expect(manager.debugInFlight, contains('t1'));
      expect(transport.renamed, isEmpty);

      // The refresh finishes: its `.new` file replaces the old copy in one step.
      transport.complete('t1', size: 6000);
      await manager.settled();
      r = await row('t1');
      expect(r.state, DownloadState.done);
      expect(r.bytes, 6000);
      expect(transport.renamed, [('$oldPath.new', oldPath)]);
      expect(transport.files[oldPath], 6000);
    });
  });

  group("a cancel the manager asks for itself (the person removed the pin)",
      () {
    test(
        "N-39: its acknowledgement changes nothing: no row, no restart, however many passes follow",
        () async {
      transport.acknowledgeCancels = true;
      await repo.pin(PinTargetType.album, 'al1', quality: AudioQuality.high);
      await manager.reconcile();
      await repo.unpin(PinTargetType.album, 'al1');
      await manager.reconcile(immediateRemoval: true);
      await manager.settled();

      expect(transport.canceled.length, 4);
      expect(await repo.rowsFor(['t1', 't2', 't3', 't4']), isEmpty);
      for (var pass = 0; pass < 3; pass++) {
        await manager.reconcile();
      }
      expect(transport.started.length, 4);
      expect(transport.canceled.length, 4);
      expect(manager.debugInFlight, isEmpty);
    });

    test(
        "N-39: the grace of a song that left a list ends with the same cancel and the same quiet",
        () async {
      transport.acknowledgeCancels = true;
      await db.into(db.playlists).insert(PlaylistsCompanion.insert(
          serverId: serverId, id: 'pl1', name: 'Mix'));
      for (var i = 0; i < 2; i++) {
        await db.into(db.playlistEntries).insert(
            PlaylistEntriesCompanion.insert(
                serverId: serverId,
                playlistId: 'pl1',
                position: i,
                trackId: 't${i + 1}'));
      }
      await repo.pin(PinTargetType.playlist, 'pl1', quality: AudioQuality.high);
      await manager.reconcile();
      expect(transport.started.length, 2);

      // The playlist is regenerated without them: the grace starts and nothing is cancelled yet.
      await db.delete(db.playlistEntries).go();
      await manager.reconcile();
      expect(transport.canceled, isEmpty);
      clock.advance(const Duration(hours: 25));
      await manager.reconcile(); // grace over
      await manager.settled();

      expect(transport.canceled.length, 2);
      expect(await repo.rowsFor(['t1', 't2']), isEmpty);
      await manager.reconcile();
      expect(transport.started.length, 2, reason: 'nothing restarts them');
    });

    test(
        "N-39: switched off and on again at once, the new transfers go on: the acknowledgement of the old ones is handled before the next pass",
        () async {
      transport.acknowledgeCancels = true;
      await repo.pin(PinTargetType.album, 'al1', quality: AudioQuality.high);
      await manager.reconcile();
      await repo.unpin(PinTargetType.album, 'al1');
      await manager.reconcile(immediateRemoval: true);
      await repo.pin(PinTargetType.album, 'al1', quality: AudioQuality.high);
      await manager.reconcile();
      expect(transport.started.length, 8,
          reason: 'the same four task ids again');
      await manager.settled();

      for (final id in ['t1', 't2', 't3', 't4']) {
        expect((await row(id)).state, DownloadState.downloading, reason: id);
      }
      expect(manager.debugInFlight, {'t1', 't2', 't3', 't4'});
    });
  });
}
