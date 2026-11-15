import 'dart:convert';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:drift/native.dart';
import 'package:encore/core/clock.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/downloads/download_planner.dart';
import 'package:encore/data/encore/encore_api.dart';
import 'package:encore/data/encore/encore_models.dart';
import 'package:encore/data/encore/encore_sync.dart';
import 'package:encore/data/sync/sync_state_store.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_encore_server.dart';

/// N-27 slice 2b, the phone's half (docs/17 "Songs that are gone", the notes of N-27 "slices 2c, 2b, 2e, 2d as ONE design"): the server retires the song
/// refs nobody points at and tells a phone which ids are gone, through its own cursor (`goneSince`). A phone that was away must drop the rows it holds for
/// them, and ONLY those nobody points at: a like, a place in a playlist or a download keeps its row. The phone's rule is the existing `dropUnused`, applied
/// to an exact signal instead of a guess about age.
String _ref(String c) => 'sr_${c * 26}';

void main() {
  late AppDatabase db;
  late FakeEncoreServer server;
  late EncoreSync sync;
  late SyncStateStore state;
  late int serverId;

  Future<void> start({int pageLimit = 3}) async {
    db = AppDatabase(NativeDatabase.memory());
    serverId = await db.into(db.servers).insert(ServersCompanion.insert(
          name: 'Test',
          username: 'tester',
          endpointsJson: '[]',
          createdAtMs: 0,
        ));
    server = FakeEncoreServer();
    state = SyncStateStore(db, serverId);
    sync = EncoreSync(
      db: db,
      api: EncoreApi(
        dio: Dio()..httpClientAdapter = server.adapter,
        baseUrl: () => Uri.parse('http://home.test:4540'),
        auth: () => {'u': 'tester', 't': 'tok', 's': 'salt'},
      ),
      serverId: serverId,
      ownerName: 'tester',
      clock: FakeClock(DateTime.utc(2026, 11, 15, 12)),
      pageLimit: pageLimit,
    );
  }

  setUp(() => start());
  tearDown(() => db.close());

  // ------------------------------------------------------------------ what a test arranges

  /// A row of the phone's library for a song the server made a ref for: what a tap on a song it could not find leaves behind (`is_ref`, a file link
  /// only when [fileId] is given).
  Future<void> row(String id,
          {String? fileId, int? starredAtMs, bool isRef = true}) =>
      db.into(db.tracks).insert(TracksCompanion.insert(
            serverId: serverId,
            id: id,
            title: 'Song $id',
            isRef: Value(isRef),
            fileId: Value(fileId),
            starredAtMs: Value(starredAtMs),
          ));

  Future<void> inPlaylist(String playlist, String trackId) async {
    await db
        .into(db.playlists)
        .insertOnConflictUpdate(PlaylistsCompanion.insert(
          serverId: serverId,
          id: playlist,
          name: 'List $playlist',
        ));
    await db.into(db.playlistEntries).insert(PlaylistEntriesCompanion.insert(
          serverId: serverId,
          playlistId: playlist,
          position: 1,
          trackId: trackId,
          entryId: Value('pe_$playlist'),
        ));
  }

  Future<void> download(String id) =>
      db.into(db.downloads).insert(DownloadsCompanion.insert(
            serverId: serverId,
            trackId: id,
            state: const Value(DownloadState.done),
            localPath: const Value('/phone/downloads/song.opus'),
            bytes: const Value(1234),
            updatedAtMs: 1,
          ));

  /// The person asked to keep a song on the phone (a pin on the track) before any download of it exists: offline, or the download was removed.
  Future<void> pin(String id) => db.into(db.pins).insert(PinsCompanion.insert(
        serverId: serverId,
        targetType: 'track',
        targetId: id,
        createdAtMs: 1,
      ));

  Future<TrackRow?> track(String id) => (db.select(db.tracks)
        ..where((t) => t.serverId.equals(serverId) & t.id.equals(id)))
      .getSingleOrNull();

  Future<DownloadRow?> dl(String id) => (db.select(db.downloads)
        ..where((d) => d.serverId.equals(serverId) & d.trackId.equals(id)))
      .getSingleOrNull();

  Future<bool> live(String id) async => (await track(id))?.deletedAtMs == null;

  // ------------------------------------------------------------------ the contract

  group('the server\'s answer (the real response the server test saved)', () {
    Map<String, dynamic> fixture() =>
        (jsonDecode(File('test/fixtures/server/library-files-with-gone.json')
                .readAsStringSync()) as Map)
            .cast<String, dynamic>();

    test(
        'the parser reads the gone ids, their cursor and whether there are more, from the file the server wrote',
        () {
      final files = EncoreFiles.fromJson(fixture());

      expect(files.gone.map((g) => (g.seq, g.id)), [
        (1, 'sr_00000000000000000000000001'),
        (2, 'sr_00000000000000000000000002'),
      ]);
      expect(files.goneCursor, '2');
      expect(files.goneMore, isFalse);
    });

    test(
        'an answer without tombstones (a server from before them) reads as none, and no cursor to keep',
        () {
      final old = fixture()
        ..remove('gone')
        ..remove('goneCursor')
        ..remove('goneMore');

      final files = EncoreFiles.fromJson(old);

      expect(files.gone, isEmpty);
      expect(files.goneCursor, isNull);
      expect(files.goneMore, isFalse);
    });

    test(
        'an entry that names no song is skipped (one odd entry never stops a sync); the rest are in order of seq',
        () {
      final files = EncoreFiles.fromJson({
        'refs': const <Object?>[],
        'cursor': '0',
        'more': false,
        'gone': [
          {'id': 'b', 'seq': 2},
          {'id': 'a', 'seq': 1},
          {'seq': 3},
          {'id': '', 'seq': 4},
          'what',
        ],
        'goneCursor': '2',
        'goneMore': true,
      });

      expect(files.gone.map((g) => g.id), ['a', 'b']);
      expect(files.goneMore, isTrue);
    });
  });

  // ------------------------------------------------------------------ what the phone does with a gone id

  group('a song the server says is gone', () {
    test(
        'a row that nothing of the person points at is dropped (what a tap on a song the server could not find leaves behind)',
        () async {
      await row(_ref('a'));
      server.retire(_ref('a'));

      await sync.pullFiles();

      expect(await live(_ref('a')), isFalse);
    });

    test(
        'a row the person liked stays, and its link to a file of the server is cleared (that file is gone)',
        () async {
      await row(_ref('a'), fileId: 'nd-a', starredAtMs: 5);
      server.retire(_ref('a'));

      await sync.pullFiles();

      expect(await live(_ref('a')), isTrue);
      expect((await track(_ref('a')))!.fileId, isNull);
    });

    test('a row in a playlist stays', () async {
      await row(_ref('a'), fileId: 'nd-a');
      await inPlaylist('pl_1', _ref('a'));
      server.retire(_ref('a'));

      await sync.pullFiles();

      expect(await live(_ref('a')), isTrue);
    });

    test(
        'a DOWNLOADED song whose file on the server is gone keeps its row and its download exactly as they were, and is still found by the same keys: it plays offline',
        () async {
      await row(_ref('a'), fileId: 'nd-a');
      await download(_ref('a'));
      final before = await dl(_ref('a'));
      server.retire(_ref('a'));

      await sync.pullFiles();

      expect(await live(_ref('a')), isTrue, reason: 'the downloads guard');
      expect((await track(_ref('a')))!.fileId, isNull);
      final after = await dl(_ref('a'));
      expect(after, isNotNull,
          reason: 'found by (server, track id), as before');
      expect(after!.state, before!.state);
      expect(after.localPath, before.localPath);
      expect(after.bytes, before.bytes);
      expect(after.updatedAtMs, before.updatedAtMs,
          reason: 'nothing of the download was written');
    });

    test(
        'a song the person PINNED to keep, with no download made yet, keeps its row: they asked for it',
        () async {
      await row(_ref('a'), fileId: 'nd-a');
      await pin(_ref('a'));
      server.retire(_ref('a'));

      await sync.pullFiles();

      expect(await live(_ref('a')), isTrue);
      expect((await track(_ref('a')))!.fileId, isNull);
    });

    test(
        'a row of a plain music server (not a ref) is never touched, even if an id looks the same',
        () async {
      await row(_ref('a'), fileId: 'nd-a', isRef: false);
      server.retire(_ref('a'));

      await sync.pullFiles();

      expect(await live(_ref('a')), isTrue);
      expect((await track(_ref('a')))!.fileId, 'nd-a');
    });

    test('an id the phone never had changes nothing and stops nothing',
        () async {
      await row(_ref('b'));
      server.retire(_ref('z'));

      final stats = (await sync.pullFiles()).getOrThrow();

      expect(await live(_ref('b')), isTrue);
      expect(stats, isNotNull);
    });
  });

  // ------------------------------------------------------------------ the pull

  group('the pull', () {
    test(
        'asks from its own cursor (never `since`), and keeps the cursor the server answered',
        () async {
      await row(_ref('a'));
      server.retire(_ref('a'));

      await sync.pullFiles();
      await sync.pullFiles();

      expect(server.goneSinceSeen, ['0', '1'],
          reason: 'the second pull asks from where the first read to');
      expect(await state.get(EncoreSync.goneCursor), '1');
    });

    test(
        'pages while the server says there are more: seven tombstones at three a page are all applied',
        () async {
      for (var i = 0; i < 7; i++) {
        final id = _ref('abcdefg'[i]);
        await row(id);
        server.retire(id);
      }

      await sync.pullFiles();

      for (var i = 0; i < 7; i++) {
        expect(await live(_ref('abcdefg'[i])), isFalse, reason: 'row $i');
      }
      expect(await state.get(EncoreSync.goneCursor), '7');
    });

    test(
        'MORE THAN 500 tombstones: a phone with two pages at the server\'s own page size reads both',
        () async {
      await db.close();
      await start(pageLimit: 500);
      const total = 501;
      for (var i = 0; i < total; i++) {
        final id = 'sr_${i.toString().padLeft(26, '0')}';
        if (i == 0 || i == total - 1) await row(id);
        server.retire(id);
      }

      await sync.pullFiles();

      expect(await live('sr_${'0'.padLeft(26, '0')}'), isFalse,
          reason: 'on the first page');
      expect(
          await live('sr_${(total - 1).toString().padLeft(26, '0')}'), isFalse,
          reason: 'on the second page: the loop kept going on goneMore');
      expect(await state.get(EncoreSync.goneCursor), '$total');
    });

    test(
        'a server from before tombstones answers without a cursor: the phone keeps its own and drops nothing',
        () async {
      server.hasGone = false;
      await row(_ref('a'));
      server.retire(_ref('a'));
      await state.set(EncoreSync.goneCursor, '9');

      await sync.pullFiles();

      expect(await state.get(EncoreSync.goneCursor), '9');
      expect(await live(_ref('a')), isTrue);
    });

    test('forgetting where the feeds were forgets the gone cursor too',
        () async {
      await row(_ref('a'));
      server.retire(_ref('a'));
      await sync.pullFiles();
      expect(await state.get(EncoreSync.goneCursor), '1');

      await sync.reset();

      expect(await state.get(EncoreSync.goneCursor), isNull);
    });
  });
}
