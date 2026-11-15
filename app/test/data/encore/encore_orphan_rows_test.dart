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
import 'package:encore/data/sync/sync_state_store.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_encore_server.dart';
import '../../support/fake_http.dart';

/// N-35 (docs/34 CF-46), the phone's half of N-31: a phone that was away while the server purged the removed entries of its playlists and its janitor retired
/// the songs nobody pointed at must end with no row nobody points at.
///
/// Two faults, one test file. (1) A purged entry's tombstone is `{id, playlist, deleted: true}`: it names no song, so the page of the changes feed carries no
/// id for `dropUnused`, and the row of a song whose LAST entry it removed stayed for ever. (2) `pull()` read the gone list before the changes, so the entries
/// still held the row when "gone" was heard. The fix is in `EncoreWriter.applyPlaylists` (it hands back the songs whose place in a playlist it took away) and
/// in `EncoreSync.pull` (the changes first, then the files and the gone list).
///
/// The first group serves the REAL responses the server's own tests saved (`library-changes-with-purged-tombstones.json`, `library-files-with-gone.json`),
/// so the contract is proved on both sides; the last group runs the whole story against the fake server (entries removed, purged, songs retired, the
/// phone asks).
const _live = 'pl_aaaaaaaaaaaaaaaaaaaaaaaaaa';
const _deleted = 'pl_bbbbbbbbbbbbbbbbbbbbbbbbbb';
const _missing = 'pl_cccccccccccccccccccccccccc';
const _removed = 'pe_xxxxxxxxxxxxxxxxxxxxxxxxxx';
const _inDeleted = 'pe_yyyyyyyyyyyyyyyyyyyyyyyyyy';
const _noPlaylist = 'pe_zzzzzzzzzzzzzzzzzzzzzzzzzz';

/// The two songs the saved answer of the files feed lists as gone.
const _goneA = 'sr_00000000000000000000000001';
const _goneB = 'sr_00000000000000000000000002';

/// Songs the files feed does NOT list as gone.
const _stays = 'sr_00000000000000000000000003';
const _keeper = 'sr_00000000000000000000000004';
const _other = 'sr_00000000000000000000000005';

