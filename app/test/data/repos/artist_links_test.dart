import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:drift/native.dart';
import 'package:encore/data/api/opensubsonic/models.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/repos/library_repository.dart';
import 'package:encore/data/sync/library_writer.dart';
import 'package:flutter_test/flutter_test.dart';

/// Owner, 7 Nov 2026: pressing "Post Malone" in the player (also on the version of "Sunflower" that shows only him) opened a page that spun for
/// ever. The keeper writes the artists of a song joined into one tag ("Post Malone, Swae Lee"); the music server makes an artist of that whole
/// name for the song, with no album and outside its artist index, so the phone never gets it and the song's artist link points at nothing. On a
/// freshly signed-in phone: 382 of 4,719 songs, 145 such artists, 159 of the songs showing a single artist; every one had an album whose artist the
/// phone had.
void main() {
  late AppDatabase db;
  late int serverId;
  late LibraryRepository repo;
  late LibraryWriter writer;

  setUp(() async {
    db = AppDatabase(NativeDatabase.memory());
    serverId = await db.into(db.servers).insert(ServersCompanion.insert(
          name: 'Home',
          username: 'friend',
          endpointsJson: '[]',
          createdAtMs: 0,
        ));
    repo = LibraryRepository(db, serverId);
    writer = LibraryWriter(db);
  });

  tearDown(() => db.close());

  Future<void> artist(String id, String name, {int? deletedAtMs}) =>
      db.into(db.artists).insert(ArtistsCompanion.insert(
          serverId: serverId,
          id: id,
          name: name,
          albumCount: const Value(1),
          deletedAtMs: Value(deletedAtMs)));

  Future<void> album(String id, String? artistId, {int? deletedAtMs}) =>
      db.into(db.albums).insert(AlbumsCompanion.insert(
          serverId: serverId,
          id: id,
          name: 'Album $id',
          artistId: Value(artistId),
          deletedAtMs: Value(deletedAtMs)));

  Future<void> song(String id,
          {String? artistId, String? albumId, String? artist}) =>
      db.into(db.tracks).insert(TracksCompanion.insert(
            serverId: serverId,
            id: id,
            title: 'Song $id',
            artistId: Value(artistId),
            albumId: Value(albumId),
            artist: Value(artist),
          ));

  Future<String?> linkOf(String songId) async =>
      (await (db.select(db.tracks)..where((t) => t.id.equals(songId)))
              .getSingle())
          .artistId;

  group('the artist that stands for an artist the phone does not have', () {
    test('is the artist of the albums the songs are on', () async {
      await artist('pm', 'Post Malone');
      await album('al1', 'pm');
      await song('s1',
          artistId: 'pm-sl', albumId: 'al1', artist: 'Post Malone, Swae Lee');
      await song('s2',
          artistId: 'pm-sl', albumId: 'al1', artist: 'Post Malone');

      expect(await repo.artistStandIn('pm-sl'), 'pm');
    });

    test('is the album artist most songs are on, when there are several',
        () async {
      await artist('a', 'A');
      await artist('b', 'B');
      await album('al-a', 'a');
      await album('al-b', 'b');
      await song('s1', artistId: 'x', albumId: 'al-a');
      await song('s2', artistId: 'x', albumId: 'al-b');
      await song('s3', artistId: 'x', albumId: 'al-b');

      expect(await repo.artistStandIn('x'), 'b');
    });

    test(
        'is nobody when no song is on an album of an artist the phone has '
        '(an album of an artist the phone lacks, a removed album, no album)',
        () async {
      await artist('gone', 'Gone', deletedAtMs: 5);
      await album('al-gone', 'gone');
      await album('al-none', null);
      await album('al-removed', 'gone', deletedAtMs: 7);
      await song('s1', artistId: 'x', albumId: 'al-gone');
      await song('s2', artistId: 'x', albumId: 'al-none');
      await song('s3', artistId: 'x', albumId: 'al-removed');
      await song('s4', artistId: 'x');

      expect(await repo.artistStandIn('x'), isNull);
      expect(await repo.artistStandIn('nobody-has-this'), isNull);
    });

    test('the name the songs carry for it is the one used most', () async {
      await song('s1', artistId: 'x', artist: 'Post Malone, Swae Lee');
      await song('s2', artistId: 'x', artist: 'Post Malone, Swae Lee');
      await song('s3', artistId: 'x', artist: 'Post Malone');

      expect(await repo.artistNameOf('x'), 'Post Malone, Swae Lee');
      expect(await repo.artistNameOf('nobody-has-this'), isNull);
    });
  });

  group('a song written for an artist the phone does not list', () {
    SsSong ssSong(String id, {String? artistId, String? albumId}) => SsSong(
          id: id,
          title: 'Song $id',
          artistId: artistId,
          albumId: albumId,
          artist: 'Post Malone, Swae Lee',
        );

    test('is linked to the artist of its album, whatever it shows', () async {
      await artist('pm', 'Post Malone');
      await album('al1', 'pm');

      await writer.upsertTracks(
          serverId, null, [ssSong('s1', artistId: 'pm-sl', albumId: 'al1')]);

      expect(await linkOf('s1'), 'pm');
    });

    test('keeps its artist when the artist is listed', () async {
      await artist('pm', 'Post Malone');
      await artist('other', 'Other');
      await album('al1', 'other');

      await writer.upsertTracks(
          serverId, null, [ssSong('s1', artistId: 'pm', albumId: 'al1')]);

      expect(await linkOf('s1'), 'pm',
          reason: "its own artist, not the album's");
    });

    test(
        'keeps its link when its album has no artist the phone has (the page then looks the artist up by name)',
        () async {
      await album('al-none', null);

      await writer.upsertTracks(serverId, null, [
        ssSong('s1', artistId: 'pm-sl', albumId: 'al-none'),
        ssSong('s2', artistId: 'pm-sl'),
      ]);

      expect(await linkOf('s1'), 'pm-sl');
      expect(await linkOf('s2'), 'pm-sl');
    });

    test('a song with no artist link stays without one', () async {
      await artist('pm', 'Post Malone');
      await album('al1', 'pm');

      await writer.upsertTracks(serverId, null, [ssSong('s1', albumId: 'al1')]);

      expect(await linkOf('s1'), isNull);
    });

    test(
        'songs that were written before are put right by the same statement '
        '(the first sync after the update)', () async {
      await artist('pm', 'Post Malone');
      await album('al1', 'pm');
      await song('s1', artistId: 'pm-sl', albumId: 'al1');
      await song('s2', artistId: 'pm', albumId: 'al1');

      final changed = await writer.linkSongsToListedArtists(serverId);

      expect(changed, 1);
      expect(await linkOf('s1'), 'pm');
      expect(await writer.linkSongsToListedArtists(serverId), 0,
          reason: 'nothing left to put right');
    });
  });
}
