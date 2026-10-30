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

/// A song pinned before the server has it (D-21: Download on a catalogue release) is WAITING, not failed: the server is still getting it.
/// It must not use up the slots of songs that are ready, and it starts by itself once the server has it.
void main() {
  late AppDatabase db;
  late DownloadsRepository repo;
  late FakeDownloadTransport transport;
  late DownloadManager manager;
  late int serverId;
  late Set<String> serverHas;
  Object? otherError;
  var policy = const DownloadPolicy();

  Future<Uri> url(
    String id, {
    AudioQuality quality = AudioQuality.original,
    String? sourceSuffix,
    int? sourceBitRate,
  }) async {
    if (otherError != null) throw otherError!;
    if (!serverHas.contains(id)) throw const SongNotKeptYet();
    return Uri.parse('https://srv/get?id=$id');
  }

  setUp(() async {
    policy = const DownloadPolicy();
    otherError = null;
    serverHas = {};
    db = AppDatabase(NativeDatabase.memory());
    final clock = FakeClock(DateTime.utc(2026, 10, 30, 10));
    serverId = await db.into(db.servers).insert(ServersCompanion.insert(
        name: 'T', username: 'u', endpointsJson: '[]', createdAtMs: 0));
    for (var i = 1; i <= 4; i++) {
      await db.into(db.tracks).insert(TracksCompanion.insert(
            serverId: serverId,
            id: 't$i',
            title: 'Song $i',
            suffix: const Value('opus'),
          ));
    }
    repo = DownloadsRepository(db, serverId, clock: clock);
    transport = FakeDownloadTransport();
    manager = DownloadManager(
      db: db,
      serverId: serverId,
      repository: repo,
      transport: transport,
      clock: clock,
      policy: () => policy,
      urlBuilder: url,
      diskSpace: FakeDiskSpace(100 * 1024 * 1024 * 1024),
    );
    await manager.start();
  });

  tearDown(() async {
    await manager.dispose();
    await db.close();
  });

  Future<DownloadRow> row(String id) async => (await repo.rowsFor([id])).single;

  test(
      'PB-35: a song the server does not keep yet waits: not failed, not started, still queued',
      () async {
    await repo.pin(PinTargetType.track, 't1', quality: AudioQuality.high);

    await manager.reconcile();

    expect((await row('t1')).state, DownloadState.queued);
    expect(transport.started, isEmpty);
  });

  test(
      'PB-35: songs that wait do not use up the slots: the ready ones behind them still start',
      () async {
    policy = const DownloadPolicy(maxInFlight: 2);
    serverHas = {'t3', 't4'};
    for (final id in ['t1', 't2', 't3', 't4']) {
      await repo.pin(PinTargetType.track, id, quality: AudioQuality.high);
    }

    await manager.reconcile();

    expect(transport.started.length, 2);
    expect((await row('t3')).state, DownloadState.downloading);
    expect((await row('t4')).state, DownloadState.downloading);
    expect((await row('t1')).state, DownloadState.queued);
    expect((await row('t2')).state, DownloadState.queued);
  });

  test('PB-35: once the server has the song the next pass starts it by itself',
      () async {
    await repo.pin(PinTargetType.track, 't1', quality: AudioQuality.high);
    await manager.reconcile();
    expect(transport.started, isEmpty);

    serverHas = {'t1'}; // the library feed delivered its file
    await manager.reconcile();

    expect((await row('t1')).state, DownloadState.downloading);
    expect(transport.started.length, 1);
  });

  test('a real failure still fails, with its reason', () async {
    otherError = StateError('disk exploded');
    await repo.pin(PinTargetType.track, 't1', quality: AudioQuality.high);

    await manager.reconcile();

    final r = await row('t1');
    expect(r.state, DownloadState.failed);
    expect(r.lastError, contains('disk exploded'));
  });
}
