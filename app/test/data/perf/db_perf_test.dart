@Tags(['perf'])
library;

import 'package:drift/native.dart';
import 'package:encore/data/api/opensubsonic/models.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/db/search_dao.dart';
import 'package:encore/data/repos/library_repository.dart';
import 'package:encore/data/sync/library_writer.dart';
import 'package:flutter_test/flutter_test.dart';

/// Database performance budgets (docs/00-requirements.md):
/// list/page queries < 16 ms and FTS search < 30 ms on 50k tracks.
///
/// These run on the Dart VM (JIT, desktop CPU) in CI, so the asserted limits
/// are 3x the on-device budget; the printed numbers are what to watch.
void main() {
  const trackCount = 50000;
  const albumCount = 5000;

  late AppDatabase db;
  late int serverId;

  setUpAll(() async {
    db = AppDatabase(NativeDatabase.memory());
    serverId = await db.into(db.servers).insert(ServersCompanion.insert(
          name: 'Perf',
          username: 'u',
          endpointsJson: '[]',
          createdAtMs: 0,
        ));
    final writer = LibraryWriter(db);

    const artists = [
      'Alcest',
      'Opeth',
      'Periphery',
      'Katatonia',
      'Sigur Rós',
      'Motörhead',
      'Gojira',
      'Tool',
      'Mastodon',
      'Leprous',
    ];
    final albums = [
      for (var a = 0; a < albumCount; a++)
        SsAlbum(
          id: 'al$a',
          name: 'Album number $a',
          artist: artists[a % artists.length],
          artistId: 'ar${a % artists.length}',
          year: 1990 + a % 35,
          songCount: trackCount ~/ albumCount,
          createdAtMs: 1700000000000 + a * 1000,
        ),
    ];
    await writer.upsertAlbums(serverId, 1, albums);

    final sw = Stopwatch()..start();
    for (var chunk = 0; chunk < trackCount; chunk += 500) {
      await writer.upsertTracks(serverId, 1, [
        for (var i = chunk; i < chunk + 500; i++)
          SsSong(
            id: 's$i',
            title: 'Track $i of ${artists[i % artists.length]}',
            album: 'Album number ${i % albumCount}',
            albumId: 'al${i % albumCount}',
            artist: artists[i % artists.length],
            artistId: 'ar${i % artists.length}',
            trackNo: i % 12,
            durationSec: 180,
            suffix: 'mp3',
            bitRate: 320,
            size: 7000000,
          ),
      ]);
    }
    // ignore: avoid_print
    print('PERF bulk upsert $trackCount tracks: ${sw.elapsedMilliseconds} ms');
  });

  tearDownAll(() => db.close());

  Future<int> timeMs(Future<void> Function() body, {int runs = 5}) async {
    await body(); // warm-up (JIT, statement cache)
    final sw = Stopwatch()..start();
    for (var i = 0; i < runs; i++) {
      await body();
    }
    return sw.elapsedMilliseconds ~/ runs;
  }

  test('bulk sync of 50k tracks stays in a sane envelope', () async {
    final count = await LibraryWriter(db).liveTrackCount(serverId);
    expect(count, trackCount);
  });

  test('FTS prefix search < 90 ms (budget 30 ms on device)', () async {
    final dao = SearchDao(db);
    final ms = await timeMs(() async {
      final r = await dao.tracks(serverId, 'motor', limit: 30).get();
      expect(r, isNotEmpty);
    });
    // ignore: avoid_print
    print('PERF FTS search: $ms ms');
    expect(ms, lessThan(90));
  });

  test('diacritic-insensitive search finds Sigur Ros', () async {
    final r = await SearchDao(db).artists(serverId, 'sigur ros').get();
    // artists table is empty here (tracks only) - album search covers artist.
    expect(r, isEmpty);
    final a =
        await SearchDao(db).albums(serverId, 'sigur ros', limit: 10).get();
    expect(a, isNotEmpty);
  });

  test('album track list query < 48 ms (budget 16 ms)', () async {
    final repo = LibraryRepository(db, serverId);
    final ms = await timeMs(() async {
      final t = await repo.watchAlbumTracks('al42').first;
      expect(t, isNotEmpty);
    });
    // ignore: avoid_print
    print('PERF album tracks: $ms ms');
    expect(ms, lessThan(48));
  });

  test('recently added albums (limit 20) < 48 ms', () async {
    final repo = LibraryRepository(db, serverId);
    final ms = await timeMs(() async {
      final a = await repo
          .watchAlbums(sort: AlbumSort.recentlyAdded, limit: 20)
          .first;
      expect(a, hasLength(20));
    });
    // ignore: avoid_print
    print('PERF recent albums: $ms ms');
    expect(ms, lessThan(48));
  });

  test('count of live tracks < 48 ms', () async {
    final ms = await timeMs(() async {
      expect(await LibraryWriter(db).liveTrackCount(serverId), trackCount);
    });
    // ignore: avoid_print
    print('PERF count: $ms ms');
    expect(ms, lessThan(48));
  });
}
