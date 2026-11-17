import 'package:drift/drift.dart' show Value;
import 'package:drift/native.dart';
import 'package:encore/core/clock.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/downloads/download_manager.dart';
import 'package:encore/data/downloads/download_planner.dart';
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
        "N-39: a cancel delivered for every task in flight by something else AFTER the Stop changes nothing either",
        () async {
      await pinAlbum();
      await stopAlbum();
      for (var i = 1; i <= 4; i++) {
        transport.cancelFromOutside('t$i');
      }
      await manager.settled();

      await letEveryBackoffPass();

      expect(transport.started.length, 4);
      await expectNothingFailedOrWaiting();
    });

    test(
        "N-39: a failure that arrives late for a song the Stop cancelled is not a failed song with a wait, and deletes nothing",
        () async {
      await pinAlbum();
      await stopAlbum();
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

  group("Resume puts the stopped songs back", () {
    test(
        "N-39: exactly the songs that were not on the phone, in their old order, none twice; a song added to the list while it was stopped waits and then comes last",
        () async {
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
  });
}

/// A transport that notes what the database says at the moment each task is cancelled.
class _OrderProbe extends FakeDownloadTransport {
  _OrderProbe(this.db);

  final AppDatabase db;
  final List<int?> stoppedAtWhenCancelled = [];
  final List<int> stateWhenCancelled = [];

  @override
  Future<void> cancel(String taskId) async {
    stoppedAtWhenCancelled
        .add((await db.select(db.pins).get()).single.stoppedAtMs);
    final id = taskId.split(':').last;
    stateWhenCancelled.add((await (db.select(db.downloads)
              ..where((d) => d.trackId.equals(id)))
            .getSingle())
        .state);
    await super.cancel(taskId);
  }
}
