import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:drift/native.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/repos/library_repository.dart';
import 'package:flutter_test/flutter_test.dart';

/// Owner, 7 Nov 2026: on "Forever" (Drake, Kanye West, Lil Wayne, Eminem) only one name could be pressed. The phone holds that file twice: an entry
/// made from the file's tags (the artists as ONE joined string) and the catalogue's (the real list). The list of artists is read from the entries of
/// the file together, the longest wins, and a joined string is never cut at its commas.
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

  Future<void> song(String id,
          {String? artistsJson, String? fileId, int? deletedAtMs}) =>
      db.into(db.tracks).insert(TracksCompanion.insert(
            serverId: serverId,
            id: id,
            title: 'Forever',
            artistsJson: Value(artistsJson),
            fileId: Value(fileId),
            deletedAtMs: Value(deletedAtMs),
          ));

  const joined = '["Drake, Kanye West, Lil Wayne, Eminem"]';
  const real = '["Drake","Kanye West","Lil Wayne","Eminem"]';

  test(
      'the entry made from the tags of a file takes the real list of the catalogue entry of the same file',
      () async {
    await song('sr_from_file', artistsJson: joined, fileId: 'f1');
    await song('sr_catalogue', artistsJson: real, fileId: 'f1');

    expect(await repo.songArtists('sr_from_file'),
        ['Drake', 'Kanye West', 'Lil Wayne', 'Eminem']);
    expect(await repo.songArtists('sr_catalogue'),
        ['Drake', 'Kanye West', 'Lil Wayne', 'Eminem']);
  });

  test('the plain row of the file itself finds them too', () async {
    await song('f1');
    await song('sr_from_file', artistsJson: joined, fileId: 'f1');
    await song('sr_catalogue', artistsJson: real, fileId: 'f1');

    expect(await repo.songArtists('f1'),
        ['Drake', 'Kanye West', 'Lil Wayne', 'Eminem']);
  });

  test('a joined string is never cut at its commas', () async {
    await song('sr_alone', artistsJson: '["Tyler, The Creator"]', fileId: 'f2');

    expect(await repo.songArtists('sr_alone'), ['Tyler, The Creator']);
  });

  test('a song by one artist, and a song nobody knows', () async {
    await song('sr_one', artistsJson: '["Radiohead"]');

    expect(await repo.songArtists('sr_one'), ['Radiohead']);
    expect(await repo.songArtists('nobody-has-this'), isEmpty);
  });

  test(
      'the entries of another file, a removed entry and damaged text change nothing',
      () async {
    await song('sr_a', artistsJson: joined, fileId: 'f1');
    await song('sr_other_file', artistsJson: '["A","B","C"]', fileId: 'f9');
    await song('sr_removed', artistsJson: real, fileId: 'f1', deletedAtMs: 5);
    await song('sr_bad', artistsJson: 'not json', fileId: 'f3');
    await song('sr_not_a_list', artistsJson: '{"a":1}', fileId: 'f4');

    expect(await repo.songArtists('sr_a'),
        ['Drake, Kanye West, Lil Wayne, Eminem']);
    expect(await repo.songArtists('sr_bad'), isEmpty);
    expect(await repo.songArtists('sr_not_a_list'), isEmpty);
  });
}
