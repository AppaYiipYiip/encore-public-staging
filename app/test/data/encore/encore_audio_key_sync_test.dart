// N-38 (review of #166 and #167): the migration to the server's key of a file's AUDIO, proved through the REAL pull of the Encore server's files and the
// sync's own end-of-sync stale marking, not through rows a test writes by hand. #166 was proved on rows written by hand and missed that `markStaleDownloads`, which
// every sync runs last, flagged every copy by plain inequality of the keys.
//
// Wired as the Encore branch of `SyncEngine` wires it: `EncoreSync.pullFiles()` (against the fake Encore server, which serves the refs as the real one does), then
// `LibraryWriter.markStaleDownloads`, then the download planner. (The engine itself is not run: the only harness that wires it with an Encore server is the whole
// `Session`, which is far heavier than the three steps this test needs; the three calls are the ones the engine makes in this order.)
import 'package:dio/dio.dart';
import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:drift/native.dart';
import 'package:encore/core/clock.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/downloads/download_planner.dart';
import 'package:encore/data/encore/encore_api.dart';
import 'package:encore/data/encore/encore_sync.dart';
import 'package:encore/data/repos/downloads_repository.dart';
import 'package:encore/data/sync/library_writer.dart';
import 'package:encore/domain/audio_quality.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_encore_server.dart';

const _served = 'a1:0123456789abcdef0123456789abcdef';

