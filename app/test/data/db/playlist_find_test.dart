import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:drift/native.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/db/search_dao.dart';
import 'package:flutter_test/flutter_test.dart';

/// N-25 (the owner, 13 Nov 2026): find a song inside a playlist. The finding is Search's own (the `track_fts` index, `toFtsQuery`), restricted
/// to the entries of one playlist, so the two can never disagree about what a word finds (ADR-R42, audit B-46).
void main() {
  late AppDatabase db;
  late int serverId;

  setUp(() async {
    db = AppDatabase(NativeDatabase.memory());
    serverId = await db.into(db.servers).insert(ServersCompanion.insert(
          name: 'Home',
          username: 'tester',
          endpointsJson: '[{"label":"Home","url":"http://10.0.0.2:4533"}]',
          createdAtMs: 0,
        ));
  });

  tearDown(() => db.close());

  Future<void> track(String id, String title, {String? artist, String? album}) {
    return db.into(db.tracks).insertOnConflictUpdate(TracksCompanion.insert(
          serverId: serverId,
          id: id,
          title: title,
          artist: Value(artist),
          album: Value(album),
        ));
  }

  Future<void> playlist(String id, List<String> trackIds) async {
    await db.into(db.playlists).insert(PlaylistsCompanion.insert(
          serverId: serverId,
          id: id,
          name: id,
          songCount: Value(trackIds.length),
        ));
    for (var i = 0; i < trackIds.length; i++) {
      await db.into(db.playlistEntries).insert(PlaylistEntriesCompanion.insert(
            serverId: serverId,
            playlistId: id,
            position: i,
            trackId: trackIds[i],
          ));
    }
  }

  Future<List<int>> find(String playlistId, String query) =>
      SearchDao(db).playlistEntryPositions(serverId, playlistId, query).get();

  test('finds the entries of this playlist only, in playlist order', () async {
    await track('a', 'Nude', artist: 'Radiohead', album: 'In Rainbows');
    await track('b', 'Time', artist: 'Pink Floyd');
    await track('c', 'Let Down', artist: 'Radiohead', album: 'OK Computer');
    await track('d', 'Creep', artist: 'Radiohead');
    await playlist('mine', ['c', 'b', 'a']);
    await playlist('other', ['d']);

    // 'c' comes first in the playlist although 'a' would rank higher in a search of the whole library.
    expect(await find('mine', 'radiohead'), [0, 2]);
    expect(await find('other', 'radiohead'), [0]);
    expect(await find('mine', 'creep'), isEmpty,
        reason: 'a song that is not in this playlist is never found');
  });

  test('a song that is in the playlist twice is found twice', () async {
    await track('a', 'Nude', artist: 'Radiohead');
    await track('b', 'Time', artist: 'Pink Floyd');
    await playlist('mine', ['a', 'b', 'a']);

    expect(await find('mine', 'nude'), [0, 2],
        reason: 'two entries, so the page can tell them apart by position');
  });

  test('finds what Search finds: titles, artists, albums, accents, scripts',
      () async {
    await track('a', 'Café del Mar', artist: 'Energy 52');
    await track('b', 'مرحبا', artist: 'فيروز', album: 'صباح');
    await track('c', 'Ænima', artist: 'Tool');
    await track('d', 'Plain', artist: 'Someone', album: 'Kodama');
    await playlist('mine', ['a', 'b', 'c', 'd']);

    expect(await find('mine', 'cafe'), [0], reason: 'accents are ignored');
    expect(await find('mine', 'فيروز'), [1], reason: 'another script');
    expect(await find('mine', 'صب'), [1], reason: 'the start of an album');
    expect(await find('mine', 'aenima'), [2], reason: 'a ligature');
    expect(await find('mine', 'kodama'), [3], reason: 'the album');
    // The same words give the same songs as Search itself, restricted to the playlist.
    for (final q in ['cafe', 'فيروز', 'aenima', 'kodama', 'tool', 'some']) {
      final inSearch = (await SearchDao(db).tracks(serverId, q).get())
          .map((t) => t.id)
          .toSet();
      final inPlaylist = {
        for (final p in await find('mine', q)) ['a', 'b', 'c', 'd'][p],
      };
      expect(inPlaylist, inSearch, reason: '"$q" finds the same songs');
    }
  });

  test('words that cannot be searched find nothing, as in Search', () async {
    await track('a', 'Nude', artist: 'Radiohead');
    await playlist('mine', ['a']);

    expect(await find('mine', '!!!'), isEmpty);
    expect(await find('mine', '   '), isEmpty);
  });

  test('a deleted song and an entry with no song row are not found', () async {
    await track('a', 'Nude', artist: 'Radiohead');
    await track('b', 'Let Down', artist: 'Radiohead');
    // 'ghost' has an entry but the phone has no row for it.
    await playlist('mine', ['a', 'ghost', 'b']);
    await (db.update(db.tracks)..where((t) => t.id.equals('b')))
        .write(const TracksCompanion(deletedAtMs: Value(1)));

    expect(await find('mine', 'radiohead'), [0]);
  });

  test('every entry that has a song row is found by its own title', () async {
    // The check behind the page: the index covers the rows the way the sync writes them (insert, then an upsert that changes a title).
    final ids = [for (var i = 0; i < 300; i++) 't$i'];
    await db.batch((b) => b.insertAll(db.tracks, [
          for (final id in ids)
            TracksCompanion.insert(
              serverId: serverId,
              id: id,
              title: 'Song number ${id}x',
              artist: const Value('Band'),
            ),
        ]));
    await db.batch((b) => b.insertAllOnConflictUpdate(db.tracks, [
          for (final id in ids.take(100))
            TracksCompanion.insert(
              serverId: serverId,
              id: id,
              title: 'Renamed ${id}y',
              artist: const Value('Band'),
            ),
        ]));
    await playlist('big', ids);

    for (var i = 0; i < ids.length; i++) {
      final word = i < 100 ? '${ids[i]}y' : '${ids[i]}x';
      expect(await find('big', word), [i],
          reason: 'entry $i (${ids[i]}) is covered by the index');
    }
    expect(await find('big', 'band'), hasLength(300));
  });

  test(
      'a word that most songs of a big library match is still answered at once',
      () async {
    // The first version joined the index with the playlist's entries and SQLite asked the index again for every entry: 34 s for 2,000
    // entries, the word "a" and 50,000 songs. The index is asked once now; the limit here is far above what that takes (about 20 ms) and
    // far below the old plan (many seconds).
    await db.batch((b) => b.insertAll(db.tracks, [
          for (var i = 0; i < 20000; i++)
            TracksCompanion.insert(
              serverId: serverId,
              id: 'lib$i',
              title: 'Song $i',
              artist: Value('Artist ${i % 311}'),
              album: const Value('Album a'),
            ),
        ]));
    await playlist('long', [for (var i = 0; i < 2000; i++) 'lib${i * 10}']);

    final watch = Stopwatch()..start();
    final found = await find('long', 'a');
    watch.stop();

    expect(found, hasLength(2000));
    expect(watch.elapsedMilliseconds, lessThan(2000),
        reason: 'asked the index once, not once per entry');
  });
}
