import 'package:drift/drift.dart' show Value;
import 'package:drift/native.dart';
import 'package:encore/core/clock.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/repos/request_repository.dart';
import 'package:encore/domain/text_match.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('normalizeForMatch', () {
    test('ignores case, accents, punctuation and "The"', () {
      expect(normalizeForMatch('The Mars Volta'), 'mars volta');
      expect(normalizeForMatch('Sigur Rós'), 'sigur ros');
      expect(normalizeForMatch('AC/DC'), 'ac dc');
      expect(normalizeForMatch("Guns N' Roses"), 'guns n roses');
      expect(normalizeForMatch('Mötley Crüe'), 'motley crue');
    });

    test('drops edition suffixes only at the end', () {
      expect(normalizeForMatch('Kodama (Deluxe Edition)'), 'kodama');
      expect(normalizeForMatch('Ghost Reveries - Remastered 2008'),
          'ghost reveries');
      expect(normalizeForMatch('Remaster of Souls'), 'remaster of souls');
    });

    test('& and "and" are the same', () {
      expect(normalizeForMatch('Simon & Garfunkel'),
          normalizeForMatch('Simon and Garfunkel'));
    });

    test('non-latin letters survive', () {
      expect(normalizeForMatch('Мумий Тролль'), 'мумий тролль');
      expect(normalizeForMatch('椎名林檎'), '椎名林檎');
    });

    test('matchKey pairs artist and title', () {
      expect(matchKey('Alcest', 'Kodama'), matchKey('ALCEST', 'kodama'));
      expect(matchKey('Alcest', 'Kodama'),
          isNot(matchKey('Alcest', 'Écailles de lune')));
    });
  });

  group('RequestRepository', () {
    late AppDatabase db;
    late RequestRepository repo;
    late int serverId;
    late FakeClock clock;

    setUp(() async {
      db = AppDatabase(NativeDatabase.memory());
      clock = FakeClock(DateTime.utc(2026, 10, 15, 9));
      serverId = await db.into(db.servers).insert(ServersCompanion.insert(
          name: 'T', username: 'u', endpointsJson: '[]', createdAtMs: 0));
      repo = RequestRepository(db, serverId, clock: clock);
    });

    tearDown(() => db.close());

    Future<void> addAlbum(String artist, String name,
        {String artistId = 'ar1'}) async {
      await db.into(db.artists).insertOnConflictUpdate(ArtistsCompanion.insert(
            serverId: serverId,
            id: artistId,
            name: artist,
            albumCount: const Value(1),
          ));
      await db.into(db.albums).insert(AlbumsCompanion.insert(
            serverId: serverId,
            id: 'al-$name',
            name: name,
            artist: Value(artist),
            artistId: Value(artistId),
          ));
    }

    test('creating twice returns the same open request', () async {
      final a = await repo.create(artist: 'Alcest', album: 'Kodama');
      final b = await repo.create(artist: 'ALCEST', album: 'kodama');
      expect(b.id, a.id);
      expect((await repo.watchAll().first).length, 1);
    });

    test('an artist request and an album request are different', () async {
      await repo.create(artist: 'Alcest');
      await repo.create(artist: 'Alcest', album: 'Kodama');
      expect((await repo.watchAll().first).length, 2);
    });

    test('a failed request can be retried (same row, back to submitted)',
        () async {
      final a = await repo.create(artist: 'Alcest', album: 'Kodama');
      await repo.setState(a.id, RequestState.failed, detail: 'offline');
      final retry = await repo.create(artist: 'Alcest', album: 'Kodama');
      expect(retry.id, a.id);
      expect(retry.state, RequestState.submitted);
      expect(retry.detail, isNull);
    });

    test('watchFor emits the state for that album', () async {
      await repo.create(artist: 'Alcest', album: 'Kodama');
      final row = await repo.watchFor('alcest', 'KODAMA').first;
      expect(row!.state, RequestState.submitted);
      expect(await repo.watchFor('Alcest', 'Other').first, isNull);
    });

    test('the album arriving in the library resolves the request', () async {
      final r = await repo.create(artist: 'Alcest', album: 'Kodama');
      await repo.setState(r.id, RequestState.requested);
      expect(await repo.resolveAgainstLibrary(), isEmpty);

      await addAlbum('Alcest', 'Kodama (Deluxe Edition)');
      final arrived = await repo.resolveAgainstLibrary();
      expect(arrived.single.id, r.id);
      final after = await repo.find('Alcest', 'Kodama');
      expect(after!.state, RequestState.inLibrary);
    });

    test('a different album by the same artist does not resolve it', () async {
      final r = await repo.create(artist: 'Alcest', album: 'Kodama');
      await repo.setState(r.id, RequestState.requested);
      await addAlbum('Alcest', 'Écailles de Lune');
      expect(await repo.resolveAgainstLibrary(), isEmpty);
    });

    test('an artist request resolves when the artist has albums', () async {
      final r = await repo.create(artist: 'Alcest');
      await repo.setState(r.id, RequestState.requested);
      await addAlbum('Alcest', 'Kodama');
      expect((await repo.resolveAgainstLibrary()).length, 1);
    });

    test('LibraryMatcher knows what is owned', () async {
      await addAlbum('Opeth', 'Ghost Reveries', artistId: 'ar3');
      final m = LibraryMatcher(db, serverId);
      expect(await m.hasArtist('opeth'), isTrue);
      expect(await m.hasAlbum('Opeth', 'Ghost Reveries (Remastered)'), isTrue);
      expect(await m.hasAlbum('Opeth', 'Blackwater Park'), isFalse);
      expect(await m.hasArtist('Periphery'), isFalse);
    });

    test('LibraryMatcher sees an owned album whose title has a ligature',
        () async {
      await addAlbum('Tool', 'Ænima', artistId: 'ar9');
      final m = LibraryMatcher(db, serverId);
      expect(await m.hasAlbum('TOOL', 'Ænima'), isTrue);
      expect(await m.hasAlbum('Tool', 'Aenima'), isTrue);
      expect(await m.hasAlbum('Tool', 'Lateralus'), isFalse);
    });
  });
}
