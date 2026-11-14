import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:drift/native.dart';
import 'package:encore/core/clock.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/encore/encore_api.dart';
import 'package:encore/data/encore/encore_sync.dart';
import 'package:encore/data/repos/release_store.dart';
import 'package:encore/data/sync/outbox.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_encore_server.dart';

const _pl1 = 'pl_11111111111111111111111111';
String _pe(String c) => 'pe_${c * 26}';

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
      clock: FakeClock(DateTime.utc(2026, 10, 22, 12)),
      pageLimit: 3,
    );
  });

  tearDown(() => db.close());

  Future<List<TrackRow>> live() => (db.select(db.tracks)
        ..where((t) => t.deletedAtMs.isNull())
        ..orderBy([(t) => OrderingTerm.asc(t.title)]))
      .get();

  Future<TrackRow> track(String id) =>
      (db.select(db.tracks)..where((t) => t.id.equals(id))).getSingle();

  group('saved releases (D-35)', () {
    test(
        'a release saved on the server is remembered by the phone, so it still says "In your library" after a restart or on a second phone',
        () async {
      server.savedReleases['cat:100'] = ['sr_1'];

      await sync.pull();

      expect(await ReleaseStore(db, serverId).saved(), {'cat:100'},
          reason: 'a fresh store over the same database is a restart');
    });
  });

  group('the server\'s files', () {
    test(
        'a song shows the picture the server found for it; a file whose picture was not found keeps the music server\'s own',
        () async {
      const url = 'https://cdn-images.dzcdn.net/images/cover/abc/1000x1000.jpg';
      final found = server.addRef('Nude', 'Radiohead',
          album: 'In Rainbows', fileId: 'nd-1', meta: {'coverArt': 'al-1'});
      server.refs[found]!['coverUrl'] = url;
      final plain = server.addRef('Reckoner', 'Radiohead',
          album: 'In Rainbows', fileId: 'nd-2', meta: {'coverArt': 'al-1'});
      final streamed = server.addRef('Videotape', 'Radiohead');
      server.refs[streamed]!['coverUrl'] = url;
      server.otherDeviceLikes(streamed);

      await sync.pull();

      expect((await track(found)).coverArt, url);
      expect((await track(plain)).coverArt, 'al-1');
      expect((await track(streamed)).coverArt, url);
    });

    test(
        'a first pass writes every song the server keeps, with the music server\'s ids, in pages',
        () async {
      for (var i = 1; i <= 7; i++) {
        server.addRef('Song $i', 'Artist',
            album: 'Album',
            fileId: 'nd-$i',
            meta: {
              'albumId': 'al-1',
              'artistId': 'ar-1',
              'coverArt': 'al-1',
              'size': 1000 + i,
              'suffix': 'opus'
            });
      }

      final stats = (await sync.pull()).getOrThrow();

      expect(stats.files, 7);
      expect(server.calls['GET library/files'],
          3 + 1 /* the changes feed's twin */ - 1,
          reason: '7 songs, 3 a page');
      final rows = await live();
      expect(rows, hasLength(7));
      final first = rows.first;
      expect(first.isRef, isTrue);
      expect(first.id, startsWith('sr_'));
      expect(first.fileId, startsWith('nd-'));
      expect((first.albumId, first.artistId, first.coverArt, first.suffix),
          ('al-1', 'ar-1', 'al-1', 'opus'));
    });

    test(
        'then only what changed: a new song, a replaced file, a file that is gone',
        () async {
      final a = server.addRef('A', 'X', fileId: 'nd-1', meta: {'size': 1});
      final b = server.addRef('B', 'X', fileId: 'nd-2');
      await sync.pull();

      server.addRef('C', 'X', fileId: 'nd-3');
      server.attachFile(a, 'nd-1b', meta: {'size': 2});
      server.removeFile(b);
      final stats = (await sync.pullFiles()).getOrThrow();

      expect(stats.files, 3);
      expect((await track(a)).fileId, 'nd-1b');
      expect((await live()).map((t) => t.title), ['A', 'C'],
          reason: 'B has no file and nobody uses it: it leaves the index');
      expect((await sync.pullFiles()).getOrThrow().files, 0);
    });

    test('a song whose file is gone stays when a person uses it', () async {
      final a = server.addRef('A', 'X', fileId: 'nd-1');
      final liked = server.addRef('Liked', 'X', fileId: 'nd-2');
      await sync.pull();
      server.otherDeviceLikes(liked);
      await sync.pullChanges();

      server.removeFile(a);
      server.removeFile(liked);
      await sync.pullFiles();

      final rows = await live();
      expect(rows.map((t) => t.title), ['Liked']);
      expect(rows.single.fileId, isNull,
          reason: 'it plays from the server\'s stream instead');
      expect(rows.single.starredAtMs, isNotNull);
    });

    test('the audio key changes with the file, not with a tag edit', () async {
      final a = server.addRef('A', 'X',
          fileId: 'nd-1', meta: {'size': 100, 'suffix': 'opus'});
      await sync.pull();
      final before = (await track(a)).audioKey;

      server.attachFile(a, 'nd-1',
          meta: {'size': 100, 'suffix': 'opus', 'genre': 'Rock'});
      await sync.pullFiles();
      final afterTag = (await track(a)).audioKey;
      server.attachFile(a, 'nd-1', meta: {'size': 250, 'suffix': 'opus'});
      await sync.pullFiles();
      final afterFile = (await track(a)).audioKey;

      expect(afterTag, before);
      expect(afterFile, isNot(before));
    });
  });

  group('the person\'s library', () {
    test(
        'likes arrive with the songs they name, including songs the server keeps no file of',
        () async {
      final owned = server.addRef('Owned', 'X', fileId: 'nd-1');
      final streamed = server.addRef('Streamed', 'Y');
      server.otherDeviceLikes(owned);
      server.otherDeviceLikes(streamed);

      final stats = (await sync.pullChanges()).getOrThrow();

      expect(stats.likes, 2);
      expect((await track(owned)).starredAtMs, isNotNull);
      final loose = await track(streamed);
      expect(loose.starredAtMs, isNotNull);
      expect((loose.fileId, loose.albumId, loose.isRef), (null, null, true));
    });

    test(
        'an unlike on another device clears the heart, and the song nobody uses any more leaves the index',
        () async {
      final streamed = server.addRef('Streamed', 'Y');
      server.otherDeviceLikes(streamed);
      await sync.pull();
      await (db.delete(db.downloads)).go();

      await server.call('DELETE', '/encore/api/v1/likes/$streamed');
      await sync.pullChanges();

      expect((await track(streamed)).deletedAtMs, isNotNull);
      expect(await live(), isEmpty);
    });

    test(
        'a like that is still waiting in the outbox is not undone by what the server last knew',
        () async {
      final id = server.addRef('A', 'X', fileId: 'nd-1');
      server.otherDeviceLikes(id);
      await sync.pull();
      await (db.update(db.tracks))
          .write(const TracksCompanion(starredAtMs: Value(null)));
      await db.into(db.outbox).insert(OutboxCompanion.insert(
            serverId: serverId,
            kind: OutboxKind.unstar,
            payloadJson: jsonEncode({
              'songIds': [id]
            }),
            createdAtMs: 1,
          ));
      server.attachFile(id, 'nd-1b'); // touches the like again

      await sync.pullChanges();

      expect((await track(id)).starredAtMs, isNull,
          reason: 'the person unliked it here; that is not sent yet');
    });

    test(
        'playlists arrive with their entries in the server\'s order, counted 0..n-1, and a move on another device reorders them',
        () async {
      final a =
          server.addRef('A', 'X', fileId: 'nd-1', meta: {'albumId': 'al-1'});
      final b = server.addRef('B', 'X');
      final c = server.addRef('C', 'X');
      await server.call('POST', '/encore/api/v1/playlists',
          {'id': _pl1, 'name': 'Road trip'});
      await server.call('POST', '/encore/api/v1/playlists/$_pl1/entries', {
        'songs': [
          {'ref': a, 'id': _pe('a')},
          {'ref': b, 'id': _pe('b')},
          {'ref': c, 'id': _pe('c')},
        ],
      });

      await sync.pullChanges();

      var rows = await (db.select(db.playlistEntries)
            ..orderBy([(e) => OrderingTerm.asc(e.position)]))
          .get();
      expect([for (final r in rows) (r.position, r.trackId, r.entryId)],
          [(0, a, _pe('a')), (1, b, _pe('b')), (2, c, _pe('c'))]);
      final playlist = await (db.select(db.playlists)
            ..where((p) => p.id.equals(_pl1)))
          .getSingle();
      expect((
        playlist.name,
        playlist.owner,
        playlist.songCount,
        playlist.readonly
      ), (
        'Road trip',
        'tester',
        3,
        false
      ));

      await server.call('PUT', '/encore/api/v1/playlists/$_pl1/order', {
        'entryIds': [_pe('c'), _pe('a'), _pe('b')]
      });
      await sync.pullChanges();

      rows = await (db.select(db.playlistEntries)
            ..orderBy([(e) => OrderingTerm.asc(e.position)]))
          .get();
      expect(rows.map((r) => r.trackId), [c, a, b]);
    });

    test(
        'an entry removed on another device disappears, a deleted playlist is tombstoned with its entries',
        () async {
      final a = server.addRef('A', 'X', fileId: 'nd-1');
      final b = server.addRef('B', 'X', fileId: 'nd-2');
      await server.call(
          'POST', '/encore/api/v1/playlists', {'id': _pl1, 'name': 'Mix'});
      await server.call('POST', '/encore/api/v1/playlists/$_pl1/entries', {
        'songs': [
          {'ref': a, 'id': _pe('a')},
          {'ref': b, 'id': _pe('b')},
        ],
      });
      await sync.pull();

      await server.call('DELETE', '/encore/api/v1/playlists/$_pl1/entries', {
        'entryIds': [_pe('a')]
      });
      await sync.pullChanges();
      expect((await db.select(db.playlistEntries).get()).map((e) => e.trackId),
          [b]);
      expect(
          (await (db.select(db.playlists)..where((p) => p.id.equals(_pl1)))
                  .getSingle())
              .songCount,
          1);

      await server.call('DELETE', '/encore/api/v1/playlists/$_pl1');
      await sync.pullChanges();
      expect(await db.select(db.playlistEntries).get(), isEmpty);
      expect(
          (await (db.select(db.playlists)..where((p) => p.id.equals(_pl1)))
                  .getSingle())
              .deletedAtMs,
          isNotNull);
    });

    test('the same pull twice changes nothing and asks only for what is new',
        () async {
      final a = server.addRef('A', 'X', fileId: 'nd-1');
      server.otherDeviceLikes(a);
      await sync.pull();
      final before = (await db.select(db.tracks).get()).length;

      final again = (await sync.pull()).getOrThrow();

      expect(again.changed, 0);
      expect((await db.select(db.tracks).get()).length, before);
    });

    test(
        'a server that cannot be reached is a failure to report, and nothing is half written',
        () async {
      server.addRef('A', 'X', fileId: 'nd-1');
      server.online = false;

      final result = await sync.pull();

      expect(result.isErr, isTrue);
      expect(await db.select(db.tracks).get(), isEmpty);
      server.online = true;
      expect((await sync.pull()).getOrThrow().files, 1);
    });

    test('reset makes the next pull read everything again', () async {
      server.addRef('A', 'X', fileId: 'nd-1');
      await sync.pull();

      await sync.reset();

      expect((await sync.pull()).getOrThrow().files, 1);
    });
  });

  // P2-28 / B-61: docs/34 rule 5 says what waits in the outbox is never overwritten by a pull. Likes had that; playlist edits did not.
  group('a playlist edit that is still waiting is not undone by a pull (P2-28)',
      () {
    Future<void> seedRoadTrip() async {
      final a = server.addRef('A', 'X', fileId: 'nd-1');
      final b = server.addRef('B', 'X');
      await server.call('POST', '/encore/api/v1/playlists',
          {'id': _pl1, 'name': 'Road trip'});
      await server.call('POST', '/encore/api/v1/playlists/$_pl1/entries', {
        'songs': [
          {'ref': a, 'id': _pe('a')},
          {'ref': b, 'id': _pe('b')},
        ],
      });
      await sync.pullChanges();
    }

    Future<void> queue(String kind, Map<String, Object?> payload) =>
        db.into(db.outbox).insert(OutboxCompanion.insert(
              serverId: serverId,
              kind: kind,
              payloadJson: jsonEncode(payload),
              createdAtMs: 1,
            ));

    Future<PlaylistRow> playlist() => (db.select(db.playlists)
          ..where((p) => p.serverId.equals(serverId) & p.id.equals(_pl1)))
        .getSingle();

    Future<List<String>> entryIds() async => [
          for (final e in await (db.select(db.playlistEntries)
                ..orderBy([(e) => OrderingTerm.asc(e.position)]))
              .get())
            e.entryId ?? '',
        ];

    // Another device touches the playlist (it adds a song), so the feed brings the playlist row again, with the name the server has.
    Future<void> anotherDeviceAddsASong({String letter = 'c'}) async {
      final c = server.addRef(letter.toUpperCase(), 'X');
      await server.call('POST', '/encore/api/v1/playlists/$_pl1/entries', {
        'songs': [
          {'ref': c, 'id': _pe(letter)},
        ],
      });
    }

    test(
        'a rename that is still waiting keeps the new name, and a song added on another device still arrives',
        () async {
      await seedRoadTrip();
      await (db.update(db.playlists)..where((p) => p.id.equals(_pl1)))
          .write(const PlaylistsCompanion(name: Value('Summer')));
      await queue('e.playlist.rename', {'playlistId': _pl1, 'name': 'Summer'});
      await anotherDeviceAddsASong();

      await sync.pullChanges();

      expect((await playlist()).name, 'Summer',
          reason: 'the person renamed it here; that is not sent yet');
      expect(await entryIds(), [_pe('a'), _pe('b'), _pe('c')],
          reason: 'the pull is not skipped as a whole');
    });

    test(
        'once the rename was delivered, the name the server has is the name (nothing keeps the old one)',
        () async {
      await seedRoadTrip();
      await (db.update(db.playlists)..where((p) => p.id.equals(_pl1)))
          .write(const PlaylistsCompanion(name: Value('Summer')));
      await queue('e.playlist.rename', {'playlistId': _pl1, 'name': 'Summer'});
      await server
          .call('PATCH', '/encore/api/v1/playlists/$_pl1', {'name': 'Winter'});
      await (db.delete(db.outbox))
          .go(); // delivered, then renamed again elsewhere

      await sync.pullChanges();

      expect((await playlist()).name, 'Winter');
    });

    test(
        'a delete that is still waiting does not bring the playlist back, and a parked one does not hold it',
        () async {
      await seedRoadTrip();
      await (db.update(db.playlists)..where((p) => p.id.equals(_pl1)))
          .write(const PlaylistsCompanion(deletedAtMs: Value(5)));
      await queue('e.playlist.delete', {'id': _pl1});
      await anotherDeviceAddsASong();

      await sync.pullChanges();

      expect((await playlist()).deletedAtMs, isNotNull,
          reason: 'the person deleted it here; that is not sent yet');

      // A turned-down edit stops protecting: the server's truth shows.
      await (db.update(db.outbox))
          .write(const OutboxCompanion(status: Value('failed')));
      await anotherDeviceAddsASong(letter: 'd');
      await sync.pullChanges();
      expect((await playlist()).deletedAtMs, isNull);
    });

    test(
        'a removal that is still waiting does not put the song back, and the other songs stay',
        () async {
      await seedRoadTrip();
      await (db.delete(db.playlistEntries)
            ..where((e) => e.entryId.equals(_pe('b'))))
          .go();
      await queue('e.playlist.remove', {
        'playlistId': _pl1,
        'entryIds': [_pe('b')],
      });
      // Another device moves the songs about, so the feed brings every entry of the playlist again, the removed one with them.
      await server.call('PUT', '/encore/api/v1/playlists/$_pl1/order', {
        'entryIds': [_pe('b'), _pe('a')]
      });

      await sync.pullChanges();

      expect(await entryIds(), [_pe('a')],
          reason: 'the person removed it here; that is not sent yet');
    });
  });
}