void main() {
  late AppDatabase db;
  late FakeEncoreServer server;
  late EncoreSync sync;
  late SyncStateStore state;
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
      pageLimit: 3,
    );
  });
  tearDown(() => db.close());

  // ------------------------------------------------------------------ what a test arranges

  Map<String, Object?> saved(String name) =>
      (jsonDecode(File('test/fixtures/server/$name').readAsStringSync()) as Map)
          .cast<String, Object?>();

  /// Serves the two real responses, whatever the phone asks.
  void serveTheSavedAnswers() {
    server.changesAnswer = saved('library-changes-with-purged-tombstones.json');
    server.filesAnswer = saved('library-files-with-gone.json');
  }

  /// A song row of an Encore server: what a pull left, or a tap on a song the server could not find.
  Future<void> song(String id,
          {String? fileId, int? starredAtMs, bool isRef = true}) =>
      db.into(db.tracks).insert(TracksCompanion.insert(
            serverId: serverId,
            id: id,
            title: 'Song $id',
            isRef: Value(isRef),
            fileId: Value(fileId),
            starredAtMs: Value(starredAtMs),
          ));

  Future<void> playlist(String id) =>
      db.into(db.playlists).insertOnConflictUpdate(PlaylistsCompanion.insert(
            serverId: serverId,
            id: id,
            name: 'List $id',
          ));

  var place = 0;

  /// A place in a playlist, as an earlier pull left it.
  Future<void> entry(String playlistId, String entryId, String trackId) =>
      db.into(db.playlistEntries).insert(PlaylistEntriesCompanion.insert(
            serverId: serverId,
            playlistId: playlistId,
            position: place,
            trackId: trackId,
            entryId: Value(entryId),
            serverPosition: Value((place++).toDouble()),
          ));

  Future<void> download(String id) =>
      db.into(db.downloads).insert(DownloadsCompanion.insert(
            serverId: serverId,
            trackId: id,
            state: const Value(DownloadState.done),
            localPath: const Value('/phone/downloads/song.opus'),
            bytes: const Value(1234),
            updatedAtMs: 1,
          ));

  Future<void> pin(String id) => db.into(db.pins).insert(PinsCompanion.insert(
        serverId: serverId,
        targetType: 'track',
        targetId: id,
        createdAtMs: 1,
      ));

  Future<TrackRow?> track(String id) => (db.select(db.tracks)
        ..where((t) => t.serverId.equals(serverId) & t.id.equals(id)))
      .getSingleOrNull();

  Future<bool> live(String id) async {
    final row = await track(id);
    return row != null && row.deletedAtMs == null;
  }

  Future<DownloadRow?> dl(String id) => (db.select(db.downloads)
        ..where((d) => d.serverId.equals(serverId) & d.trackId.equals(id)))
      .getSingleOrNull();

  Future<Set<String>> entryIds() async => {
        for (final e in await db.select(db.playlistEntries).get())
          if (e.entryId != null) e.entryId!
      };

  /// The phone as it was when it went away: the place of the removed entry (in a live playlist), the place of an entry of a playlist that was deleted, and
  /// a place that stays. [_goneA] has a file of the music server (so the gone list has something to clear), [_goneB] and [_stays] have none.
  Future<void> awayPhone() async {
    for (final p in [_live, _deleted, _missing]) {
      await playlist(p);
    }
    await song(_goneA, fileId: 'nd-a');
    await song(_goneB);
    await song(_stays);
    await song(_keeper);
    await entry(_live, _removed, _goneA);
    await entry(_deleted, _inDeleted, _goneB);
    await entry(_missing, 'pe_other0000000000000000000', _stays);
    await entry(_live, 'pe_keeper000000000000000000', _keeper);
  }

  // ------------------------------------------------------------------ the away phone, on the real responses

  group(
      "a phone that was away over the purge and the retirement (the real responses the server saved)",
      () {
    test(
        "no row is left that nothing points at: the songs of the purged entries go, whether the gone list names them or not; the song of a live entry stays",
        () async {
      await awayPhone();
      serveTheSavedAnswers();

      (await sync.pull()).getOrThrow();

      expect(await entryIds(), {'pe_keeper000000000000000000'});
      expect(await live(_goneA), isFalse,
          reason: 'its last place was the removed entry; the server says gone');
      expect(await live(_goneB), isFalse,
          reason: 'its last place was in a deleted playlist; gone');
      expect(await live(_stays), isFalse,
          reason:
              'NOT in the gone list: only the entry that held it was purged, and the phone must still not keep a row nothing points at');
      expect(await live(_keeper), isTrue);
    });

    test(
        "an entry of a playlist the server says is deleted, which no entry tombstone names, frees its song as well",
        () async {
      await playlist(_deleted);
      await song(_other);
      await entry(_deleted, 'pe_not_named_by_a_tombstone0', _other);
      serveTheSavedAnswers();

      (await sync.pull()).getOrThrow();

      expect(await entryIds(), isEmpty);
      expect(await live(_other), isFalse,
          reason: 'the playlist tombstone removed its entries, all of them');
    });

    test(
        "a song the person liked keeps its row (its entry is gone, the like is not)",
        () async {
      await awayPhone();
      await (db.update(db.tracks)
            ..where((t) => t.serverId.equals(serverId) & t.id.equals(_goneB)))
          .write(const TracksCompanion(starredAtMs: Value(5)));
      serveTheSavedAnswers();

      (await sync.pull()).getOrThrow();

      expect(await live(_goneB), isTrue);
      expect(await live(_stays), isFalse, reason: 'the others still go');
    });

    test(
        "a song still in ANOTHER playlist keeps its row, and so does a song the person pinned to keep",
        () async {
      await awayPhone();
      await playlist('pl_second00000000000000000000');
      await entry('pl_second00000000000000000000',
          'pe_second000000000000000000', _goneB);
      await pin(_stays);
      serveTheSavedAnswers();

      (await sync.pull()).getOrThrow();

      expect(await live(_goneB), isTrue, reason: 'another playlist holds it');
      expect(await live(_stays), isTrue, reason: 'pinned');
      expect(await live(_goneA), isFalse, reason: 'nothing holds this one');
    });

    test(
        "a song that was DOWNLOADED keeps its row and its download exactly as they were, also when the server says it is gone: it plays offline",
        () async {
      await awayPhone();
      await download(_goneA);
      final before = await dl(_goneA);
      serveTheSavedAnswers();

      (await sync.pull()).getOrThrow();

      expect(await live(_goneA), isTrue, reason: 'the downloads guard');
      expect((await track(_goneA))!.fileId, isNull,
          reason: 'the file of the server is gone: only the link is cleared');
      final after = await dl(_goneA);
      expect(after, isNotNull);
      expect(after!.state, before!.state);
      expect(after.localPath, before.localPath);
      expect(after.bytes, before.bytes);
      expect(after.updatedAtMs, before.updatedAtMs);
    });

    test(
        "a song the server still keeps a file of stays in the browse index when its last entry is purged (only a row without a file is retired)",
        () async {
      await awayPhone();
      await (db.update(db.tracks)
            ..where((t) => t.serverId.equals(serverId) & t.id.equals(_stays)))
          .write(const TracksCompanion(fileId: Value('nd-stays')));
      serveTheSavedAnswers();

      (await sync.pull()).getOrThrow();

      expect(await live(_stays), isTrue);
      expect((await track(_stays))!.fileId, 'nd-stays');
    });

    test(
        "a row of a plain music server (not a ref) is never touched, whatever its id looks like",
        () async {
      await playlist(_live);
      await song(_stays, isRef: false);
      await entry(_live, _removed, _stays);
      serveTheSavedAnswers();

      (await sync.pull()).getOrThrow();

      expect(await entryIds(), isEmpty);
      expect(await live(_stays), isTrue);
    });

    test(
        "an entry that names no playlist is still skipped (the server always names it when it knows it): its song stays",
        () async {
      await playlist(_live);
      await song(_other);
      await entry(_live, _noPlaylist, _other);
      serveTheSavedAnswers();

      (await sync.pull()).getOrThrow();

      expect(await entryIds(), contains(_noPlaylist));
      expect(await live(_other), isTrue);
    });
  });

  // ------------------------------------------------------------------ a live feed, not the saved one

  group("an entry that comes again, or moves", () {
    Map<String, Object?> page(List<Map<String, Object?>> playlists,
            List<Map<String, Object?>> entries,
            [List<Map<String, Object?>> refs = const []]) =>
        {
          'refs': refs,
          'likes': const <Object?>[],
          'savedAlbums': const <Object?>[],
          'follows': const <Object?>[],
          'playlists': playlists,
          'entries': entries,
          'cursor': '1',
          'more': false,
        };

    Map<String, Object?> ref(String id) => {
          'id': id,
          'title': 'Song $id',
          'artists': ['Artist'],
          'durationMs': 200000,
          'file': null,
        };

    Map<String, Object?> live1(String id, String playlist, String ref) => {
          'id': id,
          'playlist': playlist,
          'ref': ref,
          'position': 1.0,
          'addedAt': 1,
          'deleted': false,
        };

    Map<String, Object?> list(String id) => {
          'id': id,
          'name': 'List',
          'cover': null,
          'collaborative': false,
          'createdAt': 1,
          'updatedAt': 2,
          'deleted': false,
        };

    test(
        "an entry that names another song now frees the song it held before (the phone hears it from the entry's own id)",
        () async {
      await playlist(_live);
      await song(_goneA);
      await song(_stays);
      await entry(_live, _removed, _goneA);
      server.changesAnswer =
          page([list(_live)], [live1(_removed, _live, _stays)], [ref(_stays)]);

      (await sync.pullChanges()).getOrThrow();

      expect(await live(_goneA), isFalse);
      expect(await live(_stays), isTrue);
    });

    test(
        "a song moved from one playlist to another in one page keeps its row (the place it left is freed, the place it came to holds it)",
        () async {
      await playlist(_live);
      await playlist(_deleted);
      await song(_goneA);
      await entry(_live, _removed, _goneA);
      server.changesAnswer = page([
        list(_live),
        list(_deleted),
      ], [
        {'id': _removed, 'playlist': _live, 'deleted': true},
        live1(_inDeleted, _deleted, _goneA),
      ], [
        ref(_goneA)
      ]);

      (await sync.pullChanges()).getOrThrow();

      expect(await entryIds(), {_inDeleted});
      expect(await live(_goneA), isTrue);
    });

    test(
        "a removal that carries its song (a tombstone that was not purged yet) still drops the row, as before",
        () async {
      await playlist(_live);
      await song(_goneA);
      await entry(_live, _removed, _goneA);
      server.changesAnswer = page([
        list(_live)
      ], [
        {
          ...live1(_removed, _live, _goneA),
          'deleted': true,
        },
      ]);

      (await sync.pullChanges()).getOrThrow();

      expect(await live(_goneA), isFalse);
    });
  });

  // ------------------------------------------------------------------ the order of the two feeds

  group("the order of the pulls", () {
    List<String> paths() => [
          for (final r in server.adapter.requests)
            if (r.uri.path.endsWith('/library/changes') ||
                r.uri.path.endsWith('/library/files'))
              r.uri.path.split('/').last
        ];

    test(
        "the changes are read before the files and the gone list, so every pointer is in its final state when \"gone\" is heard",
        () async {
      final a = server.addRef('Song A', 'Artist', fileId: 'nd-a');
      server.addPlaylist('pl_00000000000000000000000001', 'Mix', [a]);

      (await sync.pull()).getOrThrow();

      expect(paths().first, 'changes');
      expect(paths(), contains('files'));
      expect(paths().indexOf('changes'), lessThan(paths().indexOf('files')));
    });

    test(
        "every cursor is kept after a pull, and the next pull asks from them and finds nothing new",
        () async {
      final a = server.addRef('Song A', 'Artist', fileId: 'nd-a');
      server.addPlaylist('pl_00000000000000000000000001', 'Mix', [a]);
      server.retire(server.addRef('Song B', 'Artist'));

      (await sync.pull()).getOrThrow();

      expect(await state.get(EncoreSync.changesCursor), isNot('0'));
      expect(await state.get(EncoreSync.filesCursor), isNot('0'));
      expect(await state.get(EncoreSync.goneCursor), '1');
      expect(await state.get(EncoreSync.mergesCursor), '0');
      server.goneSinceSeen.clear();

      final again = (await sync.pull()).getOrThrow();

      expect(again.changed, 0);
      expect(server.goneSinceSeen, ['1']);
    });

    test(
        "when the changes cannot be read nothing of the files is asked and no cursor moves; the next pull reads both",
        () async {
      final a = server.addRef('Song A', 'Artist', fileId: 'nd-a');
      server.addPlaylist('pl_00000000000000000000000001', 'Mix', [a]);
      server.adapter.routes['/encore/api/v1/library/changes'] =
          (r) => const FakeResponse.connectionError();

      final failed = await sync.pull();

      expect(failed.isErr, isTrue);
      expect(paths(), ['changes']);
      expect(await state.get(EncoreSync.changesCursor), isNull);
      expect(await state.get(EncoreSync.filesCursor), isNull);
      expect(await state.get(EncoreSync.goneCursor), isNull);

      server.adapter.routes.remove('/encore/api/v1/library/changes');
      final caught = (await sync.pull()).getOrThrow();

      expect(caught.files, 1);
      expect(caught.playlists, 1);
      expect(await live(a), isTrue);
    });
  });

  // ------------------------------------------------------------------ the whole story, on the fake server

  group("the whole story on the fake server", () {
    const list = 'pl_00000000000000000000000001';

    Future<void> removeEntriesOf(List<String> refIds) async {
      final ids = [
        for (final e in server.entries[list]!)
          if (refIds.contains(e['ref'])) e['id']! as String
      ];
      await server.call('DELETE', '/encore/api/v1/playlists/$list/entries',
          {'entryIds': ids});
    }

    test(
        "a phone that has the playlist, goes away while its entries are removed and purged and its songs retired, comes back with no row nothing points at; what it liked and downloaded stays",
        () async {
      final a = server.addRef('Song A', 'Artist', fileId: 'nd-a');
      final b = server.addRef('Song B', 'Artist');
      final c = server.addRef('Song C', 'Artist');
      final d = server.addRef('Song D', 'Artist', fileId: 'nd-d');
      server.addPlaylist(list, 'Mix', [a, b, c, d]);
      server.otherDeviceLikes(c);
      (await sync.pull()).getOrThrow();
      await download(d);
      expect((await db.select(db.playlistEntries).get()).length, 4);
      for (final id in [a, b, c, d]) {
        expect(await live(id), isTrue, reason: id);
      }

      // The phone is away. Somebody removes the four entries, 90 days pass, the server purges them and its janitor retires the songs nothing points at: A, B
      // and D (C is liked: the server keeps it).
      await removeEntriesOf([a, b, c, d]);
      server.purgeTombstones();
      server.retire(a);
      server.retire(b);
      server.retire(d);

      (await sync.pull()).getOrThrow();

      expect(await db.select(db.playlistEntries).get(), isEmpty);
      expect(await live(a), isFalse, reason: "A: a file, gone, no entry");
      expect(await live(b), isFalse, reason: "B: no file, gone, no entry");
      expect(await live(c), isTrue, reason: "C: the person liked it");
      expect(await live(d), isTrue, reason: "D: downloaded");
      expect((await dl(d))!.localPath, '/phone/downloads/song.opus');
      expect((await track(d))!.fileId, isNull);
    });

    test(
        "a phone that was online keeps working as before: an entry removed and echoed with its song drops the row, and a second pull changes nothing",
        () async {
      final a = server.addRef('Song A', 'Artist');
      final b = server.addRef('Song B', 'Artist');
      server.addPlaylist(list, 'Mix', [a, b]);
      (await sync.pull()).getOrThrow();

      await removeEntriesOf([a]);
      (await sync.pull()).getOrThrow();

      expect(await live(a), isFalse);
      expect(await live(b), isTrue);
      expect((await sync.pull()).getOrThrow().changed, 0);
    });
  });
}
