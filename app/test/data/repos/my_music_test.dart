import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:drift/native.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/repos/library_repository.dart';
import 'package:flutter_test/flutter_test.dart';

/// "My music" is the slice of a shared catalogue this account has a
/// relationship with (ADR-049). Everything else on the server must stay out.
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

  /// One album with one track (`<album>-t1`), by artist `ar-<album>`.
  Future<void> album(
    String id, {
    int? albumStarred,
    int? albumRating,
    int? albumPlays,
    int? trackStarred,
    int? trackPlays,
    int? trackRating,
    bool deleted = false,
  }) async {
    await db.into(db.artists).insert(ArtistsCompanion.insert(
        serverId: serverId, id: 'ar-$id', name: 'Artist $id'));
    await db.into(db.albums).insert(AlbumsCompanion.insert(
          serverId: serverId,
          id: id,
          name: 'Album $id',
          artistId: Value('ar-$id'),
          starredAtMs: Value(albumStarred),
          userRating: Value(albumRating),
          playCount: Value(albumPlays),
        ));
    await db.into(db.tracks).insert(TracksCompanion.insert(
          serverId: serverId,
          id: '$id-t1',
          title: 'Song $id',
          albumId: Value(id),
          artistId: Value('ar-$id'),
          starredAtMs: Value(trackStarred),
          playCount: Value(trackPlays),
          userRating: Value(trackRating),
          deletedAtMs: Value(deleted ? 1 : null),
        ));
  }

  Future<void> playlist(
    String id,
    String owner,
    List<String> trackIds, {
    bool readonly = false,
    bool deleted = false,
  }) async {
    await db.into(db.playlists).insert(PlaylistsCompanion.insert(
          serverId: serverId,
          id: id,
          name: 'List $id',
          owner: Value(owner),
          readonly: Value(readonly),
          deletedAtMs: Value(deleted ? 1 : null),
        ));
    for (var i = 0; i < trackIds.length; i++) {
      await db.into(db.playlistEntries).insert(PlaylistEntriesCompanion.insert(
          serverId: serverId,
          playlistId: id,
          position: i,
          trackId: trackIds[i]));
    }
  }

  test('what the account has played, liked, rated or downloaded is mine',
      () async {
    await album('starredTrack', trackStarred: 5);
    await album('playedTrack', trackPlays: 3);
    await album('ratedTrack', trackRating: 4);
    await album('starredAlbum', albumStarred: 7);
    await album('ratedAlbum', albumRating: 5);
    await album('playedAlbum', albumPlays: 2);
    await album('downloaded');
    await db.into(db.downloads).insert(DownloadsCompanion.insert(
        serverId: serverId, trackId: 'downloaded-t1', updatedAtMs: 0));
    await album('heardHere');
    await db.into(db.playHistory).insert(PlayHistoryCompanion.insert(
        serverId: serverId, trackId: 'heardHere-t1', playedAtMs: 1));
    await album('untouched');

    final mine = await repo.loadMyMusic('marwa');

    expect(
        mine.albumIds,
        {
          'starredTrack',
          'playedTrack',
          'ratedTrack',
          'starredAlbum',
          'ratedAlbum',
          'playedAlbum',
          'downloaded',
          'heardHere',
        },
        reason: 'an album nobody touched is somebody else\'s');
    expect(mine.artistIds, contains('ar-starredTrack'));
    expect(mine.artistIds, isNot(contains('ar-untouched')));
  });

  test('songs in my own playlists count; smart and other people\'s do not',
      () async {
    await album('inMine');
    await album('inSmart');
    await album('inSaras');
    await album('inDeletedList');
    await playlist('p1', 'marwa', ['inMine-t1']);
    await playlist('p2', 'marwa', ['inSmart-t1'], readonly: true);
    await playlist('p3', 'sara', ['inSaras-t1']);
    await playlist('p4', 'marwa', ['inDeletedList-t1'], deleted: true);

    final mine = await repo.loadMyMusic('marwa');

    expect(mine.albumIds, {'inMine'},
        reason: 'generated playlists would make the whole library "mine"');
  });

  test('owner names match without regard to case', () async {
    await album('a');
    await playlist('p1', 'Marwa', ['a-t1']);

    expect((await repo.loadMyMusic('marwa')).albumIds, {'a'});
    expect((await repo.loadMyMusic('MARWA')).albumIds, {'a'});
  });

  test('a starred artist is mine before any song of theirs was played',
      () async {
    await album('quiet');
    await (db.update(db.artists)..where((a) => a.id.equals('ar-quiet')))
        .write(const ArtistsCompanion(starredAtMs: Value(9)));

    final mine = await repo.loadMyMusic('marwa');

    expect(mine.artistIds, {'ar-quiet'});
    expect(mine.albumIds, isEmpty);
  });

  test('tombstoned songs and albums are ignored', () async {
    await album('gone', trackStarred: 5, deleted: true);

    expect((await repo.loadMyMusic('marwa')).albumIds, isEmpty);
  });

  test('a download that is no longer wanted does not count', () async {
    await album('unpinned');
    await db.into(db.downloads).insert(DownloadsCompanion.insert(
          serverId: serverId,
          trackId: 'unpinned-t1',
          updatedAtMs: 0,
          orphanedAtMs: const Value(5),
        ));

    expect((await repo.loadMyMusic('marwa')).albumIds, isEmpty);
  });

  test('watchMyMusic follows the library and re-emits only on change',
      () async {
    await album('first', trackPlays: 1);
    final seen = <Set<String>>[];
    final sub = repo.watchMyMusic('marwa').listen((m) => seen.add(m.albumIds));
    addTearDown(sub.cancel);
    await pumpEventQueue();
    expect(seen.single, {'first'});

    await album('second', trackStarred: 1);
    // Updates are coalesced over a few seconds; wait them out for real.
    await Future<void>.delayed(const Duration(seconds: 4));

    expect(seen.last, {'first', 'second'});
    expect(seen.length, 2, reason: 'no duplicate emissions');
  });
}
