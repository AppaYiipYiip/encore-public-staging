import 'dart:convert';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:drift/native.dart';
import 'package:encore/core/clock.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/downloads/download_planner.dart';
import 'package:encore/data/encore/encore_api.dart';
import 'package:encore/data/encore/encore_sync.dart';
import 'package:encore/data/repos/library_repository.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_encore_server.dart';

/// P2-25 slice 4 (docs/34 CF-47), the phone's half of the rehome: the server re-pointed the files that the old text fold had glued onto one song to the songs
/// they belong to. The phone is told through the files feed it already reads, with NO new feed: `files_since` returns the CURRENT state of every ref whose file
/// changed, so the old song comes back with the file it kept and the new songs come back whole. This proves the phone's reading of such a page, on the REAL
/// responses the server's own test saved (`library-files-before-split.json`, what a phone that synced before the split holds, and `library-files-after-split.json`,
/// what the same feed answers after it; written by `server/encore_server/tests/test_rehome.py`, which fails when the answer changes).
///
/// The story: five Arabic and Russian files hung on ONE song, `sr_...01` ("كيفك إنت", whose preferred file was the Russian `nd-5`). So before the split the Arabic
/// album's song list is empty and the Russian song sits under the wrong album (the symptom the owner saw: "1 song", and it was the Russian one). After it, the old
/// song names the file it kept and four new songs arrive, each with its own file.
const _old = 'sr_00000000000000000000000001';
const _fishes = 'sr_00000000000000000000000002';
const _arabicAlbum = 'al-كيفك إنت';
const _russianAlbum = 'al-Группа крови';

