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

/// N-39: THE PERSON'S OWN STOP, the part that keeps the files (docs/design S-16, S-17, S-96; docs/33 PB-F22, PB-43, PB-44).
///
/// A Stop is the manager's own intent, stored in the pin of the download in the phone's database (v9 `Pins.stoppedAtMs`) and not in memory: the
/// transfers in flight are cancelled AFTER it is stored, so the `canceled` that comes back is never read as a cancel from outside (PR #113's
/// back-off); nothing that is stopped is started, refreshed or tried again by any pass, restart, sync or reconnection until Resume; and nothing is
/// ever deleted by a Stop (only Remove deletes). One test per promise, each seen red against the stubs or the old code and shown to fail against a
/// mutation of the code that keeps it (the list is in the pull request).
void main() {
  late AppDatabase db;
  late FakeClock clock;
  late DownloadsRepository repo;
  late FakeDownloadTransport transport;
  late DownloadManager manager;
  late int serverId;
  var policy = const DownloadPolicy();
  final extra = <DownloadManager>[];

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

  Future<void> boot({FakeDownloadTransport? with_}) async {
    transport = with_ ?? FakeDownloadTransport();
    manager = newManager(transport);
    await manager.start();
  }

  setUp(() async {
    policy = const DownloadPolicy();
    db = AppDatabase(NativeDatabase.memory());
    clock = FakeClock(DateTime.utc(2026, 11, 17, 12));
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
    await boot();
  });

  tearDown(() async {
    for (final m in extra) {
      await m.dispose();
    }
    extra.clear();
    await manager.dispose();
    await db.close();
  });

  const album = (PinTargetType.album, 'al1');
  Future<void> stopAlbum() => manager.stop([album]);
  Future<void> resumeAlbum() => manager.resume([album]);
  Future<DownloadRow> row(String id) async => (await repo.rowsFor([id])).single;
  int startsOf(String id) =>
      transport.started.where((r) => r.taskId.endsWith(':$id')).length;
  List<String> startOrder() =>
      [for (final r in transport.started) r.taskId.split(':').last];
  String taskOf(String id) => 'enc:$serverId:$id';
  Future<void> pinAlbum() async {
    await repo.pin(PinTargetType.album, 'al1', quality: AudioQuality.high);
    await manager.reconcile();
  }

  /// Time passes past every step of the back-off of a failed download (5 min, doubling to the 6 h cap), with a pass over the queue after each.
  Future<void> letEveryBackoffPass() async {
    for (var minutes = 6; minutes <= 6 * 60 + 1; minutes *= 2) {
      clock.advance(Duration(minutes: minutes));
      await manager.reconcile();
    }
    clock.advance(const Duration(hours: 7));
    await manager.reconcile();
  }

  Future<void> expectNothingFailedOrWaiting() async {
    for (var i = 1; i <= 4; i++) {
      final r = await row('t$i');
      expect(r.state, isNot(DownloadState.failed),
          reason: 't$i was read as a failed song');
      expect(r.attempts, 0, reason: 't$i has a wait ahead of it');
      expect(r.lastError, isNull);
    }
  }

  group("the stop is the manager's own intent, stored first", () {
    test(
        "N-39: it is written in the pin and the rows are out of the way BEFORE any transfer is cancelled",
        () async {
      final probe = _OrderProbe(db);
      await manager.dispose();
      await boot(with_: probe);
      await pinAlbum();
      expect(probe.started.length, 4);

      await stopAlbum();

      expect(probe.canceled.length, 4);
      expect(probe.stoppedAtWhenCancelled, everyElement(isNotNull),
          reason:
              'a cancel that went out before the stop was stored would come back as a cancel from outside');
      expect(probe.stateWhenCancelled,
          everyElement(isNot(DownloadState.downloading)),
          reason:
              'a row that still says downloading when its task is cancelled is what PR 113 retries after a wait');
      final pin = (await repo.pins()).single;
      expect(pin.stoppedAtMs, clock.now().millisecondsSinceEpoch);
    });

    test(
        "N-39: the cancel that comes back after the person's own Stop is not an outside cancel: no back-off, no failed song, however long it waits",
        () async {
      transport.acknowledgeCancels = true;
      await pinAlbum();
      expect(transport.started.length, 4);

      await stopAlbum();
      await manager.settled();
      expect(transport.canceled.toSet(),
          {for (var i = 1; i <= 4; i++) taskOf('t$i')});

      await letEveryBackoffPass();

      expect(transport.started.length, 4,
          reason: 'nothing was queued again, not after any back-off step');
      await expectNothingFailedOrWaiting();
      for (var i = 1; i <= 4; i++) {
        expect((await row('t$i')).state, DownloadState.queued);
      }
    });

    test(
        "N-39: a cancel delivered for every task in flight by something else AFTER the Stop's own acknowledgements changes nothing either",
        () async {
      // The first `canceled` after a Stop is the Stop's own acknowledgement (one for each cancel it sent, see the group below): they come first here,
      // so that what is delivered next is a word of something else.
      transport.acknowledgeCancels = true;
      await pinAlbum();
      await stopAlbum();
      await manager.settled();
      for (var i = 1; i <= 4; i++) {
        transport.cancelFromOutside('t$i');
      }
      await manager.settled();

      await letEveryBackoffPass();

      expect(transport.started.length, 4);
      await expectNothingFailedOrWaiting();
    });

    test(
        "N-39: the second layer: a canceled for a song of a stopped download is no outside cancel even when its row still says downloading",
        () async {
      // The Stop's own acknowledgements come first (they are the first layer, and are held by the group below); what is delivered afterwards finds only
      // the stopped song.
      transport.acknowledgeCancels = true;
      await pinAlbum();
      await stopAlbum();
      await manager.settled();
      // The Stop puts the rows out of the way before it cancels, so no row says "downloading" for a stopped song today. A later change (a task id per
      // attempt kept in the row, N-45) must not turn the word guard into the only thing standing: it is a layer of its own and is held here.
      await (db.update(db.downloads)
            ..where((d) => d.trackId.isIn(['t1', 't2'])))
          .write(const DownloadsCompanion(
              state: Value(DownloadState.downloading)));
      transport.cancelFromOutside('t1');
      transport.cancelFromOutside('t2');
      await manager.settled();

      await letEveryBackoffPass();

      expect(transport.started.length, 4);
      for (final id in ['t1', 't2']) {
        final r = await row(id);
        expect(r.state, isNot(DownloadState.failed));
        expect(r.attempts, 0);
        expect(r.lastError, isNull);
      }
    });

    test(
        "N-39: a failure that arrives late for a song the Stop cancelled is not a failed song with a wait, and deletes nothing",
        () async {
      // The cancel's own acknowledgement came first (a failure that is the only word of the cancelled attempt is the group below's); this one is a
      // second word about a song that is stopped, and the stop is what keeps it out of the failures.
      transport.acknowledgeCancels = true;
      await pinAlbum();
      await stopAlbum();
      await manager.settled();
      for (var i = 1; i <= 4; i++) {
        transport.fail('t$i');
      }
      await manager.settled();

      await letEveryBackoffPass();

      expect(transport.started.length, 4);
      await expectNothingFailedOrWaiting();
      expect(transport.deleted, isEmpty);
    });

    test(
        "N-39: a manager built again on the same database is still stopped: nothing restarts, at the start, at any pass, after any time",
        () async {
      await pinAlbum();
      transport.complete('t1');
      await manager.settled();
      await stopAlbum();
      await manager.dispose();

      final after = FakeDownloadTransport();
      final second = newManager(after);
      extra.add(second);
      await second.start();
      for (var pass = 0; pass < 3; pass++) {
        clock.advance(const Duration(hours: 7));
        await second.reconcile();
      }

      expect(after.started, isEmpty,
          reason:
              'the person stopped it: the next start of the app starts nothing');
      expect((await repo.pins()).single.stoppedAtMs, isNotNull);
      expect((await row('t1')).state, DownloadState.done);
      for (var i = 2; i <= 4; i++) {
        expect((await row('t$i')).state, DownloadState.queued);
      }
    });

    test(
        "N-39: stopping it a second time, or resuming one that is not stopped, changes nothing more",
        () async {
      await pinAlbum();
      await stopAlbum();
      final first = (await repo.pins()).single.stoppedAtMs;
      clock.advance(const Duration(minutes: 3));
      await stopAlbum();
      expect((await repo.pins()).single.stoppedAtMs, first,
          reason: 'the time of the first Stop is kept');
      expect(transport.canceled.length, 4);

      await resumeAlbum();
      await resumeAlbum();
      expect(transport.started.length, 8,
          reason: 'each song started once more');
      expect((await repo.pins()).single.stoppedAtMs, isNull);
    });

    test(
        "N-39: a Stop pressed before the first pass has made any row holds the download: the songs found later wait too",
        () async {
      await repo.pin(PinTargetType.album, 'al1', quality: AudioQuality.high);
      await stopAlbum();
      await manager.reconcile();
      expect(transport.started, isEmpty);
      expect(await repo.rowsFor(['t1', 't2', 't3', 't4']), isEmpty,
          reason:
              'a stopped download makes no queue of songs that were never started');

      await resumeAlbum();
      expect(transport.started.length, 4);
    });

    test(
        "N-39: the start of the app cancels a task that a kill left running for a song the person had stopped",
        () async {
      await pinAlbum();
      await stopAlbum();
      await manager.dispose();

      final after = FakeDownloadTransport()..active = {taskOf('t1')};
      final second = newManager(after);
      extra.add(second);
      await second.start();

      expect(after.canceled, [taskOf('t1')]);
      expect(after.started, isEmpty);
      expect((await row('t1')).state, DownloadState.queued);
    });
  });

  group("the Stop's own late word, after Resume (review of PR 119, pin 2)", () {
    // The downloader answers a cancel with ONE word for the task: `canceled` (or, when the transfer ended in the very moment, `failed` or `complete`).
    // It can arrive after Resume has started the song again under the SAME task id (enc:<server>:<track>): a word about the old attempt, about a row that
    // says downloading for the new one. The manager keeps, in memory, how many attempts its own Stop interrupted whose last word has not come yet, for
    // each task id, and spends one on the first word that arrives. These tests send the late word by hand (`acknowledgeCancels` stays off, so the word
    // is not delivered inside the Stop's own step).
    TransferUpdate word(String id, TransferStatus status, [String? error]) =>
        TransferUpdate(taskId: taskOf(id), status: status, error: error);
    void lateCancel(String id) =>
        transport.send(word(id, TransferStatus.canceled));

    test(
        "N-39: the Stop's own cancel acknowledgement that comes AFTER Resume is not an outside cancel: the resumed transfers stay and no song starts over the limit",
        () async {
      policy = const DownloadPolicy(maxInFlight: 2);
      await pinAlbum();
      expect(startOrder(), ['t1', 't2']);
      await stopAlbum();
      await resumeAlbum();
      expect(startOrder(), ['t1', 't2', 't1', 't2'],
          reason: 'Resume asked for the two songs again, at the same limit');

      lateCancel('t1');
      lateCancel('t2');
      await manager.settled();

      for (final id in ['t1', 't2']) {
        final r = await row(id);
        expect(r.state, DownloadState.downloading,
            reason: '$id was read as a failed song');
        expect(r.attempts, 0, reason: '$id has a wait ahead of it');
        expect(r.lastError, isNull);
      }
      expect(manager.debugInFlight, {'t1', 't2'},
          reason: 'the place of a running transfer was given away');
      expect(startOrder().length, 4,
          reason: 'the freed place started another song over the limit');
      expect(transport.active.length, lessThanOrEqualTo(2));
      expect(manager.debugStoppedAttempts, isEmpty,
          reason: 'what the manager remembers is spent with the words');
    });

    test(
        "N-39: Stop, Resume, Stop, Resume with two late acknowledgements for each song: each is swallowed once, and the next canceled is an outside cancel",
        () async {
      policy = const DownloadPolicy(maxInFlight: 2);
      await pinAlbum();
      await stopAlbum();
      await resumeAlbum();
      await stopAlbum();
      await resumeAlbum();
      expect(startOrder().length, 6, reason: 'three attempts for each song');

      for (final id in ['t1', 't2']) {
        lateCancel(id);
        lateCancel(id);
      }
      await manager.settled();

      for (final id in ['t1', 't2']) {
        expect((await row(id)).state, DownloadState.downloading);
        expect((await row(id)).attempts, 0);
      }
      expect(manager.debugInFlight, {'t1', 't2'});
      expect(startOrder().length, 6);
      expect(manager.debugStoppedAttempts, isEmpty);

      // A third word is not the answer to any cancel the manager sent: it is the outside cancel of PR 113.
      lateCancel('t1');
      await manager.settled();
      final cut = await row('t1');
      expect(cut.state, DownloadState.failed);
      expect(cut.lastError, kDownloadStoppedReason);
      expect(cut.attempts, 1);
    });

    test(
        "N-39: the prompt acknowledgement spends what the Stop remembered, so a cancel from outside after Resume is still an outside cancel (PR 113)",
        () async {
      policy = const DownloadPolicy(maxInFlight: 2);
      transport.acknowledgeCancels = true;
      await pinAlbum();
      await stopAlbum();
      await manager.settled();
      expect(manager.debugStoppedAttempts, isEmpty,
          reason: 'the acknowledgements arrived inside the Stop');
      await resumeAlbum();

      transport.cancelFromOutside('t1');
      await manager.settled();

      final cut = await row('t1');
      expect(cut.state, DownloadState.failed);
      expect(cut.lastError, kDownloadStoppedReason);
      expect(cut.attempts, 1);
      expect((await row('t2')).state, DownloadState.downloading);
    });

    test(
        "N-39: only the songs the Stop cancelled have an acknowledgement coming: a canceled for another song of the same manager is an outside cancel",
        () async {
      await repo.pin(PinTargetType.track, 't1', quality: AudioQuality.high);
      await repo.pin(PinTargetType.track, 't2', quality: AudioQuality.high);
      await manager.reconcile();
      const t1 = (PinTargetType.track, 't1');
      await manager.stop([t1]);
      await manager.resume([t1]);
      expect(manager.debugStoppedAttempts.keys, [taskOf('t1')],
          reason: 'one attempt of one song, not a flag for the download');

      lateCancel('t2');
      await manager.settled();
      expect((await row('t2')).state, DownloadState.failed,
          reason: 'nobody had cancelled t2: this is the cancel from outside');

      lateCancel('t1');
      await manager.settled();
      expect((await row('t1')).state, DownloadState.downloading);
      expect(manager.debugStoppedAttempts, isEmpty);
    });

    test(
        "N-39: a Stop of songs that are not in flight leaves nothing to remember: no acknowledgement can come for a cancel that was never sent",
        () async {
      policy = const DownloadPolicy(wifiOnly: true, onWifi: false);
      await pinAlbum();
      expect(transport.started, isEmpty);

      await stopAlbum();
      await stopAlbum();

      expect(transport.canceled, isEmpty);
      expect(manager.debugStoppedAttempts, isEmpty);
    });

    test(
        "N-39: a failure that is the cancelled attempt's own last word, arriving after Resume, is swallowed once; the new attempt's real failure after it is a failed song",
        () async {
      policy = const DownloadPolicy(maxInFlight: 2);
      await pinAlbum();
      await stopAlbum();
      await resumeAlbum();

      transport.send(word('t1', TransferStatus.failed, 'HTTP 500'));
      await manager.settled();
      expect((await row('t1')).state, DownloadState.downloading);
      expect((await row('t1')).attempts, 0);
      expect(manager.debugInFlight, contains('t1'));
      expect(startOrder().length, 4);

      transport.send(word('t1', TransferStatus.failed, 'HTTP 500'));
      await manager.settled();
      expect((await row('t1')).state, DownloadState.failed,
          reason: 'only ONE word was the old attempt\'s');
      expect((await row('t1')).attempts, 1);
    });

    test(
        "N-39: a cancel the downloader could not answer (it knew no such task) promises no word, so it is not remembered: the next real failure is a failed song",
        () async {
      policy = const DownloadPolicy(maxInFlight: 2);
      await pinAlbum();
      // The downloader lost its tasks (a process the system killed, a reset): a cancel finds nothing and no word will ever come for it. The manager
      // still asked, and its rows still say the songs were in flight.
      transport.active.clear();
      await stopAlbum();
      expect(transport.canceled.length, 2, reason: 'the manager did cancel');
      expect(manager.debugStoppedAttempts, isEmpty,
          reason:
              'a memory kept for a word that never comes would swallow the next attempt\'s own failure');

      await resumeAlbum();
      transport.fail('t1');
      await manager.settled();

      final r = await row('t1');
      expect(r.state, DownloadState.failed,
          reason:
              'swallowed: the row would say downloading for ever, with no task behind it and its place held');
      expect(r.attempts, 1);
      expect(manager.debugInFlight, isNot(contains('t1')));
    });

    test(
        "N-39: the finished file of the attempt the Stop interrupted, delivered after Resume, is kept as the song it is, the transfer Resume started for it is cancelled, and no song starts over the limit",
        () async {
      policy = const DownloadPolicy(maxInFlight: 2);
      await pinAlbum();
      final written = transport.requestFor('t1').relativePath;
      await stopAlbum();
      await resumeAlbum();
      expect(startOrder(), ['t1', 't2', 't1', 't2']);
      expect(transport.active.length, 2);

      // The old attempt had finished the file in the very moment of the Stop; its word comes only now.
      transport.files['/app/$written'] = 8000;
      transport.send(TransferUpdate(
          taskId: taskOf('t1'),
          status: TransferStatus.complete,
          relativePath: written));
      await manager.settled();

      expect((await row('t1')).state, DownloadState.done,
          reason: 'a finished file is a song');
      expect(transport.active, isNot(contains(taskOf('t1'))),
          reason:
              'the transfer Resume started for t1 is work already done: it is cancelled, not left to write the same file again');
      expect(transport.active.length, lessThanOrEqualTo(2),
          reason:
              'the freed place started a song beside a transfer that still ran');
      expect(startOrder().length, 5,
          reason:
              'the place t1 gave back went to the next song, once it was really free');
      expect(manager.debugInFlight, {'t2', 't3'});
      expect(transport.deleted, isEmpty);

      // The cancel of that transfer has its one last word too: swallowed, and the song stays what it is.
      lateCancel('t1');
      await manager.settled();
      expect((await row('t1')).state, DownloadState.done);
      expect((await row('t1')).attempts, 0);
      expect(manager.debugStoppedAttempts, isNot(contains(taskOf('t1'))));
    });

    test(
        "N-39: Remove ends the attempts too: what the Stop remembered of them is forgotten, so the same song asked for again is not shielded from a real cancel",
        () async {
      policy = const DownloadPolicy(maxInFlight: 2);
      await pinAlbum();
      await stopAlbum();
      expect(manager.debugStoppedAttempts.keys, hasLength(2));

      await repo.unpin(PinTargetType.album, 'al1');
      await manager.reconcile(immediateRemoval: true);
      expect(manager.debugStoppedAttempts, isEmpty,
          reason:
              'the songs are gone: no attempt of theirs has a word to come');

      await pinAlbum();
      expect(startsOf('t1'), 2);
      transport.cancelFromOutside('t1');
      await manager.settled();
      final cut = await row('t1');
      expect(cut.state, DownloadState.failed,
          reason: 'a memory that outlived its song swallowed the cancel');
      expect(cut.lastError, kDownloadStoppedReason);
    });

    test(
        "N-39: a song that finished in the very moment of the Stop is kept as the file it is, and the Stop's memory of it is spent",
        () async {
      await pinAlbum();
      await stopAlbum();
      expect(manager.debugStoppedAttempts.keys, hasLength(4));

      transport.complete('t1', size: 7000);
      await manager.settled();

      expect((await row('t1')).state, DownloadState.done);
      expect((await row('t1')).bytes, 7000);
      expect(manager.debugStoppedAttempts.keys, isNot(contains(taskOf('t1'))),
          reason:
              'a complete is the last word of the attempt: it is handled, not swallowed, and it spends the memory');
      expect(transport.deleted, isEmpty);
    });

    test(
        "N-39: a refresh that Resume started again keeps its half-made file when the Stop's late acknowledgement arrives",
        () async {
      await pinAlbum();
      transport.complete('t1', size: 5000);
      await manager.settled();
      await (db.update(db.tracks)..where((t) => t.id.equals('t1')))
          .write(const TracksCompanion(audioKey: Value('key1-NEW')));
      await manager.reconcile();
      expect(transport.requestFor('t1').relativePath, endsWith('.opus.new'));
      await stopAlbum();
      await resumeAlbum();
      expect(startsOf('t1'), 3,
          reason: 'the first download, the refresh, and the refresh again');

      lateCancel('t1');
      await manager.settled();

      final r = await row('t1');
      expect(r.state, DownloadState.downloading,
          reason: 'the refresh Resume started is still running');
      expect(r.refreshQuality, isNotNull);
      expect(transport.deleted, isEmpty,
          reason: 'the half-made file belongs to the transfer that is running');
      expect(manager.debugInFlight, contains('t1'));
    });

    test(
        "N-39: the start of the app that cancels a task a kill left running for a stopped song spends its acknowledgement too, when Resume comes first",
        () async {
      await pinAlbum();
      await stopAlbum();
      await manager.dispose();

      final after = FakeDownloadTransport()..active = {taskOf('t1')};
      final second = newManager(after);
      extra.add(second);
      await second.start();
      expect(after.canceled, [taskOf('t1')]);
      await second.resume([album]);
      expect(
          after.started.where((r) => r.taskId == taskOf('t1')), hasLength(1));

      after.send(word('t1', TransferStatus.canceled));
      await second.settled();

      expect((await row('t1')).state, DownloadState.downloading);
      expect((await row('t1')).attempts, 0);
    });
  });

  group("nothing that is stopped is started, refreshed or tried again", () {
    test(
        "N-39: no pass, retry, change of network or passing of time starts a stopped song, a failed one included, and Retry leaves its count alone",
        () async {
      await pinAlbum();
      transport.fail('t4');
      await manager.settled();
      expect((await row('t4')).state, DownloadState.failed);
      await stopAlbum();
      final started = transport.started.length;

      await manager.retryFailed();
      policy = const DownloadPolicy(onWifi: false);
      await manager.reconcile();
      policy = const DownloadPolicy();
      await manager.reconcile();
      await letEveryBackoffPass();

      expect(transport.started.length, started);
      final failed = await row('t4');
      expect(failed.state, DownloadState.failed,
          reason:
              'the song that did not come is still counted while the download is stopped (S-16: "7 of 10 on this phone · 3 songs did not come")');
      expect(failed.attempts, 1);
    });

    test(
        "N-39: a song that another download that goes on also wants keeps coming; the rest of the stopped one does not",
        () async {
      await db.into(db.playlists).insert(
          PlaylistsCompanion.insert(serverId: serverId, id: 'p1', name: 'Mix'));
      await db.into(db.playlistEntries).insert(PlaylistEntriesCompanion.insert(
          serverId: serverId, playlistId: 'p1', position: 0, trackId: 't1'));
      await repo.pin(PinTargetType.playlist, 'p1', quality: AudioQuality.high);
      await pinAlbum();
      expect(startsOf('t1'), 1);

      await stopAlbum();

      expect(transport.canceled, isNot(contains(taskOf('t1'))));
      expect((await row('t1')).state, DownloadState.downloading);
      expect(transport.canceled,
          containsAll([taskOf('t2'), taskOf('t3'), taskOf('t4')]));
      transport.complete('t1');
      await manager.settled();
      expect((await row('t1')).state, DownloadState.done);
    });

    test(
        "N-39: a copy that was being refreshed when the Stop came is still the song: it plays, and nothing of it is deleted",
        () async {
      transport.acknowledgeCancels = true;
      await pinAlbum();
      transport.complete('t1', size: 5000);
      await manager.settled();
      final oldPath = (await row('t1')).localPath!;
      await (db.update(db.tracks)..where((t) => t.id.equals('t1')))
          .write(const TracksCompanion(audioKey: Value('key1-NEW')));
      await manager.reconcile();
      expect(transport.requestFor('t1').relativePath, endsWith('.opus.new'));

      await stopAlbum();
      await manager.settled();

      final r = await row('t1');
      expect(r.state, DownloadState.done);
      expect(r.localPath, oldPath);
      expect(r.refreshQuality, isNull);
      expect(await repo.localPathFor('t1'), oldPath);
      expect(transport.deleted, isEmpty,
          reason: 'a Stop deletes nothing, not even the half of the new file');

      await letEveryBackoffPass();
      expect(startsOf('t1'), 2, reason: 'the refresh waits for Resume too');
      expect((await row('t1')).state, DownloadState.done,
          reason:
              'a song of a stopped download is not set up for a refresh: its old copy is the song, and it plays');
      expect(await repo.localPathFor('t1'), oldPath);
      await resumeAlbum();
      expect(startsOf('t1'), 3);
    });

    test(
        "N-39: a refresh that was only waiting in the queue when the Stop came leaves the old copy playable, not stuck behind the stop",
        () async {
      await pinAlbum();
      transport.complete('t1', size: 5000);
      await manager.settled();
      final oldPath = (await row('t1')).localPath!;
      policy = const DownloadPolicy(onWifi: false);
      await (db.update(db.tracks)..where((t) => t.id.equals('t1')))
          .write(const TracksCompanion(audioKey: Value('key1-NEW')));
      await manager.reconcile();
      expect((await row('t1')).state, DownloadState.queued,
          reason: 'a refresh waiting for Wi-Fi');

      await stopAlbum();

      expect((await row('t1')).state, DownloadState.done);
      expect(await repo.localPathFor('t1'), oldPath);
      policy = const DownloadPolicy();
      await resumeAlbum();
      expect(startsOf('t1'), 2, reason: 'Resume plans the refresh again');
    });
  });

  group("a Stop never deletes a file", () {
    test(
        "N-39: Stop, the late words, a restart, a stopped week and Resume delete nothing and lose no finished copy",
        () async {
      transport.acknowledgeCancels = true;
      await pinAlbum();
      transport.complete('t1', size: 5000);
      transport.complete('t2', size: 6000);
      await manager.settled();
      final paths = {
        for (final id in ['t1', 't2']) id: (await row(id)).localPath!
      };
      // What a refresh in flight at the Stop leaves on the disk: its half-made file. A Stop deletes nothing, not even that (only Remove does).
      final partial = '${paths['t1']}.new';
      transport.files[partial] = 1234;

      await stopAlbum();
      transport.fail('t3');
      transport.cancelFromOutside('t4');
      await manager.settled();
      await manager.dispose();
      final after = FakeDownloadTransport()
        ..acknowledgeCancels = true
        ..files.addAll(transport.files);
      final second = newManager(after);
      extra.add(second);
      await second.start();
      clock.advance(const Duration(days: 8));
      await second.reconcile();

      expect(after.deleted, isEmpty);
      expect(transport.deleted, isEmpty);
      for (final e in paths.entries) {
        expect(after.files, contains(e.value), reason: '${e.key} was lost');
        expect((await row(e.key)).state, DownloadState.done);
        expect((await row(e.key)).localPath, e.value);
      }
      expect(after.files, contains(partial),
          reason:
              "the half-made file of a refresh is not for a Stop to delete");

      expect(after.started, isEmpty,
          reason: 'the restart and the pass of a week later started nothing');
      await second.resume([album]);
      expect(after.deleted, isEmpty);
      expect(after.started.map((r) => r.taskId.split(':').last).toList(),
          ['t3', 't4'],
          reason: 'what Resume starts is what was not on the phone');
    });

    test(
        "N-39: a song that finishes in the very moment of the Stop is kept, not thrown away, and the place it frees starts nothing",
        () async {
      policy = const DownloadPolicy(maxInFlight: 2);
      await pinAlbum();
      expect(transport.started.length, 2);
      await stopAlbum();

      transport.complete('t1', size: 7000);
      await manager.settled();

      final r = await row('t1');
      expect(r.state, DownloadState.done);
      expect(r.bytes, 7000);
      expect(transport.deleted, isEmpty);
      expect(startsOf('t3'), 0,
          reason: 'the stopped download starts no other song');
    });

    test(
        "N-39: Remove is the one path that deletes: it deletes the copies of a stopped download and what was still coming is not fetched",
        () async {
      await pinAlbum();
      transport.complete('t1', size: 5000);
      transport.complete('t2', size: 6000);
      await manager.settled();
      final p1 = (await row('t1')).localPath!;
      final p2 = (await row('t2')).localPath!;
      await stopAlbum();
      expect(transport.deleted, isEmpty);

      await repo.unpin(PinTargetType.album, 'al1');
      await manager.reconcile(immediateRemoval: true);

      expect(transport.deleted, unorderedEquals([p1, p2]));
      expect(await repo.rowsFor(['t1', 't2', 't3', 't4']), isEmpty);
      await resumeAlbum();
      expect(startsOf('t3'), 1, reason: 'a removed download is not fetched');
    });
  });

  group("Remove also takes the half-made file of a refresh (review of PR 119)",
      () {
    // A refresh in flight at the Stop leaves its `.new` file on disk (a Stop deletes nothing). Remove is THE path that deletes, so it takes that file
    // too, and only the files of the songs it removes, also after the app was closed in between (the stop is in the database; the manager's own plan
    // of the path is not).
    Future<(String, String)> refreshOneAndStop() async {
      await pinAlbum();
      transport.complete('t1', size: 5000);
      await manager.settled();
      final copy = (await row('t1')).localPath!;
      await (db.update(db.tracks)..where((t) => t.id.equals('t1')))
          .write(const TracksCompanion(audioKey: Value('key1-NEW')));
      await manager.reconcile();
      final partial = '/app/${transport.requestFor('t1').relativePath}';
      expect(partial, endsWith('.opus.new'));
      transport.files[partial] = 1234;
      await stopAlbum();
      await manager.settled();
      expect(transport.deleted, isEmpty, reason: 'a Stop deletes nothing');
      expect(transport.files, contains(partial));
      return (copy, partial);
    }

    test(
        "N-39: Remove after a Stop that came in the middle of a refresh deletes the old copy and the half-made file, and nothing else",
        () async {
      final (copy, partial) = await refreshOneAndStop();

      await repo.unpin(PinTargetType.album, 'al1');
      await manager.reconcile(immediateRemoval: true);

      expect(transport.deleted, unorderedEquals([copy, partial]));
      expect(transport.files, isNot(contains(partial)));
      expect(await repo.rowsFor(['t1', 't2', 't3', 't4']), isEmpty);
    });

    test(
        "N-39: the same after the app was closed and opened again: the manager no longer knows the path, and finds the half-made file from what it could have written",
        () async {
      final (copy, partial) = await refreshOneAndStop();
      // A refresh that asked for the original quality writes `.flac.new` (the source's own suffix), a different name from the copy's.
      const other = '/app/downloads/1/t1.flac.new';
      transport.files[other] = 99;
      await manager.dispose();
      final after = FakeDownloadTransport()..files.addAll(transport.files);
      final second = newManager(after);
      extra.add(second);
      await second.start();
      expect(after.deleted, isEmpty, reason: 'starting deletes nothing');

      await repo.unpin(PinTargetType.album, 'al1');
      await second.reconcile(immediateRemoval: true);

      expect(after.deleted, unorderedEquals([copy, partial, other]));
      expect(after.files, isEmpty);
    });

    test(
        "N-39: only the files of the songs that are removed: a song another download keeps coming keeps its copy and its half-made file",
        () async {
      await db.into(db.playlists).insert(
          PlaylistsCompanion.insert(serverId: serverId, id: 'p1', name: 'Mix'));
      await db.into(db.playlistEntries).insert(PlaylistEntriesCompanion.insert(
          serverId: serverId, playlistId: 'p1', position: 0, trackId: 't2'));
      await repo.pin(PinTargetType.playlist, 'p1', quality: AudioQuality.high);
      await pinAlbum();
      transport.complete('t1', size: 5000);
      transport.complete('t2', size: 6000);
      await manager.settled();
      final copy1 = (await row('t1')).localPath!;
      final copy2 = (await row('t2')).localPath!;
      for (final id in ['t1', 't2']) {
        await (db.update(db.tracks)..where((t) => t.id.equals(id)))
            .write(TracksCompanion(audioKey: Value('$id-NEW')));
      }
      await manager.reconcile();
      final partial1 = '/app/${transport.requestFor('t1').relativePath}';
      final partial2 = '/app/${transport.requestFor('t2').relativePath}';
      transport.files[partial1] = 1;
      transport.files[partial2] = 2;

      await stopAlbum();
      await manager.reconcile();
      expect(transport.deleted, isEmpty);
      await repo.unpin(PinTargetType.album, 'al1');
      await manager.reconcile(immediateRemoval: true);

      expect(transport.deleted, unorderedEquals([copy1, partial1]));
      expect(transport.files, contains(copy2));
      expect(transport.files, contains(partial2));
      expect((await row('t2')).state, isNot(DownloadState.failed));
    });
  });

  group("Resume puts the stopped songs back", () {
    test(
        "N-39: exactly the songs that were not on the phone, in their old order, none twice; a song added to the list while it was stopped waits and then comes last",
        () async {
      // The downloader answers a cancel with its one last word, as the real one does: the completions below are the new attempts' own.
      transport.acknowledgeCancels = true;
      policy = const DownloadPolicy(maxInFlight: 1);
      await pinAlbum();
      expect(startOrder(), ['t1']);
      transport.complete('t1');
      await manager.settled();
      expect(startOrder(), ['t1', 't2']);

      await stopAlbum();
      await db.into(db.tracks).insert(TracksCompanion.insert(
            serverId: serverId,
            id: 't5',
            title: 'Song 5',
            albumId: const Value('al1'),
            suffix: const Value('flac'),
            bitRate: const Value(900),
            audioKey: const Value('key5'),
          ));
      await manager.reconcile();
      expect(startOrder(), ['t1', 't2'],
          reason: 'the song added to a stopped list does not start by itself');

      await resumeAlbum();
      for (final id in ['t2', 't3', 't4']) {
        transport.complete(id);
        await manager.settled();
      }
      expect(startOrder(), ['t1', 't2', 't2', 't3', 't4', 't5']);
      expect(startsOf('t1'), 1,
          reason: 'the song that was done is not asked again');
      transport.complete('t5');
      await manager.settled();
      for (var i = 1; i <= 5; i++) {
        expect((await row('t$i')).state, DownloadState.done);
      }
    });

    test(
        "N-39: Resume of a release one of whose songs was asked for on its own brings back exactly the songs the Stop held, in their old order, and does not start the other again",
        () async {
      policy = const DownloadPolicy(maxInFlight: 1);
      transport.acknowledgeCancels = true;
      const release = ['t1', 't2', 't3', 't4'];
      for (final id in release) {
        await repo.pin(PinTargetType.track, id,
            quality: AudioQuality.high, alongside: release);
      }
      await manager.reconcile();
      expect(startOrder(), ['t1']);
      final keys = [for (final id in release) (PinTargetType.track, id)];
      await manager.stop(keys);

      // The person asks for t3 on its own (the track menu): a new request. It is not stopped, it goes on by itself, and the others still wait.
      await repo.pin(PinTargetType.track, 't3', quality: AudioQuality.high);
      await manager.reconcile();
      expect(await repo.heldTrackIds(), {'t1', 't2', 't4'});
      expect(startOrder(), ['t1', 't3']);

      await manager.resume(keys);
      expect(await repo.heldTrackIds(), isEmpty,
          reason: 'every song the Stop held is released');
      expect(startOrder(), ['t1', 't3'],
          reason:
              "the place is the one of t3 until it is done, and it is not started again");
      for (final id in ['t3', 't1', 't2']) {
        transport.complete(id);
        await manager.settled();
      }
      expect(startOrder(), ['t1', 't3', 't1', 't2', 't4'],
          reason: 'the held songs come back in their old order');
      expect(startsOf('t3'), 1);
    });
  });

  group("Resume keeps the order the songs were asked for", () {
    test(
        "N-39: the songs come back in the order they were first asked for, not in the order of their ids, and each song is asked for once",
        () async {
      transport.acknowledgeCancels = true;
      // The songs are asked for one after the other with the phone off Wi-Fi, so their rows are made in this order and nothing starts yet.
      policy = const DownloadPolicy(wifiOnly: true, onWifi: false);
      const order = ['t4', 't2', 't3', 't1'];
      for (final id in order) {
        await repo.pin(PinTargetType.track, id, quality: AudioQuality.high);
        await manager.reconcile();
      }
      expect(transport.started, isEmpty);
      policy = const DownloadPolicy(maxInFlight: 1);
      await manager.reconcile();
      expect(startOrder(), ['t4']);

      final pins = [for (final id in order) (PinTargetType.track, id)];
      await manager.stop(pins);
      await manager.reconcile();
      expect(startOrder(), ['t4'], reason: 'stopped: nothing starts');
      await manager.resume(pins);
      expect(startOrder(), ['t4', 't4']);
      for (final id in ['t4', 't2', 't3']) {
        transport.complete(id);
        await manager.settled();
      }

      expect(startOrder(), ['t4', 't4', 't2', 't3', 't1']);
    });
  });

  group("a song that joins a stopped release later waits too", () {
    // A catalogue release is a set of per-song pins, made one after the other (and the rest at the next start of the app if a kill came between):
    // the songs that are not pinned yet when the Stop comes have no pin of their own to hold them.
    const release = ['t1', 't2', 't3', 't4'];
    Future<void> pinSong(String id,
            {List<String> alongside = const []}) async =>
        repo.pin(PinTargetType.track, id,
            quality: AudioQuality.high, alongside: alongside);

    test(
        "N-39: pinned with the release's other songs while those are stopped, it is stopped too: no pass, restart or passing of time starts it, Resume brings it",
        () async {
      await pinSong('t1', alongside: release);
      await pinSong('t2', alongside: release);
      await manager.reconcile();
      await manager.stop([
        (PinTargetType.track, 't1'),
        (PinTargetType.track, 't2'),
      ]);

      await pinSong('t3', alongside: release);
      await pinSong('t4', alongside: release);
      await manager.reconcile();
      await letEveryBackoffPass();
      expect([for (final id in release) startsOf(id)], [1, 1, 0, 0],
          reason:
              'the first two ran before the Stop; nothing started after it, the late songs included');
      final pins = {for (final p in await repo.pins()) p.targetId: p};
      expect(pins['t3']!.stoppedAtMs, isNotNull);
      expect(pins['t4']!.stoppedAtMs, isNotNull);

      // The app is closed and opened again: still nothing.
      await manager.dispose();
      final after = FakeDownloadTransport();
      final second = newManager(after);
      extra.add(second);
      await second.start();
      await second.reconcile();
      expect(after.started, isEmpty);

      await second.resume([
        for (final id in release) (PinTargetType.track, id),
      ]);
      expect({
        for (final r in after.started) r.taskId.split(':').last
      }, {
        't1',
        't2',
        't3',
        't4'
      }, reason: 'Resume asks for every song that is not on the phone');
    });

    test(
        "N-39: a song the person asks for on its own is the person's own request: it starts at once and does not wait with the stopped release",
        () async {
      await pinSong('t1', alongside: release);
      await manager.reconcile();
      await manager.stop([(PinTargetType.track, 't1')]);

      await pinSong('t3'); // the song menu's Download: no release around it
      await manager.reconcile();

      expect(startsOf('t3'), 1);
      expect(
          (await repo.pins())
              .where((p) => p.targetId == 't3')
              .single
              .stoppedAtMs,
          isNull);
    });

    test(
        "N-39: a release that is not stopped is not slowed: its late songs start as before",
        () async {
      await pinSong('t1', alongside: release);
      await manager.reconcile();
      await pinSong('t3', alongside: release);
      await manager.reconcile();

      expect(startsOf('t3'), 1);
    });
  });
}

/// A transport that notes what the database says at the moment each task is cancelled.
class _OrderProbe extends FakeDownloadTransport {
  _OrderProbe(this.db);

  final AppDatabase db;
  final List<int?> stoppedAtWhenCancelled = [];
  final List<int> stateWhenCancelled = [];

  @override
  Future<bool> cancel(String taskId) async {
    stoppedAtWhenCancelled
        .add((await db.select(db.pins).get()).single.stoppedAtMs);
    final id = taskId.split(':').last;
    stateWhenCancelled.add((await (db.select(db.downloads)
              ..where((d) => d.trackId.equals(id)))
            .getSingle())
        .state);
    return super.cancel(taskId);
  }
}
