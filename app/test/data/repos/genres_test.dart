import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:drift/native.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/repos/library_repository.dart';
import 'package:flutter_test/flutter_test.dart';

/// Search > Browse lists the genres of the library. Tags are typed by people
/// and tools, so "Progressive Rock" and "progressive rock" are the same genre
/// and must be one tile (docs/23, B36).
void main() {
  late AppDatabase db;
  late int serverId;
  late LibraryRepository repo;

  setUp(() async {
    db = AppDatabase(NativeDatabase.memory());
    serverId = await db.into(db.servers).insert(ServersCompanion.insert(
          name: 'Home',
          username: 'marwa',
          endpointsJson: '[]',
          createdAtMs: 0,
        ));
    repo = LibraryRepository(db, serverId);
  });

  tearDown(() => db.close());

  Future<void> album(String id, String? genre, {bool deleted = false}) =>
      db.into(db.albums).insert(AlbumsCompanion.insert(
            serverId: serverId,
            id: id,
            name: 'Album $id',
            genre: Value(genre),
            deletedAtMs: Value(deleted ? 1 : null),
          ));

  test('a genre spelled two ways is one tile with the combined count',
      () async {
    await album('a1', 'Progressive Rock');
    await album('a2', 'Progressive Rock');
    await album('a3', 'progressive rock');
    await album('a4', 'Shoegaze');

    final genres = await repo.watchGenres().first;

    expect(genres.map((g) => g.name), ['Progressive Rock', 'Shoegaze']);
    expect(genres.first.albums, 3);
  });

  test('the more common spelling is the one that is shown', () async {
    await album('a1', 'progressive rock');
    await album('a2', 'progressive rock');
    await album('a3', 'Progressive Rock');

    final genres = await repo.watchGenres().first;

    expect(genres.single.name, 'progressive rock');
    expect(genres.single.albums, 3);
  });

  test('a tie is settled the same way every time', () async {
    await album('a1', 'progressive rock');
    await album('a2', 'Progressive Rock');

    final genres = await repo.watchGenres().first;

    expect(genres.single.name, 'Progressive Rock');
  });

  test('deleted albums, missing and empty genres do not count', () async {
    await album('a1', 'Metal');
    await album('a2', 'metal', deleted: true);
    await album('a3', null);
    await album('a4', '');

    final genres = await repo.watchGenres().first;

    expect(genres.map((g) => (g.name, g.albums)), [('Metal', 1)]);
  });

  test('the biggest genres come first and the limit is applied after merging',
      () async {
    for (var i = 0; i < 3; i++) {
      await album('x$i', i.isEven ? 'Rock' : 'rock');
    }
    await album('y1', 'Jazz');
    await album('y2', 'Blues');

    final genres = await repo.watchGenres(limit: 2).first;

    expect(genres.map((g) => g.name), ['Rock', 'Blues']);
  });

  test('opening the merged tile lists the albums of both spellings', () async {
    await album('a1', 'Progressive Rock');
    await album('a2', 'progressive rock');
    await album('a3', 'Shoegaze');

    for (final asked in ['Progressive Rock', 'progressive rock']) {
      final albums = await repo.watchGenreAlbums(asked).first;
      expect(albums.map((a) => a.id).toSet(), {'a1', 'a2'}, reason: asked);
    }
  });
}
