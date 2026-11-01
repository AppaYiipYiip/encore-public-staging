import 'package:drift/drift.dart' show Value;
import 'package:drift/native.dart';
import 'package:encore/core/clock.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/downloads/download_manager.dart';
import 'package:encore/data/downloads/download_planner.dart';
import 'package:encore/data/repos/downloads_repository.dart';
import 'package:encore/domain/audio_quality.dart';
import 'package:encore/domain/storage_guard.dart';
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

void main() {
  late AppDatabase db;
  late FakeClock clock;
  late DownloadsRepository repo;
  late FakeDownloadTransport transport;
  late DownloadManager manager;
  late FakeDiskSpace disk;
  late int serverId;
  var policy = const DownloadPolicy();

  setUp(() async {
    policy = const DownloadPolicy();
    db = AppDatabase(NativeDatabase.memory());
    clock = FakeClock(DateTime.utc(2026, 10, 15, 10));
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
    disk = FakeDiskSpace(100 * 1024 * 1024 * 1024);
    manager = DownloadManager(
      db: db,
      serverId: serverId,
      repository: repo,
      transport: transport,
      clock: clock,
      policy: () => policy,
      urlBuilder: _url,
      diskSpace: disk,
    );
    await manager.start();
  });

  tearDown(() async {
    await manager.dispose();
    await db.close();
  });

  Future<DownloadRow> row(String id) async => (await repo.rowsFor([id])).single;

  test('pinning an album starts its tracks at the pin quality', () async {
    await repo.pin(PinTargetType.album, 'al1', quality: AudioQuality.high);
    await manager.reconcile();

    expect(transport.started.length, 4);
    final req = transport.requestFor('t1');
    expect(req.url.queryParameters['q'], 'opus160');
    expect(req.relativePath, 'downloads/$serverId/t1.opus');
    expect(req.requiresWifi, isTrue);
    expect((await row('t1')).state, DownloadState.downloading);
  });

  test(
      'a pinned playlist that was empty downloads the song that is added to it later (Q1)',
      () async {
    await db.into(db.playlists).insert(PlaylistsCompanion.insert(
        serverId: serverId, id: 'plE', name: 'Blank'));
    await repo.pin(PinTargetType.playlist, 'plE');
    await manager.reconcile();
    expect(transport.started, isEmpty);

    await db.into(db.playlistEntries).insert(PlaylistEntriesCompanion.insert(
        serverId: serverId, playlistId: 'plE', position: 0, trackId: 't2'));
    await manager.reconcile();

    expect(transport.started.length, 1);
    expect((await row('t2')).state, DownloadState.downloading);
    final pin = await repo.watchPinState(PinTargetType.playlist, 'plE').first;
    expect(pin.total, 1);
  });

  test('original quality keeps the source extension', () async {
    await repo.pin(PinTargetType.album, 'al1');
    await manager.reconcile();
    expect(
        transport.requestFor('t2').relativePath, 'downloads/$serverId/t2.flac');
  });

  test('a finished transfer is recorded with size and audio key', () async {
    await repo.pin(PinTargetType.album, 'al1', quality: AudioQuality.high);
    await manager.reconcile();
    transport.complete('t1', size: 5000);
    await manager.settled();

    final r = await row('t1');
    expect(r.state, DownloadState.done);
    expect(r.bytes, 5000);
    expect(r.localPath, '/app/downloads/$serverId/t1.opus');
    expect(r.sourceAudioKey, 'key1');
    final pin = await repo.watchPinState(PinTargetType.album, 'al1').first;
    expect(pin.done, 1);
  });

  test('the in-flight budget is respected and refilled', () async {
    policy = const DownloadPolicy(maxInFlight: 2);
    await repo.pin(PinTargetType.album, 'al1');
    await manager.reconcile();
    expect(transport.started.length, 2);

    transport.complete('t1');
    await manager.settled();
    expect(transport.started.length, 3, reason: 'a slot freed up');
  });

  group('storage guard', () {
    const mb = 1024 * 1024;

    test('the cap pauses the queue (rows stay queued) until it is raised',
        () async {
      // Each file is estimated at 8 MiB; 20 MiB fits two.
      policy = const DownloadPolicy(limitBytes: 20 * mb);
      await repo.pin(PinTargetType.album, 'al1');
      await manager.reconcile();

      expect(transport.started.length, 2);
      expect(manager.verdict, StorageVerdict.limitReached);
      expect((await row('t3')).state, DownloadState.queued,
          reason: 'queued, not failed');

      policy = const DownloadPolicy(limitBytes: 100 * mb);
      await manager.reconcile();
      expect(transport.started.length, 4);
      expect(manager.verdict, StorageVerdict.ok);
    });

    test('finished downloads count against the cap', () async {
      policy = const DownloadPolicy(limitBytes: 30 * mb, maxInFlight: 1);
      await repo.pin(PinTargetType.album, 'al1');
      await manager.reconcile();
      expect(transport.started.length, 1);

      transport.complete('t1', size: 25 * mb);
      await manager.settled();

      // 25 MiB used + 8 MiB estimated > 30 MiB.
      expect(transport.started.length, 1);
      expect(manager.verdict, StorageVerdict.limitReached);
    });

    test('a nearly full phone stops downloads even without a cap', () async {
      disk.free = 1024 * mb + 4 * mb; // floor 1 GiB, next file ~8 MiB
      await repo.pin(PinTargetType.album, 'al1');
      await manager.reconcile();

      expect(transport.started, isEmpty);
      expect(manager.verdict, StorageVerdict.lowSpace);

      disk.free = 50 * 1024 * mb;
      await manager.reconcile();
      expect(transport.started.length, 4);
      expect(manager.verdict, StorageVerdict.ok);
    });

    test('unknown free space does not block', () async {
      disk.free = null;
      await repo.pin(PinTargetType.album, 'al1');
      await manager.reconcile();
      expect(transport.started.length, 4);
    });

    test('verdict changes are published', () async {
      final seen = <StorageVerdict>[];
      final sub = manager.verdicts.listen(seen.add);
      policy = const DownloadPolicy(limitBytes: 10 * mb);
      await repo.pin(PinTargetType.album, 'al1');
      await manager.reconcile();
      policy = const DownloadPolicy();
      await manager.reconcile();
      await pumpEventQueue();
      await sub.cancel();

      expect(seen, [StorageVerdict.limitReached, StorageVerdict.ok]);
    });
  });

  test('Wi-Fi only: nothing starts on mobile data, then it resumes', () async {
    policy = const DownloadPolicy(wifiOnly: true, onWifi: false);
    await repo.pin(PinTargetType.album, 'al1');
    await manager.reconcile();
    expect(transport.started, isEmpty);
    expect((await row('t1')).state, DownloadState.queued);

    policy = const DownloadPolicy(wifiOnly: true, onWifi: true);
    await manager.reconcile();
    expect(transport.started.length, 4);
  });

  test('a failure is recorded and retried only after the back-off', () async {
    await repo.pin(PinTargetType.album, 'al1');
    await manager.reconcile();
    transport.fail('t1', 'HTTP 503');
    await manager.settled();

    final r = await row('t1');
    expect(r.state, DownloadState.failed);
    expect(r.lastError, 'HTTP 503');
    expect(r.attempts, 1);

    await manager.reconcile();
    expect((await row('t1')).state, DownloadState.failed,
        reason: 'too soon to retry');

    clock.advance(const Duration(minutes: 11)); // 5 min * 2^1 = 10 min
    await manager.reconcile();
    expect((await row('t1')).state, DownloadState.downloading);
  });

  test('retryFailed requeues immediately', () async {
    await repo.pin(PinTargetType.album, 'al1');
    await manager.reconcile();
    transport.fail('t1');
    await manager.settled();
    await manager.retryFailed();
    expect((await row('t1')).state, DownloadState.downloading);
  });

  test('PB-40: unpinning with immediate removal deletes files and rows',
      () async {
    await repo.pin(PinTargetType.album, 'al1', quality: AudioQuality.high);
    await manager.reconcile();
    transport.complete('t1');
    await manager.settled();

    await repo.unpin(PinTargetType.album, 'al1');
    await manager.reconcile(immediateRemoval: true);

    expect(await repo.rowsFor(['t1', 't2', 't3', 't4']), isEmpty);
    expect(transport.deleted, contains('/app/downloads/$serverId/t1.opus'));
    expect(transport.canceled.length, greaterThanOrEqualTo(3),
        reason: 'unfinished transfers were cancelled');
  });

  test(
      'PB-40: a pin the person removed (a playlist deleted) takes its songs off the phone at once, not a day later (field test 2026-10-31: "x songs downloaded" after deleting a playlist)',
      () async {
    await db.into(db.playlists).insert(
        PlaylistsCompanion.insert(serverId: serverId, id: 'pl1', name: 'Mix'));
    await db.into(db.playlistEntries).insert(PlaylistEntriesCompanion.insert(
        serverId: serverId, playlistId: 'pl1', position: 0, trackId: 't1'));
    await repo.pin(PinTargetType.playlist, 'pl1', quality: AudioQuality.high);
    await manager.reconcile();
    transport.complete('t1');
    await manager.settled();

    // What deleting the playlist does to its pin: the pin goes, nothing asks the manager for an immediate removal.
    await repo.unpin(PinTargetType.playlist, 'pl1');
    await Future<void>.delayed(const Duration(milliseconds: 800));
    await manager.settled();

    expect(await repo.rowsFor(['t1']), isEmpty,
        reason:
            'the songs are not held for the grace period of a regenerated list');
    expect(transport.deleted, isNotEmpty);
  });

  test(
      'PB-40: a pin written again with nothing removed (a resume, a refreshed quality) does not end the grace period of songs that left a list',
      () async {
    await db.into(db.playlists).insert(
        PlaylistsCompanion.insert(serverId: serverId, id: 'pl1', name: 'Mix'));
    await db.into(db.playlistEntries).insert(PlaylistEntriesCompanion.insert(
        serverId: serverId, playlistId: 'pl1', position: 0, trackId: 't1'));
    await repo.pin(PinTargetType.playlist, 'pl1', quality: AudioQuality.high);
    await manager.reconcile();
    transport.complete('t1');
    await manager.settled();
    await db.delete(db.playlistEntries).go();
    await manager.reconcile();
    expect((await row('t1')).orphanedAtMs, isNotNull);

    await repo.pin(PinTargetType.playlist, 'pl1', quality: AudioQuality.high);
    await Future<void>.delayed(const Duration(milliseconds: 800));
    await manager.settled();

    expect(await repo.rowsFor(['t1']), isNotEmpty,
        reason: 'nobody removed anything: the day of grace goes on');
    expect(transport.deleted, isEmpty);
  });

  test(
      'PB-40: a song still wanted by another pin stays when one pin is removed',
      () async {
    await db.into(db.playlists).insert(
        PlaylistsCompanion.insert(serverId: serverId, id: 'pl1', name: 'Mix'));
    await db.into(db.playlistEntries).insert(PlaylistEntriesCompanion.insert(
        serverId: serverId, playlistId: 'pl1', position: 0, trackId: 't1'));
    await repo.pin(PinTargetType.playlist, 'pl1', quality: AudioQuality.high);
    await repo.pin(PinTargetType.album, 'al1', quality: AudioQuality.high);
    await manager.reconcile();
    transport.complete('t1');
    await manager.settled();

    await repo.unpin(PinTargetType.playlist, 'pl1');
    await Future<void>.delayed(const Duration(milliseconds: 800));
    await manager.settled();

    expect((await row('t1')).orphanedAtMs, isNull);
    expect(transport.deleted, isEmpty);
  });

  test('PB-40: server-side drop keeps the file for the grace period', () async {
    await db.into(db.playlists).insert(
        PlaylistsCompanion.insert(serverId: serverId, id: 'pl1', name: 'Mix'));
    await db.into(db.playlistEntries).insert(PlaylistEntriesCompanion.insert(
        serverId: serverId, playlistId: 'pl1', position: 0, trackId: 't1'));
    await repo.pin(PinTargetType.playlist, 'pl1', quality: AudioQuality.high);
    await manager.reconcile();
    transport.complete('t1');
    await manager.settled();

    // The playlist is regenerated without t1.
    await db.delete(db.playlistEntries).go();
    await manager.reconcile();
    expect((await row('t1')).orphanedAtMs, isNotNull);
    expect(transport.deleted, isEmpty);

    clock.advance(const Duration(hours: 25));
    await manager.reconcile();
    expect(await repo.rowsFor(['t1']), isEmpty);
    expect(transport.deleted, isNotEmpty);
  });

  test('a changed audio key refreshes the copy and swaps atomically', () async {
    await repo.pin(PinTargetType.album, 'al1', quality: AudioQuality.high);
    await manager.reconcile();
    transport.complete('t1');
    await manager.settled();
    final oldPath = (await row('t1')).localPath!;

    await (db.update(db.tracks)..where((t) => t.id.equals('t1')))
        .write(const TracksCompanion(audioKey: Value('key1-NEW')));
    await manager.reconcile();

    final req = transport.requestFor('t1');
    expect(req.relativePath, endsWith('.opus.new'));
    expect((await row('t1')).localPath, oldPath,
        reason: 'the old file is still the playable one');

    transport.complete('t1', size: 9000);
    await manager.settled();
    final r = await row('t1');
    expect(r.state, DownloadState.done);
    expect(r.sourceAudioKey, 'key1-NEW');
    expect(r.bytes, 9000);
    expect(transport.renamed.single.$1, endsWith('.opus.new'));
  });

  test('tasks that died with the app go back to the queue', () async {
    await repo.pin(PinTargetType.album, 'al1');
    await manager.reconcile();
    expect((await row('t1')).state, DownloadState.downloading);

    // New process: the transport remembers nothing.
    transport.active = {};
    final fresh = DownloadManager(
      db: db,
      serverId: serverId,
      repository: repo,
      transport: transport,
      clock: clock,
      policy: () => policy,
      urlBuilder: _url,
    );
    final before = transport.started.length;
    await fresh.start();
    await fresh.reconcile();
    expect(transport.started.length, greaterThan(before));
    expect(transport.resumeCalls, 2, reason: 'once per process start');
    await fresh.dispose();
  });

  test('an empty download is a failure, not a track', () async {
    await repo.pin(PinTargetType.album, 'al1');
    await manager.reconcile();
    transport.complete('t1', size: 10);
    await manager.settled();
    expect((await row('t1')).state, DownloadState.failed);
  });

  test('finishing after the pin was removed discards the file', () async {
    await repo.pin(PinTargetType.album, 'al1');
    await manager.reconcile();
    await repo.unpin(PinTargetType.album, 'al1');
    await manager.reconcile(immediateRemoval: true);
    transport.complete('t1');
    await manager.settled();
    expect(transport.deleted, contains('/app/downloads/$serverId/t1.flac'));
    expect(await repo.rowsFor(['t1']), isEmpty);
  });

  group('after the app was killed and restarted (B21)', () {
    DownloadManager restarted() => DownloadManager(
          db: db,
          serverId: serverId,
          repository: repo,
          transport: transport,
          clock: clock,
          policy: () => policy,
          urlBuilder: _url,
        );

    test('a download that finishes after a restart is still recognised',
        () async {
      await repo.pin(PinTargetType.album, 'al1'); // original quality: .flac
      await manager.reconcile();
      await manager.dispose(); // the process dies; the transfer carries on
      final fresh = restarted();
      await fresh.start();

      transport.complete('t2', size: 5000);
      await fresh.settled();

      final r = await row('t2');
      expect(r.state, DownloadState.done,
          reason: 'it was marked failed and downloaded again');
      expect(r.localPath, '/app/downloads/$serverId/t2.flac');
      await fresh.dispose();
    });

    test('a refreshed copy that finishes after a restart is swapped in',
        () async {
      await repo.pin(PinTargetType.album, 'al1', quality: AudioQuality.high);
      await manager.reconcile();
      transport.complete('t1');
      await manager.settled();
      final oldPath = (await row('t1')).localPath!;
      await (db.update(db.tracks)..where((t) => t.id.equals('t1')))
          .write(const TracksCompanion(audioKey: Value('key1-NEW')));
      await manager.reconcile();
      expect(transport.requestFor('t1').relativePath, endsWith('.opus.new'));
      await manager.dispose();
      final fresh = restarted();
      await fresh.start();

      transport.complete('t1', size: 9000);
      await fresh.settled();

      final r = await row('t1');
      expect(r.state, DownloadState.done);
      expect(r.localPath, oldPath);
      expect(r.bytes, 9000, reason: 'the new copy replaced the old one');
      expect(transport.renamed.single.$2, oldPath);
      await fresh.dispose();
    });

    test('a file that finishes after unpin and a restart is discarded',
        () async {
      await repo.pin(PinTargetType.album, 'al1');
      await manager.reconcile();
      await manager.dispose();
      await repo.unpin(PinTargetType.album, 'al1');
      final fresh = restarted();
      await fresh.start();
      await fresh.reconcile(immediateRemoval: true);

      transport.complete('t1');
      await fresh.settled();

      expect(transport.deleted, contains('/app/downloads/$serverId/t1.flac'),
          reason: 'otherwise the file stays on the phone for ever');
      await fresh.dispose();
    });
  });

  group('swapping in a refreshed copy (B22)', () {
    Future<String> startRefresh() async {
      await repo.pin(PinTargetType.album, 'al1', quality: AudioQuality.high);
      await manager.reconcile();
      transport.complete('t1');
      await manager.settled();
      final oldPath = (await row('t1')).localPath!;
      await (db.update(db.tracks)..where((t) => t.id.equals('t1')))
          .write(const TracksCompanion(audioKey: Value('key1-NEW')));
      await manager.reconcile();
      return oldPath;
    }

    test('the old copy is never deleted before the new one is in place',
        () async {
      final oldPath = await startRefresh();
      transport.complete('t1', size: 9000);
      await manager.settled();

      expect(transport.deleted, isNot(contains(oldPath)));
      expect((await row('t1')).bytes, 9000);
    });

    test('a swap that fails keeps the old copy and removes the new file',
        () async {
      final oldPath = await startRefresh();
      transport.failRename = true;
      transport.complete('t1', size: 9000);
      await manager.settled();

      final r = await row('t1');
      expect(r.state, DownloadState.done, reason: 'the old copy still plays');
      expect(r.localPath, oldPath);
      expect(r.bytes, 4096, reason: 'the row still describes the old file');
      expect(transport.files.containsKey(oldPath), isTrue);
      expect(transport.deleted, contains('$oldPath.new'));
      expect(r.sourceAudioKey, 'key1',
          reason: 'still the old key, so the refresh is tried again');
    });
  });

  group('is it really the song? (B23)', () {
    test('a truncated original is a failure and the bad file is removed',
        () async {
      await (db.update(db.tracks)..where((t) => t.id.equals('t3')))
          .write(const TracksCompanion(size: Value(9000000)));
      await repo.pin(PinTargetType.album, 'al1');
      await manager.reconcile();

      transport.complete('t3', size: 5000);
      await manager.settled();

      final r = await row('t3');
      expect(r.state, DownloadState.failed);
      expect(r.lastError, contains('incomplete'));
      expect(transport.deleted, contains('/app/downloads/$serverId/t3.flac'));
    });

    test('a web page saved as a song is a failure', () async {
      await repo.pin(PinTargetType.album, 'al1');
      await manager.reconcile();
      transport.heads['/app/downloads/$serverId/t4.flac'] =
          '<html><body>Please sign in'.codeUnits;

      transport.complete('t4', size: 5000);
      await manager.settled();

      final r = await row('t4');
      expect(r.state, DownloadState.failed);
      expect(r.lastError, contains('did not send audio'));
      expect(transport.deleted, contains('/app/downloads/$serverId/t4.flac'));
    });
  });
}
