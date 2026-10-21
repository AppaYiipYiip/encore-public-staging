import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:drift/native.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/repos/library_repository.dart';
import 'package:flutter_test/flutter_test.dart';

/// Found on a friend's phone (2026-10-17): he opened the app and "Pink Floyd"
/// was in his library, though he had no music of theirs. His account has no
/// songs at all; the music server still lists an artist that another person's
/// library once shared (an artist record with an album count and nothing under
/// it). An artist the library holds nothing of is not part of the library.
void main() {
  late AppDatabase db;
  late int serverId;
  late LibraryRepository repo;

  setUp(() async {
    db = AppDatabase(NativeDatabase.memory());
    serverId = await db.into(db.servers).insert(ServersCompanion.insert(
          name: 'Home',
          username: 'friend',
          endpointsJson: '[]',
          createdAtMs: 0,
        ));
    repo = LibraryRepository(db, serverId);
  });

  tearDown(() => db.close());

  Future<void> artist(String id, String name, {int albumCount = 1}) =>
      db.into(db.artists).insert(ArtistsCompanion.insert(
          serverId: serverId,
          id: id,
          name: name,
          albumCount: Value(albumCount)));

  Future<void> album(String id, String artistId) =>
      db.into(db.albums).insert(AlbumsCompanion.insert(
          serverId: serverId,
          id: id,
          name: 'Album $id',
          artistId: Value(artistId)));

  Future<void> song(String id, String artistId, {int? deletedAtMs}) =>
      db.into(db.tracks).insert(TracksCompanion.insert(
            serverId: serverId,
            id: id,
            title: 'Song $id',
            artistId: Value(artistId),
            deletedAtMs: Value(deletedAtMs),
          ));

  test('an artist with no album and no song in the library is not listed',
      () async {
    await artist('ghost', 'Pink Floyd'); // says 1 album, holds none
    await artist('real', 'Alcest');
    await album('al1', 'real');
    await song('s1', 'real');

    final names = (await repo.watchArtists().first).map((a) => a.name);

    expect(names, ['Alcest']);
  });

  test('an artist who only appears on songs (no album of their own) is kept',
      () async {
    await artist('guest', 'A Guest', albumCount: 0);
    await song('s9', 'guest');

    final names = (await repo.watchArtists().first).map((a) => a.name);

    expect(names, ['A Guest']);
  });

  test('an artist whose only songs were deleted is not listed', () async {
    await artist('gone', 'Gone');
    await song('s2', 'gone', deletedAtMs: 1);

    expect(await repo.watchArtists().first, isEmpty);
  });
}
