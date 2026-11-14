import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:drift/native.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/repos/library_repository.dart';
import 'package:flutter_test/flutter_test.dart';

/// N-24: the artist page's Play and Shuffle play "every song of this artist the server holds". The page needs that list as a stream (it
/// dims the buttons when there is nothing to play and follows a sync); Android Auto asks the same question once (`artist:ID`). One query
/// answers both, so the page and the car cannot disagree on what "all of an artist" is.
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

  Future<void> song(
    String id,
    String artistId, {
    String album = 'A',
    int? disc,
    int? no,
    int? deletedAtMs,
  }) =>
      db.into(db.tracks).insert(TracksCompanion.insert(
            serverId: serverId,
            id: id,
            title: 'Song $id',
            artistId: Value(artistId),
            album: Value(album),
            discNo: Value(disc),
            trackNo: Value(no),
            deletedAtMs: Value(deletedAtMs),
          ));

  Future<void> populate() async {
    await song('b2', 'ar1', album: 'B', no: 2);
    await song('a2', 'ar1', album: 'A', no: 2);
    await song('a1', 'ar1', album: 'A', no: 1);
    await song('b1', 'ar1', album: 'B', no: 1);
    await song('other', 'ar2', album: 'A', no: 1);
    await song('gone', 'ar1', album: 'A', no: 3, deletedAtMs: 5);
  }

  test('the stream lists the artist\'s songs in album, then track order',
      () async {
    await populate();

    final ids = (await repo.watchArtistTracks('ar1').first).map((t) => t.id);

    expect(ids, ['a1', 'a2', 'b1', 'b2'],
        reason: 'another artist\'s song and a deleted song are not part of it');
  });

  test('the one-shot read and the stream are the same list', () async {
    await populate();

    final once = (await repo.artistTracks('ar1')).map((t) => t.id).toList();
    final stream =
        (await repo.watchArtistTracks('ar1').first).map((t) => t.id).toList();

    expect(stream, once);
  });

  test('the stream follows a song that arrives later', () async {
    final seen = <List<String>>[];
    final sub = repo
        .watchArtistTracks('ar1')
        .listen((tracks) => seen.add([for (final t in tracks) t.id]));
    await pumpEventQueue();
    await song('a1', 'ar1', no: 1);
    await pumpEventQueue();
    await sub.cancel();

    expect(seen.first, isEmpty);
    expect(seen.last, ['a1']);
  });
}
