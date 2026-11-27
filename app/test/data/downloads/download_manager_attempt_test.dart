import 'package:drift/drift.dart' show Value;
import 'package:drift/native.dart';
import 'package:encore/core/clock.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/downloads/download_manager.dart';
import 'package:encore/data/downloads/download_planner.dart';
import 'package:encore/data/downloads/download_transport.dart';
import 'package:encore/data/repos/downloads_repository.dart';
import 'package:encore/domain/audio_quality.dart';
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

/// N-45: a late word of an OLD download task can never end a NEW attempt of the same song.
///
/// Found by the N-39 helper and the review of PR 113: a task used to be named from the song alone (`enc:<server>:<track>`), so the downloader's last
/// word of an attempt that was switched off (it answers a cancel, or a transfer that ended in the very moment of the cancel) was read against the row of
/// the attempt that replaced it. Reachable by switching a download off and on again inside the 400 ms debounce: the new transfer's row failed with a
/// back-off, its place went to another song, and the transfer went on with nothing behind it. Every attempt now has its own task id, stored in the row
/// before the downloader is asked, and a word is read only against the attempt it names.
void main() {
  late AppDatabase db;
  late FakeClock clock;
  late DownloadsRepository repo;
  late FakeDownloadTransport transport;
  late DownloadManager manager;
  late int serverId;
  var policy = const DownloadPolicy();
  const album = (PinTargetType.album, 'al1');

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
    clock = FakeClock(DateTime.utc(2026, 11, 27, 12));
    serverId = await db.into(db.servers).insert(ServersCompanion.insert(
        name: 'T', username: 'u', endpointsJson: '[]', createdAtMs: 0));
    for (var i = 1; i <= 3; i++) {
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

  /// The ids the manager asked the downloader to run for a song, oldest first: a test says WHICH attempt a word is about.
  List<String> attemptsOf(String id) => [
        for (final r in transport.started)
          if (r.taskId.endsWith(':$id')) r.taskId
      ];

  /// A download switched off and on again: the pin goes, the pass deletes the row and cancels the task, the pin comes back and the next pass starts the
  /// song again. Returns the ids of the first and the second attempt.
  Future<(String, String)> switchedOffAndOn() async {
    await repo.pin(PinTargetType.album, 'al1', quality: AudioQuality.high);
    await manager.reconcile();
    expect(attemptsOf('t1'), hasLength(1));
    final first = attemptsOf('t1').single;

    await repo.unpin(PinTargetType.album, 'al1');
    await manager.reconcile(immediateRemoval: true);
    expect(transport.canceled, contains(first),
        reason: 'the old task was cancelled');
    await repo.pin(PinTargetType.album, 'al1', quality: AudioQuality.high);
    await manager.reconcile();

    expect(attemptsOf('t1'), hasLength(2), reason: 'a second attempt started');
    return (first, attemptsOf('t1').last);
  }

  group('a late word of the attempt that was switched off', () {
    test(
        'N-45: each attempt has its own task id, also when the row was deleted in between',
        () async {
      final (first, second) = await switchedOffAndOn();

      expect(second, isNot(first),
          reason: 'the same name is what let an old word end a new attempt');
    });

    test('N-45: a late failure of the old attempt does not end the new one',
        () async {
      final (first, second) = await switchedOffAndOn();

      transport.send(TransferUpdate(
          taskId: first, status: TransferStatus.failed, error: 'HTTP 500'));
      await manager.settled();

      final r = await row('t1');
      expect(r.state, DownloadState.downloading,
          reason: 'the new attempt is still running: its row is not failed');
      expect(r.attempts, 0, reason: 'and no back-off was written for it');
      expect(manager.debugInFlight, contains('t1'),
          reason: 'its place is not given away to another song');
      expect(transport.active, contains(second));
    });

    test(
        'N-45: a late cancel acknowledgement of the old attempt does not end the new one',
        () async {
      final (first, second) = await switchedOffAndOn();

      transport
          .send(TransferUpdate(taskId: first, status: TransferStatus.canceled));
      await manager.settled();

      final r = await row('t1');
      expect(r.state, DownloadState.downloading);
      expect(r.attempts, 0);
      expect(manager.debugInFlight, contains('t1'));
      expect(transport.active, contains(second));
    });

    test(
        'N-45: a late completion of the old attempt does not end the new one as done',
        () async {
      final (first, second) = await switchedOffAndOn();
      final planned = transport.started.last.relativePath;
      transport.files['/app/$planned'] = 4096;

      transport.send(TransferUpdate(
          taskId: first,
          status: TransferStatus.complete,
          progress: 1,
          relativePath: planned));
      await manager.settled();

      final r = await row('t1');
      expect(r.state, DownloadState.downloading,
          reason:
              'the attempt that runs writes the same file and ends the song itself');
      expect(manager.debugInFlight, contains('t1'),
          reason: 'its place is kept while its transfer runs');
      expect(transport.active, contains(second));

      transport.complete('t1');
      await manager.settled();
      expect((await row('t1')).state, DownloadState.done,
          reason: 'and the new attempt still ends as it should');
    });

    test(
        'N-45: a late completion of the old attempt still completes the song when NO newer attempt runs (the new row is only queued): a finished file is not downloaded again',
        () async {
      await repo.pin(PinTargetType.album, 'al1', quality: AudioQuality.high);
      await manager.reconcile();
      final old = transport.requestFor('t1');
      expect(transport.started, hasLength(3));

      // Off Wi-Fi nothing is started: the download is switched off and on again and the new row waits in the queue, with no task name of its own.
      policy = const DownloadPolicy(wifiOnly: true, onWifi: false);
      await repo.unpin(PinTargetType.album, 'al1');
      await manager.reconcile(immediateRemoval: true);
      await repo.pin(PinTargetType.album, 'al1', quality: AudioQuality.high);
      await manager.reconcile();
      expect((await row('t1')).state, DownloadState.queued);
      expect(attemptsOf('t1'), hasLength(1), reason: 'nothing started again');

      // The old attempt had finished the file when the cancel reached it: its word comes now.
      transport.files['/app/${old.relativePath}'] = 4096;
      transport.send(TransferUpdate(
          taskId: old.taskId,
          status: TransferStatus.complete,
          relativePath: old.relativePath,
          qualityId: old.qualityId));
      await manager.settled();

      final r = await row('t1');
      expect(r.state, DownloadState.done,
          reason:
              'a finished file is the song: it was dropped and the song would be downloaded again in full, maybe over mobile data');
      expect(r.quality, old.qualityId);
      expect(attemptsOf('t1'), hasLength(1), reason: 'no second download');
      expect(transport.deleted, isEmpty);
    });

    test('N-45: the words of the new attempt still end it', () async {
      await switchedOffAndOn();

      transport.fail('t1');
      await manager.settled();

      final r = await row('t1');
      expect(r.state, DownloadState.failed);
      expect(r.attempts, 1);
      expect(manager.debugInFlight, isNot(contains('t1')));
    });
  });

  group(
      'a refresh is under way and a late word of the FIRST download names the copy on the phone',
      () {
    late String livePath; // relative, as an update carries it
    late String oldPath; // absolute, as the row and the fake's files have it

    // t1 is on the phone (5000 bytes), the server says the song changed, and the refresh is in flight at `.new`: a second attempt of the same song.
    Future<void> refreshInFlight() async {
      await repo.pin(PinTargetType.album, 'al1', quality: AudioQuality.high);
      await manager.reconcile();
      transport.complete('t1', size: 5000);
      await manager.settled();
      oldPath = (await row('t1')).localPath!;
      livePath = transport.requestFor('t1').relativePath;
      await (db.update(db.tracks)..where((t) => t.id.equals('t1')))
          .write(const TracksCompanion(audioKey: Value('key1-NEW')));
      await manager.reconcile();
      expect(transport.requestFor('t1').relativePath, '$livePath.new');
      expect(attemptsOf('t1'), hasLength(2));
    }

    for (final status in [
      TransferStatus.canceled,
      TransferStatus.failed,
      TransferStatus.complete,
    ]) {
      test(
          'N-45: a late ${status.name} of the first download deletes nothing and leaves the refresh running under its own name',
          () async {
        await refreshInFlight();

        transport.send(TransferUpdate(
          taskId: attemptsOf('t1').first,
          status: status,
          relativePath: livePath,
          error: status == TransferStatus.failed ? 'HTTP 500' : null,
        ));
        await manager.settled();

        expect(transport.deleted, isEmpty,
            reason: 'the copy the person has was deleted by a late word');
        expect(transport.files[oldPath], 5000);
        final r = await row('t1');
        expect(r.state, DownloadState.downloading,
            reason: 'the refresh is still running');
        expect(r.localPath, oldPath);
        expect(r.attempts, 0);
        expect(manager.debugInFlight, contains('t1'));
        expect(transport.active, contains(attemptsOf('t1').last));
      });
    }
  });

  // The six costs docs/33 (PB-44, PB-F22) lists as "what a person would see while N-45 is not built", found by the adversarial tester of 22 Nov 2026. N-45 is
  // done only when each has a test that fails on the code before it and passes with the task id per attempt.
  group(
      'the six costs of a word of an old attempt read as the newest one\'s (docs/33)',
      () {
    Future<void> pinAndStopAndResume() async {
      await repo.pin(PinTargetType.album, 'al1', quality: AudioQuality.high);
      await manager.reconcile();
      await manager.stop([album]);
      await manager.resume([album]);
      for (final id in ['t1', 't2', 't3']) {
        expect(attemptsOf(id), hasLength(2),
            reason: '$id: stopped and resumed');
      }
    }

    test(
        'N-45 (a): Stop, Resume and the app is restarted BEFORE the Stop\'s acknowledgement came: the replayed cancels are about the attempts that were stopped, and the songs that run are not shown as songs that did not come',
        () async {
      await pinAndStopAndResume();
      await manager.dispose();

      final after = FakeDownloadTransport()
        ..active = {
          for (final id in ['t1', 't2', 't3']) transport.latestTaskOf(id)
        }
        ..replayOnResume.addAll([
          for (final id in ['t1', 't2', 't3'])
            TransferUpdate(
                taskId: transport.firstTaskOf(id),
                status: TransferStatus.canceled),
        ]);
      final second = newManager(after);
      await second.start();
      await second.settled();

      for (final id in ['t1', 't2', 't3']) {
        final r = await row(id);
        expect(r.state, DownloadState.downloading,
            reason:
                '$id was read as a cancel from outside, with a back-off, while its task runs');
        expect(r.attempts, 0, reason: id);
        expect(r.lastError, isNull, reason: id);
      }
      expect(after.started, isEmpty, reason: 'nothing is started twice');
      expect(after.canceled, isEmpty);
      expect(second.debugInFlight, {'t1', 't2', 't3'});
      await second.dispose();
    });

    test(
        'N-45 (b): Remove, then a quick download of the same songs again: the removed attempt\'s last word is not the new attempt\'s',
        () async {
      final (first, second) = await switchedOffAndOn();

      transport
          .send(TransferUpdate(taskId: first, status: TransferStatus.canceled));
      await manager.settled();

      final r = await row('t1');
      expect(r.state, DownloadState.downloading,
          reason: 'a song shown as one that did not come while its task runs');
      expect(manager.debugInFlight, contains('t1'),
          reason: 'one place over the limit');
      expect(transport.active, contains(second));
    });

    test(
        'N-45 (c): Stop, Resume, and a cancel from outside of the NEW attempt while the Stop\'s acknowledgement is still owed: the cancel from outside is read as one at once, and the Stop\'s word as the Stop\'s',
        () async {
      await pinAndStopAndResume();

      transport.cancelFromOutside('t1'); // the newest attempt's word, FIRST
      await manager.settled();

      var r = await row('t1');
      expect(r.state, DownloadState.failed,
          reason:
              'one counter took it for the Stop\'s acknowledgement and swallowed it');
      expect(r.lastError, kDownloadStoppedReason);
      expect(r.attempts, 1);

      transport.send(TransferUpdate(
          taskId: transport.firstTaskOf('t1'),
          status: TransferStatus.canceled)); // the Stop's own word, after
      await manager.settled();
      r = await row('t1');
      expect(r.state, DownloadState.failed);
      expect(r.attempts, 1, reason: 'counted once, not twice');
      expect(manager.debugStoppedAttempts,
          isNot(contains(transport.firstTaskOf('t1'))),
          reason: 'the Stop\'s word spent what the Stop owed');
    });

    test(
        'N-45 (d): a cancel word that never arrives does not swallow the real failure of the NEW attempt',
        () async {
      await pinAndStopAndResume(); // the Stop's `canceled` words are never sent

      transport.fail('t1'); // the new attempt really fails

      await manager.settled();
      final r = await row('t1');
      expect(r.state, DownloadState.failed,
          reason:
              'it was swallowed: the song stayed "downloading" with no task behind it and its place held');
      expect(r.attempts, 1);
      expect(manager.debugInFlight, isNot(contains('t1')));
    });

    test(
        'N-45 (e): the Stop\'s late cancel arriving after the NEW attempt ended and a refresh started does not delete the refresh\'s half-made file or free its place',
        () async {
      await pinAndStopAndResume();
      transport.complete('t1',
          size:
              5000); // the new attempt completes, the Stop's word is still owed
      await manager.settled();
      expect((await row('t1')).state, DownloadState.done);
      await (db.update(db.tracks)..where((t) => t.id.equals('t1')))
          .write(const TracksCompanion(audioKey: Value('key1-NEW')));
      await manager.reconcile();
      expect(transport.requestFor('t1').relativePath, endsWith('.opus.new'));
      expect(attemptsOf('t1'), hasLength(3), reason: 'first, resumed, refresh');

      transport.send(TransferUpdate(
          taskId: attemptsOf('t1').first, status: TransferStatus.canceled));
      await manager.settled();

      expect(transport.deleted, isEmpty,
          reason: 'the refresh\'s half-made `.new` file was deleted');
      final r = await row('t1');
      expect(r.state, DownloadState.downloading);
      expect(manager.debugInFlight, contains('t1'),
          reason: 'its place was freed while the refresh task is still live');
      expect(transport.active, contains(attemptsOf('t1').last));
    });

    test(
        'N-45 (f): a late completion of an OLD attempt does not put its quality on the file a newer attempt, at another quality, has made',
        () async {
      await repo.pin(PinTargetType.album, 'al1', quality: AudioQuality.high);
      await manager.reconcile();
      final old = transport.requestFor('t1');
      await manager.stop(
          [album]); // the cancel lost the race to the file: its word is late
      policy = const DownloadPolicy(dataSaver: true);
      await manager.resume([album]);
      final newer = transport.requestFor('t1');
      expect(newer.qualityId, isNot(old.qualityId),
          reason: 'Data saver made the new attempt at another quality');
      expect(newer.relativePath, old.relativePath,
          reason:
              'the same file name: the new attempt overwrites the old attempt\'s file');

      transport.complete('t1',
          size:
              4096); // the new attempt finished: the row is done at ITS quality
      await manager.settled();
      expect((await row('t1')).quality, newer.qualityId);

      transport.send(TransferUpdate(
          taskId: old.taskId,
          status: TransferStatus.complete,
          relativePath: old.relativePath,
          qualityId:
              old.qualityId)); // and only now the old attempt's late word
      await manager.settled();

      final r = await row('t1');
      expect(r.state, DownloadState.done);
      expect(r.quality, newer.qualityId,
          reason:
              'the file is what the newer attempt made: recording the old quality planned no upgrade');
    });

    test(
        'N-45 (f), the other order: the OLD attempt\'s late completion comes FIRST and the newer attempt, which finished in transit, still decides the quality of the file it wrote',
        () async {
      await repo.pin(PinTargetType.album, 'al1', quality: AudioQuality.high);
      await manager.reconcile();
      final old = transport.requestFor('t1');
      await manager.stop([album]);
      policy = const DownloadPolicy(dataSaver: true);
      await manager.resume([album]);
      final newer = transport.requestFor('t1');
      expect(newer.qualityId, isNot(old.qualityId));

      // The old attempt's finished file is the song (the Stop's cancel lost the race to it): kept, and the transfer Resume started is cancelled.
      transport.files['/app/${old.relativePath}'] = 4096;
      transport.send(TransferUpdate(
          taskId: old.taskId,
          status: TransferStatus.complete,
          relativePath: old.relativePath,
          qualityId: old.qualityId));
      await manager.settled();
      expect((await row('t1')).state, DownloadState.done);
      expect(transport.canceled, contains(newer.taskId));

      // But the newer attempt had finished in transit, over the same file name, before the cancel reached it: its own word follows, and what it made is
      // what the file IS. The song has a copy now, which a word that names it must not touch, unless it is the word of the attempt that wrote it last.
      transport.complete('t1', size: 4096);
      await manager.settled();

      final r = await row('t1');
      expect(r.state, DownloadState.done);
      expect(r.quality, newer.qualityId,
          reason:
              'the old quality stayed on a file the newer attempt made: no upgrade would ever be planned for it');
    });
  });

  group('the attempt names of one process and the next', () {
    test(
        'N-45: a new process never reuses the name of an attempt of the one before it, also when the clock has not moved',
        () async {
      await repo.pin(PinTargetType.album, 'al1', quality: AudioQuality.high);
      await manager.reconcile();
      final first = attemptsOf('t1').single;
      await manager.stop([album]);
      await manager.dispose();

      final after = FakeDownloadTransport();
      final second = newManager(after);
      await second.start();
      await second.resume([album]);
      await second.settled();

      final next = after.attemptsOf('t1');
      expect(next, hasLength(1));
      expect(next.single, isNot(first),
          reason:
              'the numbers are seeded from the rows: a fixed clock would give the same name again, and the downloader\'s last word of the first attempt would end the second');
      await second.dispose();
    });

    test(
        'N-45: the name of an attempt holds the song whatever its id contains, and a name that is not ours is not read',
        () async {
      await db.into(db.tracks).insert(TracksCompanion.insert(
            serverId: serverId,
            id: 'a:b:7',
            title: 'Odd id',
            albumId: const Value('al2'),
            suffix: const Value('flac'),
            bitRate: const Value(900),
            audioKey: const Value('keyodd'),
          ));
      await repo.pin(PinTargetType.album, 'al2', quality: AudioQuality.high);
      await manager.reconcile();
      final id = attemptsOf('a:b:7').single;
      expect(id, startsWith('enc2:$serverId:'));
      expect(id, endsWith(':a:b:7'));

      transport.fail('a:b:7');
      await manager.settled();
      expect((await row('a:b:7')).state, DownloadState.failed,
          reason: 'the word was read as the word of the song a:b:7');

      transport.send(TransferUpdate(
          taskId: 'enc2:999:1:a:b:7', status: TransferStatus.failed));
      transport.send(TransferUpdate(
          taskId: 'enc2:$serverId:x:a:b:7', status: TransferStatus.failed));
      await manager.settled();
      expect((await row('a:b:7')).attempts, 1,
          reason:
              'another server\'s name and a name with no attempt number are not ours');
    });
  });

  group('what the downloader kept across the upgrade (a task of the old name)',
      () {
    test(
        'N-45: a row of an older build whose task is still running survives the start and ends with that task\'s own word',
        () async {
      // A row of an older build: "downloading", no task id of its own, and the downloader still runs the task it was handed under the old name.
      await db.into(db.downloads).insert(DownloadsCompanion.insert(
            serverId: serverId,
            trackId: 't2',
            state: const Value(1),
            updatedAtMs: clock.now().millisecondsSinceEpoch,
          ));
      await repo.pin(PinTargetType.track, 't2', quality: AudioQuality.high);
      final old = FakeDownloadTransport()..active = {'enc:$serverId:t2'};
      final restarted = newManager(old);
      await restarted.start();

      expect(old.started.where((r) => r.taskId.endsWith(':t2')), isEmpty,
          reason: 'the running task is not started again (no second download)');
      expect(restarted.debugInFlight, contains('t2'));

      old.send(TransferUpdate(
          taskId: 'enc:$serverId:t2',
          status: TransferStatus.complete,
          progress: 1,
          relativePath: 'downloads/$serverId/t2.flac',
          qualityId: AudioQuality.high.id));
      old.files['/app/downloads/$serverId/t2.flac'] = 4096;
      await restarted.settled();

      expect((await row('t2')).state, DownloadState.done);
      await restarted.dispose();
    });
  });
}
