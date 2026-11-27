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
import 'package:encore/data/sync/library_writer.dart';
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

  /// What a sync does to a song and its copy: the new description is written, THEN the sync's own stale marking runs (`LibraryWriter.markStaleDownloads`), THEN the
  /// download manager reconciles. The marking decides by the same verdict as the planner: a key that merely differs must not flag the copy.
  Future<void> sync(TracksCompanion change) async {
    await (db.update(db.tracks)..where((t) => t.id.equals('t1'))).write(change);
    await LibraryWriter(db).markStaleDownloads(serverId: serverId, nowMs: 1000);
    await manager.reconcile();
    await manager.settled();
  }

  test('the copy was made under the old key', () async {
    final r = await row();
    expect(r.state, DownloadState.done);
    expect(r.sourceAudioKey, _oldKey());
    expect(r.sourceLegacyKey, _oldKey(),
        reason:
            'a download made now remembers the old-formula key of its file');
  });

  test(
      'the server starts serving keys: the copy stays, its row takes the key, nothing is fetched',
      () async {
    final before = await row();

    await sync(const TracksCompanion(audioKey: Value(_served)));

    final r = await row();
    expect(r.state, DownloadState.done, reason: 'no refresh was started');
    expect(r.sourceAudioKey, _served, reason: 'adopted in place');
    expect(r.stale, isFalse,
        reason: 'the sync\'s own stale marking did not flag it either');
    expect(r.sourceLegacyKey, _oldKey());
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
      'a server rolled back to one without keys (the same file) does not make the copy stale',
      () async {
    await sync(const TracksCompanion(audioKey: Value(_served)));

    await sync(TracksCompanion(audioKey: Value(_oldKey())));

    final r = await row();
    expect(r.state, DownloadState.done);
    expect(r.stale, isFalse);
    expect(r.sourceAudioKey, _served,
        reason: 'a key from a way that cannot be computed now says nothing');
    expect(transport.renamed, isEmpty);
  });

  test(
      'a rollback AFTER the server rewrote the tags: still the same copy (the row learned the new size when the key was equal)',
      () async {
    await sync(const TracksCompanion(audioKey: Value(_served)));
    await sync(const TracksCompanion(size: Value(5321))); // the retag

    await sync(
        TracksCompanion(audioKey: Value(_oldKey(size: 5321)))); // rollback

    final r = await row();
    expect(r.state, DownloadState.done);
    expect(r.stale, isFalse);
    expect(transport.renamed, isEmpty);
    expect(r.sourceLegacyKey, _oldKey(size: 5321));
  });

  test(
      'the song is later served from ANOTHER file with no key (a second file of the song became the preferred one): the copy is fetched again',
      () async {
    await sync(const TracksCompanion(audioKey: Value(_served)));

    // A FLAC the library link attached to the same song became its preferred file: another size, another duration, no key of its audio.
    await sync(TracksCompanion(
        size: const Value(31000),
        suffix: const Value('flac'),
        bitRate: const Value(1011),
        audioKey: Value(legacyAudioKey(
          size: 31000,
          suffix: 'flac',
          bitRate: 1011,
          durationSec: 200,
          samplingRate: 44100,
          bitDepth: 16,
        ))));

    final refresh = transport.requestFor('t1');
    expect(refresh.relativePath, endsWith('.opus.new'),
        reason:
            'before this change the two legacy keys differed and the copy was refreshed; it still is');
  });
}
