import 'package:dio/dio.dart';
import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:drift/native.dart';
import 'package:encore/core/clock.dart';
import 'package:encore/data/api/opensubsonic/opensubsonic_client.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/encore/encore_api.dart';
import 'package:encore/data/encore/encore_mutations.dart';
import 'package:encore/data/encore/encore_sync.dart';
import 'package:encore/data/sync/outbox.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_encore_server.dart';
import '../../support/fake_http.dart';

/// The person's edits on an Encore server: local first, delivered in order, safe to deliver twice, and what comes back from the server is
/// the same thing the person already sees.
void main() {
  late AppDatabase db;
  late FakeEncoreServer server;
  late EncoreApi api;
  late EncorePlaylistEditor editor;
  late MutationService mutations;
  late OutboxProcessor outbox;
  late EncoreSync sync;
  late FakeClock clock;
  late int serverId;
  late String a;
  late String b;
  late String c;

  setUp(() async {
    db = AppDatabase(NativeDatabase.memory());
    serverId = await db.into(db.servers).insert(ServersCompanion.insert(
        name: 'T', username: 'tester', endpointsJson: '[]', createdAtMs: 0));
    clock = FakeClock(DateTime.utc(2026, 10, 22, 12));
    server = FakeEncoreServer();
    api = EncoreApi(
      dio: Dio()..httpClientAdapter = server.adapter,
      baseUrl: () => Uri.parse('http://home.test:4540'),
      auth: () => {'u': 'tester', 't': 'tok', 's': 'salt'},
      deviceId: 'dv_00000000000000000000000001',
    );
    a = server.addRef('A', 'X', fileId: 'nd-1', meta: {'albumId': 'al-1'});
    b = server.addRef('B', 'X', fileId: 'nd-2', meta: {'albumId': 'al-1'});
    c = server.addRef('C', 'Y');
    sync = EncoreSync(
        db: db,
        api: api,
        serverId: serverId,
        ownerName: 'tester',
        clock: clock);
    await sync
        .pullFiles(); // A and B are in the library's index; C is a song nobody keeps a file of
    final changes = (await api.ref(c)).getOrThrow();
    await db.into(db.tracks).insert(TracksCompanion.insert(
          serverId: serverId,
          id: changes.id,
          title: changes.title,
          isRef: const Value(true),
        ));
    outbox = OutboxProcessor(
      db: db,
      client: OpenSubsonicClient(
        dio: fakeDio(FakeHttpAdapter()),
        baseUrl: () => Uri.parse('http://unused'),
        credentials: const SubsonicCredentials(username: 'u', password: 'p'),
      ),
      serverId: serverId,
      clock: clock,
      encore: api,
    );
    editor = EncorePlaylistEditor(
        db: db, serverId: serverId, clock: clock, ownerName: 'tester');
    mutations = MutationService(db: db, serverId: serverId, clock: clock);
  });

  tearDown(() async {
    await outbox.dispose();
    await db.close();
  });

  Future<List<PlaylistEntryRow>> entries(String id) =>
      (db.select(db.playlistEntries)
            ..where((e) => e.playlistId.equals(id))
            ..orderBy([(e) => OrderingTerm.asc(e.position)]))
          .get();

  group('playlists', () {
    test(
        'a new playlist is on screen at once with ids of the phone\'s own, and arrives on the server exactly as shown',
        () async {
      final id = await editor.create('Road trip', trackIds: [a, b, c]);

      expect(id, startsWith('pl_'));
      expect((await entries(id)).map((e) => e.trackId), [a, b, c]);
      expect(
          (await entries(id)).every((e) => (e.entryId ?? '').startsWith('pe_')),
          isTrue);
      expect(server.playlists, isEmpty,
          reason: 'nothing was sent yet: the edit waits in the outbox');

      await outbox.flush();

      expect(server.playlists.keys, [id]);
      expect(server.entries[id]!.map((e) => e['id']),
          (await entries(id)).map((e) => e.entryId));
      expect(await db.select(db.outbox).get(), isEmpty);
    });

    test('offline it waits, and when the connection is back it arrives once',
        () async {
      server.online = false;
      final id = await editor.create('Gym', trackIds: [a]);
      await editor.addTracks(id, [b]);

      await outbox.flush();
      expect(await db.select(db.outbox).get(), hasLength(2),
          reason: 'still waiting');
      expect(server.playlists, isEmpty);

      server.online = true;
      clock.advance(const Duration(hours: 1));
      await outbox.flush();
      await outbox.flush();

      expect(server.playlists.keys, [id]);
      expect(server.entries[id], hasLength(2));
      expect(await db.select(db.outbox).get(), isEmpty);
    });

    test(
        'adding, removing and renaming are applied locally first and delivered in order',
        () async {
      final id = await editor.create('Mix', trackIds: [a]);
      await editor.addTracks(id, [b, c]);
      await editor.removeAt(id, 0);
      await editor.rename(id, 'Better mix');

      expect((await entries(id)).map((e) => (e.position, e.trackId)),
          [(0, b), (1, c)]);
      final row = await (db.select(db.playlists)..where((p) => p.id.equals(id)))
          .getSingle();
      expect((row.name, row.songCount), ('Better mix', 2));

      await outbox.flush();

      expect(server.playlists[id]!['name'], 'Better mix');
      final live = [
        for (final e in server.entries[id]!)
          if (e['deleted'] == false) e['ref']
      ];
      expect(live, [b, c]);
    });

    test(
        'what the server sends back is what the person already sees (no duplicate, no reorder)',
        () async {
      final id = await editor.create('Mix', trackIds: [a, b]);
      await editor.addTracks(id, [c]);
      await outbox.flush();
      final before = (await entries(id))
          .map((e) => (e.position, e.trackId, e.entryId))
          .toList();

      await sync.pullChanges();

      expect(
          (await entries(id))
              .map((e) => (e.position, e.trackId, e.entryId))
              .toList(),
          before);
    });

    test(
        'deleting is delivered, and deleting what another device already deleted is not an error',
        () async {
      final id = await editor.create('Old', trackIds: [a]);
      await outbox.flush();
      await server.call('DELETE', '/encore/api/v1/playlists/$id');

      await editor.delete(id);
      await outbox.flush();

      expect(await db.select(db.outbox).get(), isEmpty);
      expect(
          (await (db.select(db.playlists)..where((p) => p.id.equals(id)))
                  .getSingle())
              .deletedAtMs,
          isNotNull);
    });

    test(
        'adding to a playlist another device deleted is dropped, not parked as a failure',
        () async {
      final id = await editor.create('Mine', trackIds: [a]);
      await outbox.flush();
      await server.call('DELETE', '/encore/api/v1/playlists/$id');

      await editor.addTracks(id, [b]);
      await outbox.flush();

      expect(await db.select(db.outbox).get(), isEmpty);
    });

    test('a playlist that does not exist cannot be edited', () async {
      expect(await editor.addTracks('pl_nope', [a]), isFalse);
      expect(await editor.rename('pl_nope', 'x'), isFalse);
      expect(await editor.removeAt('pl_nope', 0), isFalse);
    });
  });

  group('likes and plays', () {
    test(
        'a heart is local at once and arrives as a like with the time it was given',
        () async {
      await db.into(db.tracks).insertOnConflictUpdate(TracksCompanion.insert(
          serverId: serverId, id: a, title: 'A', isRef: const Value(true)));
      await mutations.setTrackStarred(a, true);

      expect(
          (await (db.select(db.tracks)..where((t) => t.id.equals(a)))
                  .getSingle())
              .starredAtMs,
          isNotNull);
      await outbox.flush();

      expect(server.likes.keys, [a]);
      expect(server.likes[a], clock.now().millisecondsSinceEpoch);

      await mutations.setTrackStarred(a, false);
      await outbox.flush();
      expect(server.likes, isEmpty);
    });

    test(
        'a listening is one play on the server however often its delivery is repeated',
        () async {
      await mutations.recordPlay(
          trackId: a, listenedMs: 187000, source: 'album:al-1');
      await outbox.flush();
      final first = server.plays.single;

      // the same row delivered again after a lost answer
      await server.call('POST', '/encore/api/v1/plays', first);

      expect(server.plays, hasLength(1));
      expect(first['ref'], a);
      expect(first['msPlayed'], 187000);
      expect(first['context'], 'album:al-1');
    });

    test(
        'a now-playing ping and a rating are not sent anywhere and do not stay in the queue',
        () async {
      await db.into(db.outbox).insert(OutboxCompanion.insert(
          serverId: serverId,
          kind: OutboxKind.rating,
          payloadJson: '{"id":"x","rating":4}',
          createdAtMs: 1));
      await db.into(db.outbox).insert(OutboxCompanion.insert(
          serverId: serverId,
          kind: OutboxKind.scrobble,
          payloadJson: '{"id":"x","submission":false}',
          createdAtMs: 2));

      await outbox.flush();

      expect(await db.select(db.outbox).get(), isEmpty);
      expect(server.plays, isEmpty);
    });
  });
}