void main() {
  late AppDatabase db;
  late FakeEncoreServer server;
  late EncoreSync sync;
  late int serverId;

  setUp(() async {
    db = AppDatabase(NativeDatabase.memory());
    serverId = await db.into(db.servers).insert(ServersCompanion.insert(
          name: 'Test',
          username: 'tester',
          endpointsJson: '[]',
          createdAtMs: 0,
        ));
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
      clock: FakeClock(DateTime.utc(2026, 11, 17, 12)),
      pageLimit: 500,
    );
  });
  tearDown(() => db.close());

  // ------------------------------------------------------------------ what a test arranges

  Map<String, Object?> saved(String name) =>
      (jsonDecode(File('test/fixtures/server/$name').readAsStringSync()) as Map)
          .cast<String, Object?>();

  Future<void> pullThe(String name) async {
    server.filesAnswer = saved(name);
    (await sync.pull()).getOrThrow();
  }

  Future<TrackRow> track(String id) => (db.select(db.tracks)
        ..where((t) => t.serverId.equals(serverId) & t.id.equals(id)))
      .getSingle();

  /// The song list of the album page: `AlbumScreen` reads `albumTracksProvider`, which is `LibraryRepository.watchAlbumTracks`, the query used here. (The album's own
  /// row, its name and count, comes from the music server's album list, which this feed does not carry, so it is not what this proves.)
  Future<List<String>> album(String albumId) async => [
        for (final t in await LibraryRepository(db, serverId)
            .watchAlbumTracks(albumId)
            .first)
          t.title
      ];

  Future<int> liveRows() async => (await (db.select(db.tracks)
            ..where(
                (t) => t.serverId.equals(serverId) & t.deletedAtMs.isNull()))
          .get())
      .length;

  /// What a person has on the old song, as a phone that synced before the split holds it: a like, a place in a playlist, a play and a download of its file.
  Future<void> ownThe(String id) async {
    await (db.update(db.tracks)
          ..where((t) => t.serverId.equals(serverId) & t.id.equals(id)))
        .write(const TracksCompanion(starredAtMs: Value(777)));
    await db
        .into(db.playlists)
        .insertOnConflictUpdate(PlaylistsCompanion.insert(
          serverId: serverId,
          id: 'pl_aaaaaaaaaaaaaaaaaaaaaaaaaa',
          name: 'Mine',
        ));
    await db.into(db.playlistEntries).insert(PlaylistEntriesCompanion.insert(
          serverId: serverId,
          playlistId: 'pl_aaaaaaaaaaaaaaaaaaaaaaaaaa',
          position: 0,
          trackId: id,
          entryId: const Value('pe_aaaaaaaaaaaaaaaaaaaaaaaaaa'),
        ));
    await db.into(db.playHistory).insert(PlayHistoryCompanion.insert(
          serverId: serverId,
          trackId: id,
          playedAtMs: 5,
        ));
    await db.into(db.downloads).insert(DownloadsCompanion.insert(
          serverId: serverId,
          trackId: id,
          state: const Value(DownloadState.done),
          localPath: const Value('/phone/downloads/old.opus'),
          bytes: const Value(5000),
          sourceAudioKey: Value((await track(id)).audioKey),
          updatedAtMs: 1,
        ));
  }

  Future<DownloadRow> download(String id) => (db.select(db.downloads)
        ..where((d) => d.serverId.equals(serverId) & d.trackId.equals(id)))
      .getSingle();

  // ------------------------------------------------------------------ before: the symptom

  test(
      "BEFORE the split the song list of the Arabic album is empty and the old song sits under the Russian album (what the owner saw)",
      () async {
    await pullThe('library-files-before-split.json');

    expect(await album(_arabicAlbum), isEmpty);
    expect(await album(_russianAlbum), ['كيفك إنت'],
        reason: 'its preferred file is the Russian one: 1 song, the wrong one');
  });

  // ------------------------------------------------------------------ after: the split page

  test(
      "after the split the song list of the Arabic album has every one of its songs and the Russian album its two",
      () async {
    await pullThe('library-files-before-split.json');
    await pullThe('library-files-after-split.json');

    expect(await album(_arabicAlbum),
        unorderedEquals(['كيفك إنت', 'نسّم علينا الهوا', 'حبيتك بالصيف']));
    expect(await album(_russianAlbum),
        unorderedEquals(['Группа крови', 'Кукушка']));
    expect(await album('al-In Rainbows'),
        unorderedEquals(['Weird Fishes', 'Reckoner']),
        reason: 'a library that was never damaged is read as before');
  });

  test(
      "the new songs are inserted, the old song keeps its id and its first title and names the file it kept, and no row is dropped",
      () async {
    await pullThe('library-files-before-split.json');
    final before = await track(_old);
    final rowsBefore = await liveRows();
    expect(rowsBefore, 3);

    await pullThe('library-files-after-split.json');

    final after = await track(_old);
    expect(after.title, before.title);
    expect(before.fileId, 'nd-5');
    expect(after.fileId, 'nd-1', reason: 'the file the ref kept');
    expect(after.albumId, _arabicAlbum);
    expect(await liveRows(), rowsBefore + 4,
        reason: 'four songs arrived; none was dropped');
    for (final nd in ['nd-2', 'nd-3', 'nd-4', 'nd-5']) {
      final rows = await (db.select(db.tracks)
            ..where((t) => t.serverId.equals(serverId) & t.fileId.equals(nd)))
          .get();
      expect(rows.map((r) => r.id), isNot(contains(_old)));
      expect(rows, hasLength(1), reason: '$nd hangs on exactly one song');
    }
    expect((await track(_fishes)).fileId, 'nd-6');
  });

  test(
      "nothing the person has moves: the like, the place in a playlist, the play and the download stay on the old song",
      () async {
    await pullThe('library-files-before-split.json');
    await ownThe(_old);
    final dl = await download(_old);

    await pullThe('library-files-after-split.json');

    expect((await track(_old)).starredAtMs, 777);
    final entries = await db.select(db.playlistEntries).get();
    expect(entries.map((e) => e.trackId), [_old]);
    final plays = await db.select(db.playHistory).get();
    expect(plays.map((p) => p.trackId), [_old]);
    final now = await download(_old);
    expect(now.state, dl.state);
    expect(now.localPath, dl.localPath);
    expect(now.bytes, dl.bytes);
    for (final id in [
      'sr_00000000000000000000000100',
      'sr_00000000000000000000000101'
    ]) {
      expect((await track(id)).starredAtMs, isNull,
          reason: 'a new song is nobody\'s like');
    }
  });

  test(
      "the download of the old song is STALE by the key it already has: the phone fetches the file the song has now, and the new songs have none",
      () async {
    await pullThe('library-files-before-split.json');
    await ownThe(_old);
    final keyBefore = (await track(_old)).audioKey;
    expect(keyBefore, isNotEmpty);

    // Control: nothing changed on the server, the same copy is not touched.
    final same = planDownloads(
      desired: {
        _old: DesiredDownload(
            trackId: _old, quality: 'original', audioKey: keyBefore)
      },
      existing: {_old: await download(_old)},
      nowMs: 100000000000,
    );
    expect(same.toRefresh, isEmpty);

    await pullThe('library-files-after-split.json');

    final keyAfter = (await track(_old)).audioKey;
    expect(keyAfter, isNot(keyBefore));
    expect((await download(_old)).sourceAudioKey, keyBefore,
        reason: 'the copy on the phone is of the OLD file');
    final plan = planDownloads(
      desired: {
        _old: DesiredDownload(
            trackId: _old, quality: 'original', audioKey: keyAfter)
      },
      existing: {_old: await download(_old)},
      nowMs: 100000000000,
    );
    expect(plan.toRefresh, [_old]);
    expect(plan.toQueue, isEmpty);
    expect(plan.toDelete, isEmpty);
  });

  test(
      "the saved page tells the phone nothing in reverse: no merge, no gone id, no new feed",
      () {
    final page = saved('library-files-after-split.json');
    expect(page['merges'], isEmpty);
    expect(page['gone'], isEmpty);
    expect((page['refs'] as List), hasLength(5));
  });
}
