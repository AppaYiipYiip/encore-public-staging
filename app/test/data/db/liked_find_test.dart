import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:drift/native.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/db/search_dao.dart';
import 'package:flutter_test/flutter_test.dart';

/// N-32 (the owner, 15 Nov 2026): find a song inside Liked Songs, as in any playlist. The finding is Search's own (the `track_fts` index,
/// `toFtsQuery`), restricted to the songs the person has liked, so the two can never disagree about what a word finds (ADR-R42, audit B-46)
/// and the playlist's finding (`playlist_find_test.dart`) and this one read the same index in the same way.
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

  Future<void> track(String id, String title,
      {String? artist, String? album, int? liked, int? server}) {
    return db.into(db.tracks).insertOnConflictUpdate(TracksCompanion.insert(
          serverId: server ?? serverId,
          id: id,
          title: title,
          artist: Value(artist),
          album: Value(album),
          starredAtMs: Value(liked),
        ));
  }

  Future<Set<String>> find(String query) async =>
      (await SearchDao(db).likedTrackIds(serverId, query).get()).toSet();

  test('finds the liked songs only, not the other songs that match', () async {
    await track('a', 'Nude', artist: 'Radiohead', liked: 10);
    await track('b', 'Let Down', artist: 'Radiohead', liked: 20);
    await track('c', 'Creep', artist: 'Radiohead'); // not liked
    await track('d', 'Time', artist: 'Pink Floyd', liked: 30);

    expect(await find('radiohead'), {'a', 'b'},
        reason: 'Creep matches the word but is not liked');
    expect(await find('creep'), isEmpty,
        reason: 'a song that is not liked is never found');
    expect(await find('time'), {'d'});
  });

  test('finds what Search finds: titles, artists, albums, accents, scripts',
      () async {
    await track('a', 'Café del Mar', artist: 'Energy 52', liked: 1);
    await track('b', 'مرحبا', artist: 'فيروز', album: 'صباح', liked: 2);
    await track('c', 'Ænima', artist: 'Tool', liked: 3);
    await track('d', 'Plain', artist: 'Someone', album: 'Kodama', liked: 4);

    expect(await find('cafe'), {'a'}, reason: 'accents are ignored');
    expect(await find('فيروز'), {'b'}, reason: 'another script');
    expect(await find('صب'), {'b'}, reason: 'the start of an album');
    expect(await find('aenima'), {'c'}, reason: 'a ligature');
    expect(await find('kodama'), {'d'}, reason: 'the album');
    // The same words give the same songs as Search itself, restricted to the liked songs: one matcher.
    for (final q in ['cafe', 'فيروز', 'aenima', 'kodama', 'tool', 'some']) {
      final inSearch = (await SearchDao(db).tracks(serverId, q).get())
          .where((t) => t.starredAtMs != null)
          .map((t) => t.id)
          .toSet();
      expect(await find(q), inSearch, reason: '"$q" finds the same songs');
    }
  });

  test('a song that was liked and is not any more is not found', () async {
    await track('a', 'Nude', artist: 'Radiohead', liked: 10);
    await track('b', 'Let Down', artist: 'Radiohead', liked: 20);
    expect(await find('radiohead'), {'a', 'b'});

    await (db.update(db.tracks)..where((t) => t.id.equals('b')))
        .write(const TracksCompanion(starredAtMs: Value(null)));
    expect(await find('radiohead'), {'a'});
  });

  test('a deleted song and the liked songs of another server are not found',
      () async {
    final other = await db.into(db.servers).insert(ServersCompanion.insert(
          name: 'Other',
          username: 'tester',
          endpointsJson: '[{"label":"Other","url":"http://10.0.0.3:4533"}]',
          createdAtMs: 0,
        ));
    await track('a', 'Nude', artist: 'Radiohead', liked: 10);
    await track('b', 'Let Down', artist: 'Radiohead', liked: 20);
    await track('o', 'Creep', artist: 'Radiohead', liked: 30, server: other);
    await (db.update(db.tracks)..where((t) => t.id.equals('b')))
        .write(const TracksCompanion(deletedAtMs: Value(1)));

    expect(await find('radiohead'), {'a'});
    expect(
        (await SearchDao(db).likedTrackIds(other, 'radiohead').get()).toSet(),
        {'o'});
  });

  test('words that cannot be searched find nothing, as in Search', () async {
    await track('a', 'Nude', artist: 'Radiohead', liked: 10);

    expect(await find('!!!'), isEmpty);
    expect(await find('   '), isEmpty);
  });

  test('a like or an unlike while the finding is open changes the answer',
      () async {
    await track('a', 'Nude', artist: 'Radiohead', liked: 10);
    await track('b', 'Let Down', artist: 'Radiohead');

    final answers = <Set<String>>[];
    final sub = SearchDao(db)
        .likedTrackIds(serverId, 'radiohead')
        .watch()
        .map((ids) => ids.toSet())
        .listen(answers.add);
    addTearDown(sub.cancel);
    await pumpEventQueue();
    expect(answers.last, {'a'});

    await (db.update(db.tracks)..where((t) => t.id.equals('b')))
        .write(const TracksCompanion(starredAtMs: Value(99)));
    await pumpEventQueue();
    expect(answers.last, {'a', 'b'}, reason: 'the new like appears at once');

    await (db.update(db.tracks)..where((t) => t.id.equals('a')))
        .write(const TracksCompanion(starredAtMs: Value(null)));
    await pumpEventQueue();
    expect(answers.last, {'b'}, reason: 'the unlike goes at once');
  });

  test('every liked song is found by its own title', () async {
    // The check behind the page: the index covers the rows the way the sync writes them (insert, then an upsert that changes a title).
    final ids = [for (var i = 0; i < 300; i++) 't$i'];
    await db.batch((b) => b.insertAll(db.tracks, [
          for (final (i, id) in ids.indexed)
            TracksCompanion.insert(
              serverId: serverId,
              id: id,
              title: 'Song number ${id}x',
              artist: const Value('Band'),
              starredAtMs: Value(i.isEven ? 1000 + i : null),
            ),
        ]));
    await db.batch((b) => b.insertAllOnConflictUpdate(db.tracks, [
          for (final (i, id) in ids.indexed.take(100))
            TracksCompanion.insert(
              serverId: serverId,
              id: id,
              title: 'Renamed ${id}y',
              artist: const Value('Band'),
              starredAtMs: Value(i.isEven ? 1000 + i : null),
            ),
        ]));

    for (final (i, id) in ids.indexed) {
      final word = i < 100 ? '${id}y' : '${id}x';
      expect(await find(word), i.isEven ? {id} : isEmpty,
          reason: 'song $i ($id) is liked: ${i.isEven}');
    }
    expect(await find('band'), hasLength(150));
  });

  test('the index is asked once for the whole library, never once per song',
      () async {
    // As the playlist's: a join with the index would ask it again for every row of the table (34 s for 2,000 entries and the word "a" in a
    // 50,000-song library, N-25). The plan must read the index only inside the list subquery.
    await track('a', 'Nude', artist: 'Radiohead', liked: 10);

    final plan = await db.customSelect(
      'EXPLAIN QUERY PLAN $likedTrackIdsSql',
      variables: [
        Variable<String>('"a"*'),
        Variable<int>(serverId),
      ],
    ).get();
    final steps = [
      for (final row in plan)
        (parent: row.read<int>('parent'), detail: row.read<String>('detail')),
    ];
    final shown = steps.map((s) => '${s.parent}: ${s.detail}').join(' | ');

    expect(steps.any((s) => s.detail.contains('LIST SUBQUERY')), isTrue,
        reason: 'the index is read into a list first: $shown');
    expect(steps.where((s) => s.parent == 0 && s.detail.contains('track_fts')),
        isEmpty,
        reason: 'and is not searched again for each song: $shown');
  });
}
