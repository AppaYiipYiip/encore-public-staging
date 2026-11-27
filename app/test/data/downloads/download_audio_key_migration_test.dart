// N-38 (docs/tasks/N-38-audio-only-key.md section 4): the server serves a key of a file's AUDIO (`file.audioKey`), and a downloaded copy that was made under the
// old key (which hashed the file's size) must NOT be downloaded again because the formula changed ("adopt by match"), while a tag rewrite after that (new size, same
// key) is invisible and a real change still refreshes the copy.
import 'package:drift/drift.dart' show Value;
import 'package:drift/native.dart';
import 'package:encore/core/clock.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/downloads/download_manager.dart';
import 'package:encore/data/downloads/download_planner.dart';
import 'package:encore/data/repos/downloads_repository.dart';
import 'package:encore/data/sync/fingerprint.dart';
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

String _oldKey({int size = 5000}) => legacyAudioKey(
      size: size,
      suffix: 'flac',
      bitRate: 900,
      durationSec: 200,
      samplingRate: 44100,
      bitDepth: 16,
    );

const _served = 'a1:0123456789abcdef0123456789abcdef';

void main() {
  late AppDatabase db;
  late DownloadsRepository repo;
  late FakeDownloadTransport transport;
  late DownloadManager manager;
  late int serverId;

  setUp(() async {
    db = AppDatabase(NativeDatabase.memory());
    final clock = FakeClock(DateTime.utc(2026, 11, 27, 10));
    serverId = await db.into(db.servers).insert(ServersCompanion.insert(
        name: 'T', username: 'u', endpointsJson: '[]', createdAtMs: 0));
    // A song of an Encore server as the phone stored it BEFORE the server served keys: its audio key is the old formula's.
    await db.into(db.tracks).insert(TracksCompanion.insert(
          serverId: serverId,
          id: 't1',
          title: 'Song 1',
          albumId: const Value('al1'),
          size: const Value(5000),
          suffix: const Value('flac'),
          bitRate: const Value(900),
          durationSec: const Value(200),
          samplingRate: const Value(44100),
          bitDepth: const Value(16),
          audioKey: Value(_oldKey()),
        ));
    repo = DownloadsRepository(db, serverId, clock: clock);
    transport = FakeDownloadTransport();
    manager = DownloadManager(
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
    await repo.pin(PinTargetType.album, 'al1', quality: AudioQuality.high);
    await manager.reconcile();
    transport.complete('t1');
    await manager.settled();
  });

  tearDown(() async {
    await manager.dispose();
    await db.close();
  });

  Future<DownloadRow> row() async => (await repo.rowsFor(['t1'])).single;

  Future<void> sync(TracksCompanion change) async {
    await (db.update(db.tracks)..where((t) => t.id.equals('t1'))).write(change);
    await manager.reconcile();
    await manager.settled();
  }

  test('the copy was made under the old key', () async {
    final r = await row();
    expect(r.state, DownloadState.done);
    expect(r.sourceAudioKey, _oldKey());
  });

  test(
      'the server starts serving keys: the copy stays, its row takes the key, nothing is fetched',
      () async {
    final before = await row();

    await sync(const TracksCompanion(audioKey: Value(_served)));

    final r = await row();
    expect(r.state, DownloadState.done, reason: 'no refresh was started');
    expect(r.sourceAudioKey, _served, reason: 'adopted in place');
    expect(r.localPath, before.localPath);
    expect(r.bytes, before.bytes);
    expect(transport.renamed, isEmpty);
  });

  test(
      'after the key is adopted a tag rewrite (another size, the same key) is invisible',
      () async {
    await sync(const TracksCompanion(audioKey: Value(_served)));

    // The server rewrote the tags of the file: the music server reports another size, the key of the audio is the same.
    await sync(const TracksCompanion(size: Value(5321)));

    final r = await row();
    expect(r.state, DownloadState.done);
    expect(r.sourceAudioKey, _served);
    expect(r.attempts, 0);
    expect(transport.renamed, isEmpty);
  });

  test('after the key is adopted a REAL change of the sound refreshes the copy',
      () async {
    await sync(const TracksCompanion(audioKey: Value(_served)));

    await sync(const TracksCompanion(
        audioKey: Value('a1:ffffffffffffffffffffffffffffffff')));

    final refresh = transport.requestFor('t1');
    expect(refresh.relativePath, endsWith('.opus.new'));
    transport.complete('t1', size: 9000);
    await manager.settled();
    expect((await row()).sourceAudioKey, 'a1:ffffffffffffffffffffffffffffffff');
  });

  test(
      'a file that changed BEFORE the key arrived (its size is not the one the copy was made at) is refreshed',
      () async {
    // The server retagged the file while this phone was away, and the key arrives in the same sync: the old-formula key no longer matches the copy's.
    await sync(
        const TracksCompanion(size: Value(5321), audioKey: Value(_served)));

    final refresh = transport.requestFor('t1');
    expect(refresh.relativePath, endsWith('.opus.new'),
        reason:
            'nothing can say the copy is still the same sound: the residue of the migration, one fetch');
  });

  test(
      'a server that stops serving keys for the file does not make the copy stale',
      () async {
    await sync(const TracksCompanion(audioKey: Value(_served)));

    // A server downgrade, or a file it cannot read now: the phone computes the old-formula key again.
    await sync(TracksCompanion(audioKey: Value(_oldKey())));

    final r = await row();
    expect(r.state, DownloadState.done);
    expect(r.sourceAudioKey, _served,
        reason: 'a key from a way that cannot be computed now says nothing');
    expect(transport.renamed, isEmpty);
  });
}
