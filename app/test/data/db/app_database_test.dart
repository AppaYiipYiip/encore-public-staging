import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:drift/native.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/db/search_dao.dart';
import 'package:flutter_test/flutter_test.dart';

AppDatabase _memoryDb() => AppDatabase(NativeDatabase.memory());

Future<int> _addServer(AppDatabase db, {String name = 'Home'}) {
  return db.into(db.servers).insert(
        ServersCompanion.insert(
          name: name,
          username: 'tester',
          endpointsJson: '[{"label":"Home","url":"http://10.0.0.2:4533"}]',
          createdAtMs: 0,
        ),
      );
}

Future<void> _addTrack(
  AppDatabase db,
  int serverId,
  String id,
  String title, {
  String? artist,
  String? album,
}) {
  return db.into(db.tracks).insertOnConflictUpdate(
        TracksCompanion.insert(
          serverId: serverId,
          id: id,
          title: title,
          artist: Value(artist),
          album: Value(album),
        ),
      );
}

void main() {
  late AppDatabase db;
  late int serverId;

  setUp(() async {
    db = _memoryDb();
    serverId = await _addServer(db);
  });

  tearDown(() => db.close());

  group('toFtsQuery', () {
    test('quotes tokens and makes them prefix matches', () {
      expect(toFtsQuery('alcest autre'), '"alcest"* "autre"*');
    });

    test('neutralises FTS operators and punctuation', () {
      expect(toFtsQuery('NEAR(a b) OR "x" -y*'),
          '"NEAR"* "a"* "b"* "OR"* "x"* "y"*');
      expect(toFtsQuery('   '), isNull);
      expect(toFtsQuery('!!!'), isNull);
    });

    test('keeps non-latin letters', () {
      expect(toFtsQuery('Sigur Rós'), '"Sigur"* "Rós"*');
      expect(toFtsQuery('日本語'), '"日本語"*');
    });

    test('a ligature is searched in both spellings', () {
      expect(toFtsQuery('aenima'), '("aenima"* OR "ænima"*)');
      expect(toFtsQuery('Ænima tool'), '("Ænima"* OR "aenima"*) AND "tool"*');
      expect(toFtsQuery('Straße'), '("Straße"* OR "strasse"*)');
    });
  });

  group('ligatures in the library', () {
    test('"aenima" finds the album "Ænima" and the other way round', () async {
      await db.into(db.albums).insert(AlbumsCompanion.insert(
            serverId: serverId,
            id: 'al1',
            name: 'Ænima',
            artist: const Value('Tool'),
          ));
      final dao = SearchDao(db);
      expect((await dao.albums(serverId, 'tool aenima').get()).map((a) => a.id),
          ['al1']);
      expect((await dao.albums(serverId, 'Ænima').get()).map((a) => a.id),
          ['al1']);

      await db.into(db.albums).insert(AlbumsCompanion.insert(
            serverId: serverId,
            id: 'al2',
            name: 'Aenima Live',
            artist: const Value('Tool'),
          ));
      final both = await dao.albums(serverId, 'aenima').get();
      expect(both.map((a) => a.id).toSet(), {'al1', 'al2'});
    });
  });

  group('schema', () {
    test('(serverId, id) is the identity: upsert replaces, never duplicates',
        () async {
      await _addTrack(db, serverId, 't1', 'First title');
      await _addTrack(db, serverId, 't1', 'Renamed title');

      final rows = await db.select(db.tracks).get();
      expect(rows, hasLength(1));
      expect(rows.single.title, 'Renamed title');
    });

    test('same remote id on two servers coexists (F-18)', () async {
      final other = await _addServer(db, name: 'Other');
      await _addTrack(db, serverId, 't1', 'On home');
      await _addTrack(db, other, 't1', 'On other');

      expect(await db.select(db.tracks).get(), hasLength(2));
    });

    test('deleting a server cascades to its library', () async {
      await _addTrack(db, serverId, 't1', 'Song');
      await (db.delete(db.servers)..where((s) => s.id.equals(serverId))).go();

      expect(await db.select(db.tracks).get(), isEmpty);
    });
  });

  group('full-text search', () {
    test('finds tracks by prefix, ignoring case and diacritics', () async {
      await _addTrack(db, serverId, 't1', 'Ace of Spades',
          artist: 'Motörhead', album: 'Ace of Spades');
      await _addTrack(db, serverId, 't2', 'Autre temps',
          artist: 'Alcest', album: 'Les voyages de l\'âme');

      final dao = SearchDao(db);
      expect((await dao.tracks(serverId, 'motorh').get()).map((t) => t.id),
          ['t1']);
      expect((await dao.tracks(serverId, 'VOYAGES AME').get()).map((t) => t.id),
          ['t2']);
      expect(await dao.tracks(serverId, 'zzzz').get(), isEmpty);
    });

    test('index follows updates and deletes', () async {
      await _addTrack(db, serverId, 't1', 'Old name', artist: 'Band');
      final dao = SearchDao(db);
      expect(await dao.tracks(serverId, 'old').get(), hasLength(1));

      await _addTrack(db, serverId, 't1', 'Fresh name', artist: 'Band');
      expect(await dao.tracks(serverId, 'old').get(), isEmpty);
      expect(await dao.tracks(serverId, 'fresh').get(), hasLength(1));

      await (db.delete(db.tracks)..where((t) => t.id.equals('t1'))).go();
      expect(await dao.tracks(serverId, 'fresh').get(), isEmpty);
    });

    test('tombstoned rows are not returned', () async {
      await _addTrack(db, serverId, 't1', 'Hidden gem');
      await (db.update(db.tracks)..where((t) => t.id.equals('t1')))
          .write(const TracksCompanion(deletedAtMs: Value(123)));

      expect(await SearchDao(db).tracks(serverId, 'hidden').get(), isEmpty);
    });

    test('is scoped to the server', () async {
      final other = await _addServer(db, name: 'Other');
      await _addTrack(db, serverId, 't1', 'Shared title');
      await _addTrack(db, other, 't2', 'Shared title');

      final dao = SearchDao(db);
      expect((await dao.tracks(serverId, 'shared').get()).single.id, 't1');
      expect((await dao.tracks(other, 'shared').get()).single.id, 't2');
    });

    test('albums and artists are searchable', () async {
      await db.into(db.albums).insertOnConflictUpdate(AlbumsCompanion.insert(
            serverId: serverId,
            id: 'al1',
            name: 'Kodama',
            artist: const Value('Alcest'),
          ));
      await db.into(db.artists).insertOnConflictUpdate(ArtistsCompanion.insert(
            serverId: serverId,
            id: 'ar1',
            name: 'Alcest',
          ));

      final dao = SearchDao(db);
      expect((await dao.albums(serverId, 'kod').get()).single.id, 'al1');
      expect((await dao.artists(serverId, 'alc').get()).single.id, 'ar1');
      expect((await dao.albums(serverId, 'alcest').get()).single.id, 'al1');
    });
  });

  test('rebuildSearchIndex repairs an emptied index', () async {
    await _addTrack(db, serverId, 't1', 'Needle in haystack');
    await db.customStatement(
        "INSERT INTO track_fts(track_fts) VALUES('delete-all')");
    expect(await SearchDao(db).tracks(serverId, 'needle').get(), isEmpty);

    await db.rebuildSearchIndex();
    expect(await SearchDao(db).tracks(serverId, 'needle').get(), hasLength(1));
  });
}
