import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:drift/native.dart';
import 'package:encore/core/result.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/encore/encore_api.dart';
import 'package:encore/data/encore/encore_upgrade.dart';
import 'package:encore/data/sync/sync_state_store.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_encore_server.dart';

/// A phone that has talked to a plain music server for months moves onto an Encore server (docs/18 section 4): nothing the person has is
/// lost, and every id that named a song names the server's ref afterwards.
void main() {
  late AppDatabase db;
  late FakeEncoreServer server;
  late EncoreApi api;
  late int serverId;
  var pending = 0;

  const legacyPlaylist = 'AbCdEfGhIjKlMnOpQrStUv';
  const newPlaylist = 'pl_22222222222222222222222222';

  setUp(() async {
    pending = 0;
    db = AppDatabase(NativeDatabase.memory());
    serverId = await db.into(db.servers).insert(ServersCompanion.insert(
        name: 'T', username: 'tester', endpointsJson: '[]', createdAtMs: 0));
    server = FakeEncoreServer();
    api = EncoreApi(
      dio: Dio()..httpClientAdapter = server.adapter,
      baseUrl: () => Uri.parse('http://home.test:4540'),
      auth: () => {'u': 'tester', 't': 'tok', 's': 'salt'},
    );
  });

  tearDown(() => db.close());

  EncoreUpgrade upgrade() => EncoreUpgrade(
      db: db,
      api: api,
      serverId: serverId,
      ownerName: 'tester',
      pendingEdits: () async => pending);

  Future<void> legacySong(String id, String title,
          {bool starred = false, String? albumId = 'al-1'}) =>
      db.into(db.tracks).insert(TracksCompanion.insert(
            serverId: serverId,
            id: id,
            title: title,
            artist: const Value('Artist'),
            album: const Value('Album'),
            albumId: Value(albumId),
            durationSec: const Value(200),
            starredAtMs: Value(starred ? 1700000000000 : null),
          ));

  Future<TrackRow?> track(String id) =>
      (db.select(db.tracks)..where((t) => t.id.equals(id))).getSingleOrNull();

  /// The phone of a person with three songs of the music server, one liked, a playlist of two, a download, a listen, a pin and a queue.
  Future<({String a, String b, String c})> arrange() async {
    final a = server.addRef('Song A', 'Artist',
        album: 'Album', fileId: 'nd-a', meta: {'albumId': 'al-1'});
    final b = server.addRef('Song B', 'Artist',
        album: 'Album', fileId: 'nd-b', meta: {'albumId': 'al-1'});
    final c = server.addRef('Song C', 'Artist',
        album: 'Album', fileId: 'nd-c', meta: {'albumId': 'al-1'});
    await legacySong('nd-a', 'Song A', starred: true);
    await legacySong('nd-b', 'Song B');
    await legacySong('nd-c', 'Song C');
    await db.into(db.playlists).insert(PlaylistsCompanion.insert(
        serverId: serverId,
        id: legacyPlaylist,
        name: 'Gym',
        owner: const Value('tester'),
        songCount: const Value(2)));
    for (final (i, id) in ['nd-b', 'nd-a'].indexed) {
      await db.into(db.playlistEntries).insert(PlaylistEntriesCompanion.insert(
          serverId: serverId,
          playlistId: legacyPlaylist,
          position: i,
          trackId: id));
    }
    await db.into(db.downloads).insert(DownloadsCompanion.insert(
        serverId: serverId,
        trackId: 'nd-b',
        state: const Value(2),
        localPath: const Value('/x/b.opus'),
        bytes: const Value(1000),
        updatedAtMs: 0));
    await db.into(db.playHistory).insert(PlayHistoryCompanion.insert(
        serverId: serverId,
        trackId: 'nd-a',
        playedAtMs: 5,
        listenedMs: const Value(100000)));
    await db.into(db.pins).insert(PinsCompanion.insert(
        serverId: serverId,
        targetType: 'playlist',
        targetId: legacyPlaylist,
        createdAtMs: 1));
    await db.into(db.pins).insert(PinsCompanion.insert(
        serverId: serverId,
        targetType: 'album',
        targetId: 'al-1',
        createdAtMs: 2));
    await db.into(db.pins).insert(PinsCompanion.insert(
        serverId: serverId,
        targetType: 'track',
        targetId: 'nd-c',
        createdAtMs: 3));
    await SyncStateStore(db, serverId).set(
      'playback.state',
      jsonEncode({
        'queue': {
          'items': [
            {'uid': 1, 'id': 'nd-a', 'title': 'Song A'},
            {'uid': 2, 'id': 'nd-c', 'title': 'Song C'},
          ],
          'index': 1,
        },
        'positionMs': 4000,
      }),
    );
    // What the Encore server holds after it read the person's stars and playlists from the music server.
    server.otherDeviceLikes(a);
    server.addPlaylist(newPlaylist, 'Gym', [b, a],
        sourceId: 'nd:$legacyPlaylist');
    server.migrationReport = {
      'likes': 1,
      'albums': 0,
      'artists': 0,
      'playlists': 1,
      'entries': 2,
      'unmatched': 0
    };
    return (a: a, b: b, c: c);
  }

  test(
      'every id that named a song names the ref afterwards, and nothing the person has is lost',
      () async {
    final refs = await arrange();

    final report = (await upgrade().run()).getOrThrow();

    expect(server.migrations, 1);
    expect(report.songsMoved, 3);
    // the songs: the ref's id, the music server's id as the file
    final a = (await track(refs.a))!;
    expect((a.isRef, a.fileId, a.albumId), (true, 'nd-a', 'al-1'));
    expect(a.starredAtMs, isNotNull);
    expect(await track('nd-a'), isNull);
    // the playlist: the server's, with the same songs in the same order, and its pin followed it
    expect(
        (await db.select(db.playlists).get())
            .map((p) => (p.id, p.name, p.songCount)),
        [(newPlaylist, 'Gym', 2)]);
    final entries = await (db.select(db.playlistEntries)
          ..orderBy([(e) => OrderingTerm.asc(e.position)]))
        .get();
    expect(entries.map((e) => e.trackId), [refs.b, refs.a]);
    final pins = {
      for (final p in await db.select(db.pins).get())
        '${p.targetType}:${p.targetId}'
    };
    expect(pins, {'playlist:$newPlaylist', 'album:al-1', 'track:${refs.c}'});
    // the download, the listening
    expect(
        (await db.select(db.downloads).get())
            .map((d) => (d.trackId, d.localPath)),
        [(refs.b, '/x/b.opus')]);
    expect(
        (await db.select(db.playHistory).get())
            .map((h) => (h.trackId, h.listenedMs)),
        [(refs.a, 100000)]);
    // the saved queue
    final queue =
        jsonDecode((await SyncStateStore(db, serverId).get('playback.state'))!)
            as Map;
    expect([
      for (final i in (queue['queue'] as Map)['items'] as List) (i as Map)['id']
    ], [
      refs.a,
      refs.c
    ]);
    expect((queue['queue'] as Map)['index'], 1);
    expect(await upgrade().isDone(), isTrue);
  });

  test(
      'a song the server does not know by its file is found by what it is called',
      () async {
    final a = server.addRef('Song A', 'Artist', album: 'Album', fileId: 'nd-a');
    await legacySong('nd-a', 'Song A');
    await legacySong('nd-gone', 'A Song Whose File Was Deleted', starred: true);
    await db.into(db.playlistEntries).insert(PlaylistEntriesCompanion.insert(
        serverId: serverId,
        playlistId: legacyPlaylist,
        position: 0,
        trackId: 'nd-gone'));
    await db.into(db.playlists).insert(PlaylistsCompanion.insert(
        serverId: serverId, id: legacyPlaylist, name: 'Old'));

    final report = (await upgrade().run()).getOrThrow();

    expect(report.songsResolved, 1);
    final rows = await (db.select(db.tracks)
          ..where((t) => t.title.equals('A Song Whose File Was Deleted')))
        .get();
    expect(rows.single.id, startsWith('sr_'));
    expect(rows.single.isRef, isTrue);
    expect(rows.single.fileId, isNull, reason: 'it plays from the server now');
    expect(rows.single.starredAtMs, isNotNull);
    expect(a, startsWith('sr_'));
  });

  test(
      'songs nothing of the person\'s points at are dropped; the server\'s pull brings back what exists',
      () async {
    server.addRef('Kept', 'Artist', fileId: 'nd-k');
    await legacySong('nd-k', 'Kept');
    await legacySong('nd-x', 'Nobody uses me');

    final report = (await upgrade().run()).getOrThrow();

    expect(await track('nd-x'), isNull);
    expect(report.songsDropped, greaterThanOrEqualTo(1));
    expect((await db.select(db.tracks).get()).map((t) => t.title), ['Kept'],
        reason: 'the files feed gives it back as a ref');
  });

  test(
      'two files of one recording become one song, and the download that is on the phone is kept',
      () async {
    final ref = server.addRef('Twin', 'Artist', fileId: 'nd-1');
    server.attachFile(ref, 'nd-2');
    await legacySong('nd-1', 'Twin');
    await legacySong('nd-2', 'Twin');
    await db.into(db.downloads).insert(DownloadsCompanion.insert(
        serverId: serverId,
        trackId: 'nd-2',
        state: const Value(2),
        localPath: const Value('/x/twin.opus'),
        updatedAtMs: 0));

    (await upgrade().run()).getOrThrow();

    expect(
        await (db.select(db.tracks)..where((t) => t.title.equals('Twin')))
            .get(),
        hasLength(1));
    expect(
        (await db.select(db.downloads).get())
            .map((d) => (d.trackId, d.localPath)),
        [(ref, '/x/twin.opus')]);
  });

  test(
      'it does not start while changes are still waiting to be sent the old way, and changes nothing',
      () async {
    await arrange();
    pending = 2;

    final result = await upgrade().run();

    expect(result.failureOrNull, isA<NetworkFailure>());
    expect(server.migrations, 0);
    expect(await track('nd-a'), isNotNull);
    expect(await upgrade().isDone(), isFalse);
  });

  test(
      'a server that cannot be reached half way leaves the phone as it was, and running again finishes',
      () async {
    await arrange();
    server.online = false;

    expect((await upgrade().run()).isErr, isTrue);
    expect(await track('nd-a'), isNotNull, reason: 'nothing was moved');
    expect(await db.select(db.playlists).get(), hasLength(1));

    server.online = true;
    (await upgrade().run()).getOrThrow();
    expect(await track('nd-a'), isNull);
  });

  test('running it again after it finished changes nothing', () async {
    final refs = await arrange();
    (await upgrade().run()).getOrThrow();
    final before = (await db.select(db.playlistEntries).get())
        .map((e) => (e.playlistId, e.position, e.trackId))
        .toList();

    (await upgrade().run()).getOrThrow();

    expect(
        (await db.select(db.playlistEntries).get())
            .map((e) => (e.playlistId, e.position, e.trackId))
            .toList(),
        before);
    expect(await track(refs.a), isNotNull);
  });
}