void main() {
  late AppDatabase db;
  late FakeEncoreServer server;
  late EncoreSync sync;
  late DownloadsRepository repo;
  late int serverId;
  late String ref;

  Map<String, Object?> meta({int size = 5000}) => {
        'albumId': 'al1',
        'size': size,
        'suffix': 'opus',
        'samplingRate': 48000,
        'bitDepth': 0,
      };

  setUp(() async {
    db = AppDatabase(NativeDatabase.memory());
    serverId = await db.into(db.servers).insert(ServersCompanion.insert(
        name: 'Test', username: 'tester', endpointsJson: '[]', createdAtMs: 0));
    server = FakeEncoreServer();
    sync = EncoreSync(
      db: db,
      api: EncoreApi(
        dio: Dio()..httpClientAdapter = server.adapter,
        baseUrl: () => Uri.parse('http://home.test:4540'),
        auth: () => {'u': 'tester', 't': 'tok', 's': 'salt'},
      ),
      serverId: serverId,
      ownerName: 'tester',
      clock: FakeClock(DateTime.utc(2026, 11, 27, 12)),
    );
    repo = DownloadsRepository(db, serverId,
        clock: FakeClock(DateTime.utc(2026, 11, 27, 12)));

    // A server from before keys: the song has a file and the phone pulls it.
    ref = server.addRef('Weird Fishes', 'Radiohead',
        album: 'In Rainbows', fileId: 'nd1', meta: meta());
    await sync.pullFiles();
    // The person downloaded the album: the copy's row carries what the phone computed then (the old formula).
    await repo.pin(PinTargetType.album, 'al1', quality: AudioQuality.high);
    final track = await (db.select(db.tracks)..where((t) => t.id.equals(ref)))
        .getSingle();
    await db.into(db.downloads).insert(DownloadsCompanion.insert(
          serverId: serverId,
          trackId: ref,
          state: const Value(DownloadState.done),
          localPath: const Value('/data/x.opus'),
          bytes: const Value(100),
          sourceAudioKey: Value(track.audioKey),
          sourceLegacyKey: Value(track.audioKey),
          quality: Value(AudioQuality.high.id),
          updatedAtMs: 1,
        ));
  });

  tearDown(() => db.close());

  /// What the engine does after the pull, then what the download manager plans.
  Future<DownloadPlan> afterTheSync() async {
    await sync.pullFiles();
    await LibraryWriter(db).markStaleDownloads(serverId: serverId, nowMs: 2000);
    final plan = planDownloads(
      desired: await repo.desired(),
      existing: await repo.existing(),
      nowMs: 3000,
    );
    await repo.applyPlan(plan, await repo.desired());
    return plan;
  }

  Future<DownloadRow> copy() async => (await repo.rowsFor([ref])).single;

  test('the phone starts with a copy made under the old key', () async {
    final c = await copy();
    expect(c.sourceAudioKey, isNotEmpty);
    expect(c.sourceAudioKey, isNot(startsWith('a1:')));
  });

  test(
      'the server starts serving the key of the audio: the copy is not flagged, nothing is fetched, the row takes the keys',
      () async {
    final before = await copy();
    server.attachFile(ref, 'nd1', meta: meta());
    (server.refs[ref]!['file']! as Map)['audioKey'] = _served;

    final plan = await afterTheSync();

    final c = await copy();
    expect(c.stale, isFalse,
        reason: 'the sync\'s own stale marking must not flag it');
    expect(plan.toRefresh, isEmpty);
    expect(c.state, DownloadState.done);
    expect(c.sourceAudioKey, _served);
    expect(c.sourceLegacyKey, before.sourceLegacyKey,
        reason: 'the file is as it was: the old-formula key did not move');
  });

  test(
      'then the server rewrites the tags (another size, the same key of the audio): nothing is queued and the row learns the new size\'s key',
      () async {
    server.attachFile(ref, 'nd1', meta: meta());
    (server.refs[ref]!['file']! as Map)['audioKey'] = _served;
    await afterTheSync();
    final first = await copy();

    server.attachFile(ref, 'nd1', meta: meta(size: 5321));
    (server.refs[ref]!['file']! as Map)['audioKey'] = _served;
    final plan = await afterTheSync();

    final c = await copy();
    expect(c.stale, isFalse);
    expect(plan.toRefresh, isEmpty);
    expect(c.sourceAudioKey, _served);
    expect(c.sourceLegacyKey, isNot(first.sourceLegacyKey),
        reason:
            'kept in step with the file as it is now, so a rollback to a server without keys still knows the copy');
  });

  test('a REAL change of the audio is still fetched again', () async {
    server.attachFile(ref, 'nd1', meta: meta());
    (server.refs[ref]!['file']! as Map)['audioKey'] = _served;
    await afterTheSync();

    server.attachFile(ref, 'nd1', meta: meta());
    (server.refs[ref]!['file']! as Map)['audioKey'] =
        'a1:ffffffffffffffffffffffffffffffff';
    final plan = await afterTheSync();

    expect(plan.toRefresh, [ref]);
  });

  test(
      'a server rolled back to one without keys, the same file: the copy stays',
      () async {
    server.attachFile(ref, 'nd1', meta: meta());
    (server.refs[ref]!['file']! as Map)['audioKey'] = _served;
    await afterTheSync();

    server.attachFile(ref, 'nd1', meta: meta()); // no audioKey any more
    final plan = await afterTheSync();

    expect((await copy()).stale, isFalse);
    expect(plan.toRefresh, isEmpty);
  });

  test(
      'the song is served from ANOTHER file without a key (a second file became the preferred one): the copy is fetched again',
      () async {
    server.attachFile(ref, 'nd1', meta: meta());
    (server.refs[ref]!['file']! as Map)['audioKey'] = _served;
    await afterTheSync();

    // A FLAC of the song the library link attached; another file id, size, suffix and rate, no key of its audio.
    server.attachFile(ref, 'nd2', meta: {
      'albumId': 'al1',
      'size': 31000,
      'suffix': 'flac',
      'samplingRate': 44100,
      'bitDepth': 16,
    });
    final plan = await afterTheSync();

    expect(plan.toRefresh, [ref],
        reason: 'before #166 the two size-based keys differed and it was');
  });

  test(
      'the file is gone from the server (the song has no key at all): the copy keeps playing, is not flagged and nothing is queued',
      () async {
    server.removeFile(ref);

    final plan = await afterTheSync();

    // A track with no file has no key to compare. The sync's stale marking used to flag the copy anyway (plain inequality, ''), and the planner then tried to refresh a
    // file the server no longer has; now it compares nothing, like the planner always did.
    expect((await copy()).stale, isFalse);
    expect(plan.toRefresh, isEmpty);
    expect((await copy()).state, DownloadState.done);
  });
}
