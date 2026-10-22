import 'dart:async';

import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:drift/native.dart';
import 'package:encore/core/clock.dart';
import 'package:encore/core/result.dart';
import 'package:encore/data/api/opensubsonic/opensubsonic_client.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/sync/playlist_mutations.dart';
import 'package:encore/data/sync/sync_engine.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_http.dart';
import '../../support/fake_subsonic_server.dart';

void main() {
  late AppDatabase db;
  late FakeSubsonicServer server;
  late FakeClock clock;
  late SyncEngine engine;
  late int serverId;

  setUp(() async {
    db = AppDatabase(NativeDatabase.memory());
    serverId = await db.into(db.servers).insert(ServersCompanion.insert(
          name: 'Test',
          username: 'tester',
          endpointsJson: '[]',
          createdAtMs: 0,
        ));
    server = FakeSubsonicServer()..seed(songCount: 30, albumCount: 3);
    clock = FakeClock(DateTime.utc(2026, 10, 14, 12));
    engine = _engine(db, server, serverId, clock);
  });

  tearDown(() async {
    await engine.dispose();
    await db.close();
  });

  Future<List<TrackRow>> liveTracks() => (db.select(db.tracks)
        ..where((t) => t.deletedAtMs.isNull())
        ..orderBy([(t) => OrderingTerm.asc(t.id)]))
      .get();

  Future<SyncStats> runOk({SyncReason reason = SyncReason.manual}) async {
    final outcome = await engine.run(reason: reason);
    expect(outcome, isA<SyncCompleted>(), reason: '$outcome');
    return (outcome as SyncCompleted).stats;
  }

  group('first sync', () {
    test('imports artists, albums and all songs in pages', () async {
      server.seed(songCount: 1203, albumCount: 7);
      final stats = await runOk();

      expect(stats.libraryPhaseRan, isTrue);
      expect(stats.tracks, 1203);
      expect((await db.select(db.tracks).get()), hasLength(1203));
      expect((await db.select(db.albums).get()), hasLength(7));
      expect((await db.select(db.artists).get()), hasLength(1));
      // 1203 songs / 500 per page = 3 pages (500, 500, 203).
      expect(server.adapter.count('search3'), 3);
      expect(server.adapter.count('getArtists'), 1);
    });

    test('request budget: probe + dump + volatile only', () async {
      await runOk();
      final methods = server.adapter.requests.map((r) => r.apiMethod).toSet();
      expect(
        methods,
        {
          'getScanStatus',
          'getArtists',
          'getAlbumList2',
          'search3',
          'getPlaylists',
          'getStarred2',
        },
      );
    });
  });

  group('incremental sync', () {
    test('no server change -> probe and volatile phase only', () async {
      await runOk();
      server.adapter.requests.clear();

      final stats = await runOk(reason: SyncReason.resume);

      expect(stats.libraryPhaseRan, isFalse);
      expect(server.adapter.count('search3'), 0);
      expect(server.adapter.count('getAlbumList2'), 0);
      expect(server.adapter.count('getScanStatus'), 1);
      expect(server.adapter.requests.length, lessThanOrEqualTo(3));
    });

    test('a server-side change is picked up and updates rows in place',
        () async {
      await runOk();
      server.songs[0] = FakeSubsonicServer.song(0, title: 'Renamed on server');
      server.songs.add(FakeSubsonicServer.song(100, album: 1));
      server.lastScan = '2026-10-14T13:00:00.000000000Z';
      clock.advance(const Duration(
          hours: 2)); // later than the gap between library passes

      final stats = await runOk(reason: SyncReason.scheduled);

      expect(stats.libraryPhaseRan, isTrue);
      final tracks = await liveTracks();
      expect(tracks, hasLength(31));
      expect(tracks.firstWhere((t) => t.id == 's0').title, 'Renamed on server');
    });

    group('the sync storm guard (H38, P1-14)', () {
      setUp(() async {
        await runOk();
        // Somebody's import kept a song: the server's scan time moved.
        server.songs.add(FakeSubsonicServer.song(100, album: 1));
        server.lastScan = '2026-10-14T12:05:00.000000000Z';
        server.adapter.requests.clear();
      });

      test(
          'a scan that moved a minute after the last pass does not download the library again',
          () async {
        clock.advance(const Duration(minutes: 1));

        final stats = await runOk(reason: SyncReason.scheduled);

        expect(stats.libraryPhaseRan, isFalse);
        expect(server.adapter.count('search3'), 0);
        expect(server.adapter.count('getAlbumList2'), 0);
        expect(await liveTracks(), hasLength(30),
            reason: 'the new song waits for the next pass');
      });

      test('after an hour the pass is done', () async {
        clock.advance(const Duration(hours: 1, minutes: 1));

        final stats = await runOk(reason: SyncReason.scheduled);

        expect(stats.libraryPhaseRan, isTrue);
        expect(await liveTracks(), hasLength(31));
      });

      test('on mobile data the gap is six hours', () async {
        engine.metered = true;
        clock.advance(const Duration(hours: 5));
        expect((await runOk(reason: SyncReason.scheduled)).libraryPhaseRan,
            isFalse);

        clock.advance(const Duration(hours: 2));
        expect((await runOk(reason: SyncReason.scheduled)).libraryPhaseRan,
            isTrue);
      });

      test('a pull to refresh ignores the gap', () async {
        clock.advance(const Duration(minutes: 1));

        final stats = await runOk(reason: SyncReason.manual);

        expect(stats.libraryPhaseRan, isTrue);
        expect(await liveTracks(), hasLength(31));
      });

      test('the cheap probe does not ask for a pass inside the gap', () async {
        clock.advance(const Duration(minutes: 1));

        expect(await engine.probe(), isNot(isA<ProbeNeedsFullPass>()));

        clock.advance(const Duration(hours: 2));
        expect(await engine.probe(), isA<ProbeNeedsFullPass>());
      });

      test('fifty-nine scans in the first hour cost no second library pass',
          () async {
        var passes = 0;
        for (var minute = 1; minute <= 59; minute++) {
          clock.advance(const Duration(minutes: 1));
          server.lastScan =
              '2026-10-14T12:${minute.toString().padLeft(2, '0')}:30.000000000Z';
          final stats = await runOk(reason: SyncReason.scheduled);
          if (stats.libraryPhaseRan) passes++;
        }
        expect(passes, 0, reason: 'the first hour has no second pass');
      });
    });

    test('periodic verification even when the server claims no change',
        () async {
      await runOk();
      clock.advance(const Duration(hours: 25));
      server.adapter.requests.clear();

      final stats = await runOk(reason: SyncReason.scheduled);
      expect(stats.libraryPhaseRan, isTrue);
    });

    test('removed songs are tombstoned, not hard-deleted', () async {
      await runOk();
      server.songs.removeLast();
      server.lastScan = '2026-10-14T13:00:00.000000000Z';

      final stats = await runOk();

      expect(stats.tombstonedTracks, 1);
      expect(await liveTracks(), hasLength(29));
      final all = await db.select(db.tracks).get();
      expect(all, hasLength(30), reason: 'row kept for downloads / history');
      expect(all.where((t) => t.deletedAtMs != null), hasLength(1));
    });

    test('a re-appearing song is resurrected', () async {
      await runOk();
      final removed = server.songs.removeLast();
      server.lastScan = '2026-10-14T13:00:00.000000000Z';
      await runOk();
      expect(await liveTracks(), hasLength(29));

      server.songs.add(removed);
      server.lastScan = '2026-10-14T14:00:00.000000000Z';
      await runOk();
      expect(await liveTracks(), hasLength(30));
    });
  });

  group('never destroy before replacing (F-02)', () {
    test('a failing page leaves the existing library untouched', () async {
      await runOk();
      server.lastScan = '2026-10-14T13:00:00.000000000Z';
      var calls = 0;
      final original = server.adapter.routes['search3']!;
      server.adapter.routes['search3'] = (r) {
        calls++;
        return calls == 1 ? original(r) : const FakeResponse.connectionError();
      };
      server.seed(songCount: 1100, albumCount: 3); // forces 3 pages

      final outcome = await engine.run();

      expect(outcome, isA<SyncFailed>());
      expect((outcome as SyncFailed).failure.isRetryable, isTrue);
      // Old library still fully present and nothing tombstoned.
      expect(await liveTracks(), hasLength(500));
      final tombstoned = await (db.select(db.tracks)
            ..where((t) => t.deletedAtMs.isNotNull()))
          .get();
      expect(tombstoned, isEmpty);
    });

    test('shrink guard: an empty server answer never wipes the library',
        () async {
      server.seed(songCount: 120, albumCount: 3);
      await runOk();
      server.songs = [];
      server.albums = [];
      server.artists = [];
      server.lastScan = '2026-10-14T13:00:00.000000000Z';

      final stats = await runOk();

      expect(stats.shrinkGuardTripped, isTrue);
      expect(await liveTracks(), hasLength(120));
    });

    test('shrink guard can be overridden explicitly', () async {
      server.seed(songCount: 120, albumCount: 3);
      await runOk();
      server.songs = [];
      server.lastScan = '2026-10-14T13:00:00.000000000Z';

      final outcome = await engine.run(acceptShrink: true, force: true);

      expect(outcome, isA<SyncCompleted>());
      expect(await liveTracks(), isEmpty);
    });

    // B6. The guard used to trip on EVERY run after a genuine big deletion:
    // the watermark was never saved, so every 10 minutes the whole library was
    // downloaded again and never shrank. It also looked at tracks only.
    Future<SyncStats> nextRun(String scanStamp) async {
      server.lastScan = scanStamp;
      return runOk();
    }

    test(
        'a big deletion the server keeps reporting is accepted on the third '
        'identical answer', () async {
      server.seed(songCount: 100, albumCount: 5);
      await runOk();
      server.songs = server.songs.sublist(0, 40); // 40%: under the 50% guard

      final first = await nextRun('2026-10-14T13:00:00.000000000Z');
      expect(first.shrinkGuardTripped, isTrue);
      expect(await liveTracks(), hasLength(100));

      final second = await nextRun('2026-10-14T13:10:00.000000000Z');
      expect(second.shrinkGuardTripped, isTrue);
      expect(await liveTracks(), hasLength(100));

      final third = await nextRun('2026-10-14T13:20:00.000000000Z');
      expect(third.shrinkGuardTripped, isFalse);
      expect(await liveTracks(), hasLength(40),
          reason: 'the same smaller answer three times is the new truth');
    });

    test('an answer that keeps changing is never accepted', () async {
      server.seed(songCount: 100, albumCount: 5);
      await runOk();
      for (var i = 0; i < 6; i++) {
        // 30, 31, 32 ... songs: never the same answer twice in a row.
        server.songs = [
          for (var j = 0; j < 30 + i; j++)
            FakeSubsonicServer.song(j, album: j % 5),
        ];
        final stats = await nextRun('2026-10-14T13:0$i:00.000000000Z');
        expect(stats.shrinkGuardTripped, isTrue, reason: 'run $i');
      }
      expect(await liveTracks(), hasLength(100));
    });

    test('an empty answer is never accepted automatically, however often',
        () async {
      server.seed(songCount: 120, albumCount: 3);
      await runOk();
      server.songs = [];
      server.albums = [];
      server.artists = [];

      for (var i = 0; i < 6; i++) {
        final stats = await nextRun('2026-10-14T13:0$i:00.000000000Z');
        expect(stats.shrinkGuardTripped, isTrue, reason: 'run $i');
      }
      expect(await liveTracks(), hasLength(120),
          reason: 'a missing music drive must not empty the phone');
    });

    test('albums are guarded on their own, not only when the tracks shrink',
        () async {
      server.seed(songCount: 120, albumCount: 40);
      await runOk();
      // Every song still comes back, but the album list is cut short.
      server.albums = server.albums.sublist(0, 5);

      await nextRun('2026-10-14T13:00:00.000000000Z');

      final liveAlbums = await (db.select(db.albums)
            ..where((a) => a.deletedAtMs.isNull()))
          .get();
      expect(liveAlbums, hasLength(40),
          reason: 'a truncated album list must not remove the albums');
      expect(await liveTracks(), hasLength(120));
    });

    test('a server that is mid-scan does not trigger removals', () async {
      await runOk();
      server.songs.removeRange(0, 10);
      server.scanning = true;
      server.lastScan = '2026-10-14T13:00:00.000000000Z';

      await runOk();
      expect(await liveTracks(), hasLength(30));

      // Once the scan finishes the removal is applied.
      server.scanning = false;
      await runOk();
      expect(await liveTracks(), hasLength(20));
    });

    test('unreachable server -> retryable failure, library untouched',
        () async {
      await runOk();
      server.adapter.routes['getScanStatus'] =
          (_) => const FakeResponse.connectionError();

      final outcome = await engine.run(force: true);

      expect(outcome, isA<SyncFailed>());
      expect(await liveTracks(), hasLength(30));
    });

    test('wrong credentials -> non-retryable AuthFailure', () async {
      server.adapter.routes['getScanStatus'] =
          (_) => FakeResponse.json(subsonicError(40, 'Wrong password'));

      final outcome = await engine.run();

      expect(outcome, isA<SyncFailed>());
      expect((outcome as SyncFailed).failure, isA<AuthFailure>());
    });
  });

  group('downloads follow the server (R-04)', () {
    Future<void> insertDownload(String trackId) async {
      final track = await (db.select(db.tracks)
            ..where((t) => t.id.equals(trackId)))
          .getSingle();
      await db.into(db.downloads).insert(DownloadsCompanion.insert(
            serverId: serverId,
            trackId: trackId,
            state: const Value(2),
            localPath: const Value('/offline/x.mp3'),
            sourceAudioKey: Value(track.audioKey),
            updatedAtMs: 0,
          ));
    }

    test('replaced audio file marks the download stale', () async {
      await runOk();
      await insertDownload('s1');

      server.songs[1] =
          FakeSubsonicServer.song(1, size: 9999999, suffix: 'flac');
      server.lastScan = '2026-10-14T13:00:00.000000000Z';
      final stats = await runOk();

      expect(stats.staleDownloads, 1);
      final row = await (db.select(db.downloads)
            ..where((d) => d.trackId.equals('s1')))
          .getSingle();
      expect(row.stale, isTrue);
    });

    test('a tag-only edit does NOT make the download stale', () async {
      await runOk();
      await insertDownload('s2');

      server.songs[2] = FakeSubsonicServer.song(2, title: 'Typo fixed');
      server.lastScan = '2026-10-14T13:00:00.000000000Z';
      final stats = await runOk();

      expect(stats.staleDownloads, 0);
      final track = await (db.select(db.tracks)
            ..where((t) => t.id.equals('s2')))
          .getSingle();
      expect(track.title, 'Typo fixed', reason: 'DB row still updated');
    });
  });

  group('playlists', () {
    test('new playlist is fetched once; unchanged is not refetched', () async {
      server.playlists = [
        FakeSubsonicServer.playlist('p1', 'Mine',
            songIds: ['s1', 's2', 's3'], library: server.songs),
      ];
      await runOk();
      expect(server.adapter.count('getPlaylist'), 1);

      server.adapter.requests.clear();
      await runOk();
      expect(server.adapter.count('getPlaylist'), 0);

      final entries = await (db.select(db.playlistEntries)
            ..orderBy([(e) => OrderingTerm.asc(e.position)]))
          .get();
      expect(entries.map((e) => e.trackId), ['s1', 's2', 's3']);
    });

    test('a playlist whose songs could not be fetched is fetched again',
        () async {
      // The list says "changed"; the metadata is stored; the songs fetch
      // fails once. The next run used to compare the server's stamp with the
      // row it had just updated, see no difference and keep the old songs for
      // ever (docs/23, B5).
      server.playlists = [
        FakeSubsonicServer.playlist('p1', 'Mine',
            songIds: ['s1', 's2'], library: server.songs),
      ];
      await runOk();

      server.playlists = [
        FakeSubsonicServer.playlist('p1', 'Mine',
            songIds: ['s2', 's5', 's6'],
            changed: '2026-10-12T00:00:00Z',
            library: server.songs),
      ];
      final healthy = server.adapter.routes['getPlaylist']!;
      server.adapter.routes['getPlaylist'] =
          (_) => const FakeResponse.connectionError();
      await runOk();
      server.adapter.routes['getPlaylist'] = healthy;
      await runOk();

      final entries = await (db.select(db.playlistEntries)
            ..orderBy([(e) => OrderingTerm.asc(e.position)]))
          .get();
      expect(entries.map((e) => e.trackId), ['s2', 's5', 's6']);
    });

    test('a changed playlist skipped by the per-run cap is fetched next run',
        () async {
      // New playlists are retried anyway (their songs were never fetched). A
      // playlist that CHANGED while the cap was reached had its stamp stored
      // without its songs, so nothing ever fetched it again (docs/23, B5).
      server.playlists = [
        FakeSubsonicServer.playlist('p1', 'One',
            songIds: ['s1'], library: server.songs),
        FakeSubsonicServer.playlist('p2', 'Two',
            songIds: ['s2'], library: server.songs),
      ];
      await runOk(); // both fetched once (default cap)

      await engine.dispose();
      engine = _engine(db, server, serverId, clock,
          options: const SyncOptions(maxPlaylistFetchesPerRun: 1));
      server.playlists = [
        FakeSubsonicServer.playlist('p1', 'One',
            songIds: ['s1', 's3'],
            changed: '2026-10-12T00:00:00Z',
            library: server.songs),
        FakeSubsonicServer.playlist('p2', 'Two',
            songIds: ['s2', 's4'],
            changed: '2026-10-12T00:00:00Z',
            library: server.songs),
      ];
      server.adapter.requests.clear();
      await runOk(); // cap 1: only one of them gets its new songs
      expect(server.adapter.count('getPlaylist'), 1);

      await runOk(); // the other one must not be forgotten
      expect(server.adapter.count('getPlaylist'), 2);
      final entries = await db.select(db.playlistEntries).get();
      expect(entries, hasLength(4), reason: 'both playlists now have 2 songs');
    });

    test(
        'a playlist that lists a song the server cannot return is not '
        'fetched on every run', () async {
      // The list says 3 songs, the playlist itself returns 2 (one is gone).
      // Comparing the list's count with the stored entries' count refetched it
      // every 10 minutes for ever.
      server.playlists = [
        FakeSubsonicServer.playlist('p1', 'Mine',
            songIds: ['s1', 's2', 's3'], library: server.songs),
      ];
      server.adapter.routes['getPlaylist'] = (_) {
        final base = server.playlists.first;
        return FakeResponse.json(subsonicOk({
          'playlist': {
            ...base,
            'entry': (base['entry']! as List).take(2).toList(),
          },
        }));
      };
      await runOk();
      expect(server.adapter.count('getPlaylist'), 1);

      await runOk();
      await runOk();

      expect(server.adapter.count('getPlaylist'), 1,
          reason: 'nothing changed on the server, so nothing is fetched');
    });

    test('a changed user playlist is re-fetched and entries replaced',
        () async {
      server.playlists = [
        FakeSubsonicServer.playlist('p1', 'Mine',
            songIds: ['s1', 's2'], library: server.songs),
      ];
      await runOk();

      server.playlists = [
        FakeSubsonicServer.playlist('p1', 'Mine',
            songIds: ['s2', 's5', 's6'],
            changed: '2026-10-12T00:00:00Z',
            library: server.songs),
      ];
      await runOk();

      final entries = await (db.select(db.playlistEntries)
            ..orderBy([(e) => OrderingTerm.asc(e.position)]))
          .get();
      expect(entries.map((e) => e.trackId), ['s2', 's5', 's6']);
    });

    test('a reshuffled smart playlist with the same members keeps its order',
        () async {
      server.playlists = [
        FakeSubsonicServer.playlist('sp', 'Phone Offline',
            songIds: ['s1', 's2', 's3'], readonly: true, library: server.songs),
      ];
      await runOk();
      clock.advance(const Duration(hours: 7)); // past the smart-playlist TTL

      server.playlists = [
        FakeSubsonicServer.playlist('sp', 'Phone Offline',
            songIds: ['s3', 's1', 's2'], // same set, new order
            readonly: true,
            changed: '2026-10-14T11:00:00Z',
            library: server.songs),
      ];
      await runOk();

      final entries = await (db.select(db.playlistEntries)
            ..orderBy([(e) => OrderingTerm.asc(e.position)]))
          .get();
      expect(entries.map((e) => e.trackId), ['s1', 's2', 's3'],
          reason: 'order-only change is not a change (ADR-025)');
    });

    test('a smart playlist whose members changed is updated', () async {
      server.playlists = [
        FakeSubsonicServer.playlist('sp', 'Phone Offline',
            songIds: ['s1', 's2'], readonly: true, library: server.songs),
      ];
      await runOk();
      clock.advance(const Duration(hours: 7));

      server.playlists = [
        FakeSubsonicServer.playlist('sp', 'Phone Offline',
            songIds: ['s2', 's9'],
            readonly: true,
            changed: '2026-10-14T11:00:00Z',
            library: server.songs),
      ];
      await runOk();

      final entries = await db.select(db.playlistEntries).get();
      expect(entries.map((e) => e.trackId).toSet(), {'s2', 's9'});
    });

    test('a pinned smart playlist is refreshed on the short TTL', () async {
      server.playlists = [
        FakeSubsonicServer.playlist('sp', 'Phone Offline',
            songIds: ['s1'], readonly: true, library: server.songs),
      ];
      await runOk();
      await db.into(db.pins).insert(PinsCompanion.insert(
            serverId: serverId,
            targetType: 'playlist',
            targetId: 'sp',
            createdAtMs: 0,
          ));
      server.playlists = [
        FakeSubsonicServer.playlist('sp', 'Phone Offline',
            songIds: ['s1', 's4'], readonly: true, library: server.songs),
      ];
      clock.advance(const Duration(hours: 2)); // > 1 h pinned TTL, < 6 h

      await runOk();

      final entries = await db.select(db.playlistEntries).get();
      expect(entries.map((e) => e.trackId).toSet(), {'s1', 's4'});
    });

    test('a huge smart playlist is lazy: not fetched until pinned/opened',
        () async {
      final big = [for (var i = 0; i < 400; i++) 's${i % 30}'];
      server.playlists = [
        FakeSubsonicServer.playlist('big', 'Phone Everything',
            songIds: big, readonly: true, library: server.songs),
      ];

      await runOk();
      expect(server.adapter.count('getPlaylist'), 0);
      var row = await (db.select(db.playlists)
            ..where((p) => p.id.equals('big')))
          .getSingle();
      expect(row.name, 'Phone Everything', reason: 'metadata is stored');
      expect(row.entriesFetchedAtMs, isNull);

      // Opening it fetches the entries on demand.
      final refreshed = await engine.refreshPlaylist('big');
      expect(refreshed.isOk, isTrue);
      row = await (db.select(db.playlists)..where((p) => p.id.equals('big')))
          .getSingle();
      expect(row.entriesFetchedAtMs, isNotNull);
      expect(await db.select(db.playlistEntries).get(), hasLength(400));
    });

    test('a pinned huge smart playlist is fetched by the normal sync',
        () async {
      final big = [for (var i = 0; i < 400; i++) 's${i % 30}'];
      server.playlists = [
        FakeSubsonicServer.playlist('big', 'Phone Everything',
            songIds: big, readonly: true, library: server.songs),
      ];
      await db.into(db.pins).insert(PinsCompanion.insert(
            serverId: serverId,
            targetType: 'playlist',
            targetId: 'big',
            createdAtMs: 0,
          ));

      await runOk();

      expect(server.adapter.count('getPlaylist'), 1);
    });

    test('a playlist with an undelivered edit keeps its local state', () async {
      server.playlists = [
        FakeSubsonicServer.playlist('p1', 'Mine',
            songIds: ['s1', 's2'], library: server.songs),
      ];
      await runOk();

      // The user adds a song and renames it; both are still in the outbox.
      final edits = PlaylistMutations(
          db: db, serverId: serverId, clock: clock, ownerName: 'tester');
      await edits.addTracks('p1', ['s9']);
      await edits.rename('p1', 'Road trip');

      // The server's copy is older and also reports a "change".
      server.playlists = [
        FakeSubsonicServer.playlist('p1', 'Mine',
            songIds: ['s1', 's2'],
            changed: '2026-10-12T00:00:00Z',
            library: server.songs),
      ];
      server.adapter.requests.clear();
      await runOk();

      final row = await (db.select(db.playlists)
            ..where((p) => p.id.equals('p1')))
          .getSingle();
      expect(row.name, 'Road trip');
      expect(row.songCount, 3);
      final entries = await (db.select(db.playlistEntries)
            ..orderBy([(e) => OrderingTerm.asc(e.position)]))
          .get();
      expect(entries.map((e) => e.trackId), ['s1', 's2', 's9']);
      expect(server.adapter.count('getPlaylist'), 0);
    });

    test('a playlist created on the phone is not tombstoned by a sync',
        () async {
      await runOk();
      final edits = PlaylistMutations(
          db: db, serverId: serverId, clock: clock, ownerName: 'tester');
      final id = await edits.create('Brand new', trackIds: ['s3']);

      await runOk(); // the server does not list it yet

      final row = await (db.select(db.playlists)..where((p) => p.id.equals(id)))
          .getSingle();
      expect(row.deletedAtMs, isNull);
      expect(row.name, 'Brand new');
    });

    test('opening a playlist with undelivered edits does not refetch it',
        () async {
      server.playlists = [
        FakeSubsonicServer.playlist('p1', 'Mine',
            songIds: ['s1'], library: server.songs),
      ];
      await runOk();
      final edits = PlaylistMutations(
          db: db, serverId: serverId, clock: clock, ownerName: 'tester');
      await edits.addTracks('p1', ['s2']);
      server.adapter.requests.clear();

      final result = await engine.refreshPlaylist('p1');

      expect(result.isOk, isTrue);
      expect(server.adapter.count('getPlaylist'), 0);
      expect(await db.select(db.playlistEntries).get(), hasLength(2));
    });

    test('a playlist deleted on the server is tombstoned', () async {
      server.playlists = [
        FakeSubsonicServer.playlist('p1', 'Doomed', songIds: ['s1']),
      ];
      await runOk();
      server.playlists = [];
      await runOk();

      final row = await (db.select(db.playlists)
            ..where((p) => p.id.equals('p1')))
          .getSingle();
      expect(row.deletedAtMs, isNotNull);
    });
  });

  group('starred', () {
    test('server stars are mirrored, and removed stars cleared', () async {
      server.starredSongIds = {'s1', 's2'};
      await runOk();
      var starred = await (db.select(db.tracks)
            ..where((t) => t.starredAtMs.isNotNull()))
          .get();
      expect(starred.map((t) => t.id).toSet(), {'s1', 's2'});

      server.starredSongIds = {'s2'};
      await runOk();
      starred = await (db.select(db.tracks)
            ..where((t) => t.starredAtMs.isNotNull()))
          .get();
      expect(starred.map((t) => t.id).toSet(), {'s2'});
    });

    test('a pending local star is not overwritten by a stale server view',
        () async {
      await runOk();
      // User starred s7 locally; the mutation has not reached the server yet.
      await (db.update(db.tracks)..where((t) => t.id.equals('s7')))
          .write(const TracksCompanion(starredAtMs: Value(5)));
      await db.into(db.outbox).insert(OutboxCompanion.insert(
            serverId: serverId,
            kind: 'star',
            payloadJson: '{"songIds":["s7"]}',
            createdAtMs: 0,
          ));

      await runOk(); // server still says: nothing starred

      final s7 = await (db.select(db.tracks)..where((t) => t.id.equals('s7')))
          .getSingle();
      expect(s7.starredAtMs, 5);
    });

    // The two tests below are the paths the one above never reaches: the
    // library dump and the starred phase both WRITE the server's star state
    // over the row before the pending-edit protection runs (docs/23, B7).
    Future<void> pendingOutbox(String kind, String payload) =>
        db.into(db.outbox).insert(OutboxCompanion.insert(
              serverId: serverId,
              kind: kind,
              payloadJson: payload,
              createdAtMs: 0,
            ));

    Future<int?> trackStar(String id) async =>
        (await (db.select(db.tracks)..where((t) => t.id.equals(id)))
                .getSingle())
            .starredAtMs;

    test('a pending like survives a full library dump', () async {
      await runOk();
      await (db.update(db.tracks)..where((t) => t.id.equals('s7')))
          .write(const TracksCompanion(starredAtMs: Value(5)));
      await pendingOutbox('star', '{"songIds":["s7"]}');

      final outcome = await engine.run(force: true); // re-reads every song
      expect(outcome, isA<SyncCompleted>());

      expect(await trackStar('s7'), 5,
          reason: 'the dump carries the old server view: no star');
    });

    test('a pending unlike survives the starred phase', () async {
      server.starredSongIds = {'s7'};
      await runOk(); // the phone learns that s7 is liked
      expect(await trackStar('s7'), isNotNull);

      await (db.update(db.tracks)..where((t) => t.id.equals('s7')))
          .write(const TracksCompanion(starredAtMs: Value(null)));
      await pendingOutbox('unstar', '{"songIds":["s7"]}');

      await runOk(); // the server still lists s7 as starred

      expect(await trackStar('s7'), isNull,
          reason: 'the person unliked it; the server has not heard yet');
    });

    test('a pending album like survives a full library dump', () async {
      await runOk();
      await (db.update(db.albums)..where((a) => a.id.equals('al1')))
          .write(const AlbumsCompanion(starredAtMs: Value(5)));
      await pendingOutbox('star', '{"albumIds":["al1"]}');

      await engine.run(force: true);

      final album = await (db.select(db.albums)
            ..where((a) => a.id.equals('al1')))
          .getSingle();
      expect(album.starredAtMs, 5);
    });

    test('once the like is delivered the server view wins again', () async {
      await runOk();
      await (db.update(db.tracks)..where((t) => t.id.equals('s7')))
          .write(const TracksCompanion(starredAtMs: Value(5)));
      final id = await db.into(db.outbox).insert(OutboxCompanion.insert(
            serverId: serverId,
            kind: 'star',
            payloadJson: '{"songIds":["s7"]}',
            createdAtMs: 0,
          ));
      await (db.delete(db.outbox)..where((o) => o.id.equals(id))).go();

      await engine.run(force: true); // delivered long ago; the server says no

      expect(await trackStar('s7'), isNull,
          reason: 'protection lasts only while the edit is waiting');
    });
  });

  // R-16 / ADR-071 layer L1: the cheap check the app runs every few seconds
  // while it is open, so an edit made on another device shows up in seconds.
  group('live probe', () {
    Map<String, Object?> pl(
      String id,
      List<String> songs, {
      String changed = '2026-10-10T00:00:00Z',
    }) =>
        FakeSubsonicServer.playlist(id, 'List $id',
            songIds: songs, changed: changed, library: server.songs);

    setUp(() async {
      server.playlists = [
        pl('p1', ['s1', 's2']),
        pl('p2', ['s3']),
      ];
      await runOk(); // the phone has everything
      server.adapter.requests.clear();
    });

    List<String> methods() =>
        server.adapter.requests.map((r) => r.apiMethod).toList();

    Future<List<String>> entriesOf(String playlistId) async =>
        (await (db.select(db.playlistEntries)
                  ..where((e) => e.playlistId.equals(playlistId))
                  ..orderBy([(e) => OrderingTerm.asc(e.position)]))
                .get())
            .map((e) => e.trackId)
            .toList();

    test('nothing changed: two small requests and nothing fetched', () async {
      final outcome = await engine.probe();

      expect(outcome, isA<ProbeUnchanged>());
      expect(methods(), ['getScanStatus', 'getPlaylists']);
    });

    test('an edit made elsewhere is picked up, fetching only that playlist',
        () async {
      server.playlists = [
        pl('p1', ['s1', 's2', 's9'], changed: '2026-10-16T12:00:00Z'),
        pl('p2', ['s3']),
      ];

      final outcome = await engine.probe();

      expect(outcome, isA<ProbeUpdated>());
      expect((outcome as ProbeUpdated).playlists, 1);
      expect(methods(), ['getScanStatus', 'getPlaylists', 'getPlaylist']);
      expect(await entriesOf('p1'), ['s1', 's2', 's9']);
      expect(await entriesOf('p2'), ['s3']);
    });

    test('a playlist made elsewhere appears', () async {
      server.playlists = [
        pl('p1', ['s1', 's2']),
        pl('p2', ['s3']),
        pl('p3', ['s4', 's5']),
      ];

      final outcome = await engine.probe();

      expect(outcome, isA<ProbeUpdated>());
      expect(await entriesOf('p3'), ['s4', 's5']);
    });

    test('a playlist deleted elsewhere disappears', () async {
      server.playlists = [
        pl('p1', ['s1', 's2'])
      ];

      final outcome = await engine.probe();

      expect(outcome, isA<ProbeUpdated>());
      final p2 = await (db.select(db.playlists)
            ..where((p) => p.id.equals('p2')))
          .getSingle();
      expect(p2.deletedAtMs, isNotNull);
    });

    test('a changed library asks for a normal pass, it does not dump here',
        () async {
      server.lastScan = '2026-10-16T13:00:00.000000000Z';
      clock.advance(
          const Duration(hours: 2)); // past the gap between library passes

      final outcome = await engine.probe();

      expect(outcome, isA<ProbeNeedsFullPass>());
      expect(methods(), ['getScanStatus'],
          reason: 'the probe stops at the scan status; no dump, no playlists');
    });

    test('a playlist with an edit waiting on this phone is left alone',
        () async {
      await db.into(db.outbox).insert(OutboxCompanion.insert(
            serverId: serverId,
            kind: 'playlist.update',
            payloadJson: '{"playlistId":"p1","add":["s7"]}',
            createdAtMs: 0,
          ));
      server.playlists = [
        pl('p1', ['s1'], changed: '2026-10-16T12:00:00Z'),
        pl('p2', ['s3']),
      ];

      await engine.probe();

      expect(await entriesOf('p1'), ['s1', 's2'],
          reason: 'the server copy is older than the waiting edit');
    });

    test('the network failing is reported, never thrown', () async {
      server.adapter.routes['getScanStatus'] =
          (_) => const FakeResponse.connectionError();

      final outcome = await engine.probe();

      expect(outcome, isA<ProbeFailed>());
      expect((outcome as ProbeFailed).failure, isA<NetworkFailure>());
    });

    test('it does nothing while a full run is in flight', () async {
      final gate = Completer<void>();
      final original = server.adapter.routes['getStarred2']!;
      server.adapter.routes['getStarred2'] = (r) async {
        await gate.future;
        return original(r);
      };
      final run = engine.run(force: true);
      while (server.adapter.count('getStarred2') == 0) {
        await Future<void>.delayed(const Duration(milliseconds: 5));
      }
      server.adapter.requests.clear();

      final outcome = await engine.probe();

      expect(outcome, isA<ProbeBusy>());
      expect(server.adapter.requests, isEmpty);
      gate.complete();
      await run;
    });
  });

  group('engine behaviour', () {
    test('concurrent runs are single-flight', () async {
      final a = engine.run();
      final b = engine.run();
      expect(identical(a, b), isTrue);
      await Future.wait([a, b]);
      expect(server.adapter.count('getScanStatus'), 1);
    });

    test('progress is emitted and ends idle', () async {
      final phases = <SyncPhase>[];
      final sub = engine.progress.listen((p) => phases.add(p.phase));
      await runOk();
      await Future<void>.delayed(Duration.zero);
      await sub.cancel();

      expect(
          phases,
          containsAllInOrder([
            SyncPhase.probing,
            SyncPhase.artists,
            SyncPhase.albums,
            SyncPhase.songs,
            SyncPhase.playlists,
            SyncPhase.starred,
            SyncPhase.finishing,
            SyncPhase.idle,
          ]));
    });

    test('cancel stops between pages and leaves data consistent', () async {
      server.seed(songCount: 2000, albumCount: 4);
      final original = server.adapter.routes['search3']!;
      server.adapter.routes['search3'] = (r) {
        engine.cancel(); // user cancels while the first page is in flight
        return original(r);
      };

      final outcome = await engine.run();

      expect(outcome, isA<SyncCancelled>());
      final tombstoned = await (db.select(db.tracks)
            ..where((t) => t.deletedAtMs.isNotNull()))
          .get();
      expect(tombstoned, isEmpty);
    });

    test('state survives: watermark saved only after a trusted run', () async {
      server.scanning = true;
      await runOk();
      server.scanning = false;
      server.adapter.requests.clear();

      final stats = await runOk();
      expect(stats.libraryPhaseRan, isTrue,
          reason: 'a mid-scan run must not be remembered as "up to date"');
    });
  });
}

SyncEngine _engine(
  AppDatabase db,
  FakeSubsonicServer server,
  int serverId,
  Clock clock, {
  SyncOptions options = const SyncOptions(),
}) {
  final client = OpenSubsonicClient(
    dio: fakeDio(server.adapter),
    baseUrl: () => Uri.parse('http://fake:4533'),
    credentials: const SubsonicCredentials(username: 'tester', password: 'x'),
  );
  return SyncEngine(
    db: db,
    client: client,
    serverId: serverId,
    clock: clock,
    options: options,
  );
}
