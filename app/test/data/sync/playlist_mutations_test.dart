import 'dart:convert';

import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:drift/native.dart';
import 'package:encore/core/clock.dart';
import 'package:encore/data/api/opensubsonic/opensubsonic_client.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/sync/outbox.dart';
import 'package:encore/data/sync/playlist_mutations.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_http.dart';
import '../../support/fake_subsonic_server.dart';

void main() {
  late AppDatabase db;
  late FakeHttpAdapter adapter;
  late FakeClock clock;
  late OutboxProcessor outbox;
  late PlaylistMutations playlists;
  late int serverId;
  var queued = 0;

  // What the "server" currently holds for playlist `srv-1`.
  var serverEntries = <String>[];

  setUp(() async {
    db = AppDatabase(NativeDatabase.memory());
    serverId = await db.into(db.servers).insert(ServersCompanion.insert(
          name: 'T',
          username: 'marwa',
          endpointsJson: '[]',
          createdAtMs: 0,
        ));
    for (var i = 1; i <= 6; i++) {
      await db.into(db.tracks).insert(TracksCompanion.insert(
            serverId: serverId,
            id: 't$i',
            title: 'Song $i',
            durationSec: Value(100 * i),
          ));
    }
    serverEntries = [];
    adapter = FakeHttpAdapter(routes: {
      'createPlaylist': (_) => FakeResponse.json(subsonicOk({
            'playlist': {'id': 'srv-1', 'name': 'x'},
          })),
      'updatePlaylist': (_) => FakeResponse.json(subsonicOk({})),
      'deletePlaylist': (_) => FakeResponse.json(subsonicOk({})),
      'getPlaylist': (_) => FakeResponse.json(subsonicOk({
            'playlist': FakeSubsonicServer.playlist('srv-1', 'Road trip',
                songIds: serverEntries),
          })),
    });
    clock = FakeClock(DateTime.utc(2026, 10, 15, 12));
    final client = OpenSubsonicClient(
      dio: fakeDio(adapter),
      baseUrl: () => Uri.parse('http://fake'),
      credentials: const SubsonicCredentials(username: 'marwa', password: 'p'),
    );
    outbox = OutboxProcessor(
        db: db, client: client, serverId: serverId, clock: clock);
    queued = 0;
    playlists = PlaylistMutations(
      db: db,
      serverId: serverId,
      clock: clock,
      ownerName: 'marwa',
      onQueued: () => queued++,
    );
  });

  tearDown(() => db.close());

  Future<PlaylistRow?> row(String id) =>
      (db.select(db.playlists)..where((p) => p.id.equals(id)))
          .getSingleOrNull();

  Future<List<String>> entries(String id) async {
    final rows = await (db.select(db.playlistEntries)
          ..where((e) => e.playlistId.equals(id))
          ..orderBy([(e) => OrderingTerm.asc(e.position)]))
        .get();
    return [for (final e in rows) e.trackId];
  }

  Future<List<OutboxRow>> queue() =>
      (db.select(db.outbox)..orderBy([(o) => OrderingTerm.asc(o.id)])).get();

  Map<String, dynamic> payload(OutboxRow r) =>
      (jsonDecode(r.payloadJson) as Map).cast<String, dynamic>();

  group('create', () {
    test('appears at once with its songs, owner and length', () async {
      final id = await playlists.create('Road trip', trackIds: ['t1', 't3']);

      expect(PlaylistMutations.isLocalId(id), isTrue);
      final p = (await row(id))!;
      expect(p.name, 'Road trip');
      expect(p.owner, 'marwa');
      expect(p.songCount, 2);
      expect(p.durationSec, 400);
      expect(p.readonly, isFalse);
      expect(await entries(id), ['t1', 't3']);
      expect(queued, 1);

      final op = (await queue()).single;
      expect(op.kind, OutboxKind.playlistCreate);
      expect(payload(op)['songIds'], ['t1', 't3']);
      expect(payload(op)['localId'], id);
    });

    test('a blank name becomes "New playlist"; two creates get two ids',
        () async {
      final a = await playlists.create('   ');
      final b = await playlists.create('Second');
      expect(a, isNot(b));
      expect((await row(a))!.name, 'New playlist');
    });

    test('delivery replaces the local id by the server id everywhere',
        () async {
      final id = await playlists.create('Road trip', trackIds: ['t1']);
      // The user keeps editing before the create reached the server.
      await db.into(db.pins).insert(PinsCompanion.insert(
            serverId: serverId,
            targetType: 'playlist',
            targetId: id,
            createdAtMs: 0,
          ));
      await playlists.addTracks(id, ['t2']);
      serverEntries = ['t1'];

      final delivered = await outbox.flush();

      expect(delivered, 2, reason: 'create, then the queued add');
      expect(await row(id), isNull);
      expect(await entries('srv-1'), ['t1', 't2']);
      expect((await row('srv-1'))!.name, 'Road trip');
      final pin = await db.select(db.pins).getSingle();
      expect(pin.targetId, 'srv-1');
      // The add went to the *server* id.
      final update = adapter.requests.firstWhere(
        (r) => r.apiMethod == 'updatePlaylist',
      );
      expect(update.param('playlistId'), 'srv-1');
      expect(update.params['songIdToAdd'], ['t2']);
      expect(await queue(), isEmpty);
    });

    test('a server that does not return the id: found by name in the list',
        () async {
      adapter.routes['createPlaylist'] =
          (_) => FakeResponse.json(subsonicOk({}));
      adapter.routes['getPlaylists'] = (_) => FakeResponse.json(subsonicOk({
            'playlists': {
              'playlist': [
                FakeSubsonicServer.playlist('older', 'Road trip',
                    songIds: ['t1']),
                {
                  ...FakeSubsonicServer.playlist('srv-9', 'Road trip',
                      songIds: ['t1']),
                  'created': '2026-10-15T12:00:00Z',
                },
              ],
            },
          }));
      final id = await playlists.create('Road trip', trackIds: ['t1']);

      await outbox.flush();

      expect(await row(id), isNull);
      expect(await row('srv-9'), isNotNull);
      expect(await entries('srv-9'), ['t1']);
    });

    test('a server that does not return the id and shows nothing: forgotten',
        () async {
      adapter.routes['createPlaylist'] =
          (_) => FakeResponse.json(subsonicOk({}));
      adapter.routes['getPlaylists'] = (_) => FakeResponse.json(subsonicOk({
            'playlists': {'playlist': <Object>[]},
          }));
      final id = await playlists.create('Road trip', trackIds: ['t1']);
      await playlists.addTracks(id, ['t2']);

      await outbox.flush();

      expect(await row(id), isNull,
          reason: 'the next sync brings the real one');
      expect(await entries(id), isEmpty);
      expect(await queue(), isEmpty);
    });

    test('a sync that already fetched the new playlist does not clash',
        () async {
      final id = await playlists.create('Road trip', trackIds: ['t1']);
      // The server already lists it (a sync ran between create and adoption).
      await db.into(db.playlists).insert(PlaylistsCompanion.insert(
            serverId: serverId,
            id: 'srv-1',
            name: 'Road trip',
          ));
      await db.into(db.playlistEntries).insert(PlaylistEntriesCompanion.insert(
            serverId: serverId,
            playlistId: 'srv-1',
            position: 0,
            trackId: 't1',
          ));

      await outbox.flush();

      expect(await row(id), isNull);
      expect(await entries('srv-1'), ['t1']);
      expect(await db.select(db.playlists).get(), hasLength(1));
    });
  });

  group('creating twice by accident (the phone was killed mid-delivery)', () {
    // The create reaches the server, then the process dies before the phone
    // records the new id and removes the queued row. On the next start the row
    // is still there. Sending it again made a SECOND playlist on the server and
    // corrupted the alias (docs/23, B2).
    String created(int minutesAfterQueued) => DateTime.utc(2026, 10, 15, 12)
        .add(Duration(minutes: minutesAfterQueued))
        .toIso8601String();

    void serverLists(List<Map<String, Object?>> lists) {
      adapter.routes['getPlaylists'] = (_) => FakeResponse.json(subsonicOk({
            'playlists': {'playlist': lists},
          }));
    }

    Map<String, Object?> listed(String id, String name, String created) => {
          ...FakeSubsonicServer.playlist(id, name, songIds: ['t1']),
          'created': created,
        };

    test('a create that already reached the server is adopted, not repeated',
        () async {
      final id = await playlists.create('Road trip', trackIds: ['t1']);
      serverLists([listed('srv-1', 'Road trip', created(1))]);

      await outbox.flush();

      expect(adapter.count('createPlaylist'), 0,
          reason: 'it exists already: adopt it');
      expect(await row(id), isNull);
      expect(await row('srv-1'), isNotNull);
      expect(await queue(), isEmpty);
    });

    test('an older playlist with the same name is not mistaken for it',
        () async {
      final id = await playlists.create('Road trip', trackIds: ['t1']);
      serverLists([listed('old', 'Road trip', '2026-09-01T00:00:00Z')]);

      await outbox.flush();

      expect(adapter.count('createPlaylist'), 1,
          reason: 'that playlist is from before this one was queued');
      expect(await row('old'), isNull);
      expect(await row(id), isNull, reason: 'adopted as the created one');
    });

    test('a playlist already adopted for another local one is not taken twice',
        () async {
      final first = await playlists.create('Mix', trackIds: ['t1']);
      serverLists([listed('srv-1', 'Mix', created(1))]);
      await outbox.flush(); // adopts srv-1 for [first]
      expect(await row('srv-1'), isNotNull);
      expect(await row(first), isNull);

      // A second playlist, same name and same song, created on purpose.
      adapter.requests.clear();
      adapter.routes['createPlaylist'] = (_) => FakeResponse.json(subsonicOk({
            'playlist': {'id': 'srv-2', 'name': 'Mix'},
          }));
      final second = await playlists.create('Mix', trackIds: ['t1']);
      await outbox.flush();

      expect(adapter.count('createPlaylist'), 1,
          reason: 'srv-1 belongs to the first one: a new playlist is made');
      expect(await row('srv-2'), isNotNull);
      expect(await row(second), isNull);
      expect(await row('srv-1'), isNotNull, reason: 'the first one is intact');
    });

    test('an adoption that survived a kill is recognised, nothing is resent',
        () async {
      await playlists.create('Road trip', trackIds: ['t1']);
      final queuedRow = (await queue()).single;
      await outbox.flush(); // created, adopted as srv-1, row removed

      // The kill happened before the row was removed: it is still queued.
      await db.into(db.outbox).insert(OutboxCompanion.insert(
            serverId: serverId,
            kind: queuedRow.kind,
            payloadJson: queuedRow.payloadJson,
            createdAtMs: queuedRow.createdAtMs,
          ));
      adapter.requests.clear();

      await outbox.flush();

      expect(adapter.requests, isEmpty,
          reason: 'the alias proves it was delivered: no request at all');
      expect(await queue(), isEmpty);
      expect(await row('srv-1'), isNotNull);
    });
  });

  group('add', () {
    late String id;
    setUp(() async {
      id = await playlists.create('Mix', trackIds: ['t1', 't2']);
      await outbox.flush(); // delivered and adopted as srv-1
      id = 'srv-1';
      adapter.requests.clear();
      queued = 0;
    });

    test('appends in order and updates count and length', () async {
      final ok = await playlists.addTracks(id, ['t5', 't6']);

      expect(ok, isTrue);
      expect(await entries(id), ['t1', 't2', 't5', 't6']);
      final p = (await row(id))!;
      expect(p.songCount, 4);
      expect(p.durationSec, 100 + 200 + 500 + 600);
    });

    test('several quick additions travel as one request', () async {
      await playlists.addTracks(id, ['t3']);
      await playlists.addTracks(id, ['t4']);
      await playlists.addTracks(id, ['t5']);

      expect(await queue(), hasLength(3), reason: 'queued one by one');
      expect(await outbox.flush(), 3);
      expect(adapter.count('updatePlaylist'), 1);
      expect(adapter.requests.single.params['songIdToAdd'], ['t3', 't4', 't5']);
      expect(await queue(), isEmpty);
    });

    test('an edit queued while the batch is being sent is not lost', () async {
      await playlists.addTracks(id, ['t3']);
      // The first request is "in flight" when the user adds another song.
      var requests = 0;
      adapter.routes['updatePlaylist'] = (r) async {
        if (++requests == 1) await playlists.addTracks(id, ['t5']);
        return FakeResponse.json(subsonicOk({}));
      };

      await outbox.flush();

      expect(adapter.count('updatePlaylist'), 2);
      expect(adapter.requests.first.params['songIdToAdd'], ['t3']);
      expect(adapter.requests.last.params['songIdToAdd'], ['t5']);
      expect(await queue(), isEmpty);
    });

    test('a removal between additions is not reordered', () async {
      await playlists.addTracks(id, ['t3']);
      await playlists.removeAt(id, 0);
      await playlists.addTracks(id, ['t4']);
      serverEntries = ['t1', 't2'];

      await outbox.flush();

      final updates =
          adapter.requests.where((r) => r.apiMethod == 'updatePlaylist');
      expect(updates, hasLength(3));
    });

    test('a playlist the server generates cannot be edited', () async {
      await db.into(db.playlists).insert(PlaylistsCompanion.insert(
            serverId: serverId,
            id: 'smart',
            name: 'Phone Offline',
            readonly: const Value(true),
          ));
      expect(await playlists.addTracks('smart', ['t1']), isFalse);
      expect(await playlists.rename('smart', 'x'), isFalse);
      expect(await playlists.removeAt('smart', 0), isFalse);
      expect(await entries('smart'), isEmpty);
    });

    test('an unknown or deleted playlist is refused', () async {
      expect(await playlists.addTracks('nope', ['t1']), isFalse);
      await playlists.delete(id);
      expect(await playlists.addTracks(id, ['t1']), isFalse);
    });
  });

  group('remove', () {
    late String id;
    setUp(() async {
      id = await playlists.create('Mix', trackIds: ['t1', 't2', 't3', 't4']);
      await outbox.flush();
      id = 'srv-1';
      adapter.requests.clear();
    });

    test('closes the gap and shortens the playlist', () async {
      expect(await playlists.removeAt(id, 1), isTrue);

      expect(await entries(id), ['t1', 't3', 't4']);
      final p = (await row(id))!;
      expect(p.songCount, 3);
      expect(p.durationSec, 100 + 300 + 400);
    });

    test('removing several keeps positions contiguous', () async {
      await playlists.removeAt(id, 0);
      await playlists.removeAt(id, 0);
      await playlists.removeAt(id, 1);

      expect(await entries(id), ['t3']);
      final positions = (await db.select(db.playlistEntries).get())
          .map((e) => e.position)
          .toList();
      expect(positions, [0]);
    });

    test('an out-of-range position changes nothing', () async {
      expect(await playlists.removeAt(id, 9), isFalse);
      expect(await entries(id), ['t1', 't2', 't3', 't4']);
      expect(await queue(), isEmpty);
    });

    test('delivery finds the song by id even if the server list moved',
        () async {
      await playlists.removeAt(id, 2); // t3 sat at index 2 on the phone
      // Elsewhere the playlist was reordered: t3 is now at index 0.
      serverEntries = ['t3', 't1', 't2', 't4'];

      await outbox.flush();

      final update =
          adapter.requests.firstWhere((r) => r.apiMethod == 'updatePlaylist');
      expect(update.params['songIndexToRemove'], ['0']);
    });

    test('a song already removed elsewhere is not removed twice', () async {
      await playlists.removeAt(id, 2);
      serverEntries = ['t1', 't2', 't4'];

      await outbox.flush();

      expect(adapter.count('updatePlaylist'), 0,
          reason: 'nothing left to change on the server');
      expect(await queue(), isEmpty);
    });
  });

  group('rename and delete', () {
    late String id;
    setUp(() async {
      id = await playlists.create('Mix', trackIds: ['t1']);
      await outbox.flush();
      id = 'srv-1';
      adapter.requests.clear();
    });

    test('rename is local at once and delivered', () async {
      expect(await playlists.rename(id, '  Road trip  '), isTrue);
      expect((await row(id))!.name, 'Road trip');

      await outbox.flush();
      expect(adapter.requests.single.param('name'), 'Road trip');
    });

    test('an empty name is rejected', () async {
      expect(await playlists.rename(id, '   '), isFalse);
      expect((await row(id))!.name, 'Mix');
    });

    test('delete tombstones, drops pins and queues the server call', () async {
      await db.into(db.pins).insert(PinsCompanion.insert(
            serverId: serverId,
            targetType: 'playlist',
            targetId: id,
            createdAtMs: 0,
          ));
      await playlists.addTracks(id, ['t2']); // a pending edit: now moot

      await playlists.delete(id);

      expect((await row(id))!.deletedAtMs, isNotNull);
      expect(await db.select(db.pins).get(), isEmpty);
      final q = await queue();
      expect(q.map((o) => o.kind), [OutboxKind.playlistDelete]);

      await outbox.flush();
      expect(adapter.requests.single.apiMethod, 'deletePlaylist');
      expect(adapter.requests.single.param('id'), 'srv-1');
    });

    test('a playlist the server never heard of is simply forgotten', () async {
      final local = await playlists.create('Scratch', trackIds: ['t1']);
      await playlists.addTracks(local, ['t2']);

      await playlists.delete(local);

      expect(await row(local), isNull);
      expect(await entries(local), isEmpty);
      expect(await queue(), isEmpty);
      await outbox.flush();
      expect(adapter.count('createPlaylist'), 0);
      expect(adapter.count('deletePlaylist'), 0);
    });
  });

  group('pending edits', () {
    test('ids with undelivered edits are reported', () async {
      final a = await playlists.create('A', trackIds: ['t1']);
      await outbox.flush();
      await playlists.addTracks('srv-1', ['t2']);
      final b = await playlists.create('B');

      final ids = await PlaylistMutations.pendingPlaylistIds(db, serverId);
      expect(ids, {'srv-1', b});
      expect(ids, isNot(contains(a)));
    });
  });

  group('resolveRemovalIndexes', () {
    test('matches by id, nearest occurrence to the hint', () {
      final idx = resolveRemovalIndexes(
        serverTrackIds: ['a', 'b', 'a', 'c', 'a'],
        wantedIds: ['a'],
        hints: [4],
      );
      expect(idx, [4]);
    });

    test('two removals of the same song take different occurrences', () {
      final idx = resolveRemovalIndexes(
        serverTrackIds: ['a', 'b', 'a'],
        wantedIds: ['a', 'a'],
        hints: [0, 2],
      );
      expect(idx, [0, 2]);
    });

    test('missing songs are skipped and the result is sorted', () {
      final idx = resolveRemovalIndexes(
        serverTrackIds: ['x', 'y', 'z'],
        wantedIds: ['z', 'gone', 'x'],
        hints: [2, 5, 0],
      );
      expect(idx, [0, 2]);
    });
  });
}
