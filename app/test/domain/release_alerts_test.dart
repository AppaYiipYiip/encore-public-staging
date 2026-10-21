import 'package:encore/domain/release_alerts.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  AlbumArrival arrival(String album, String artist, int at,
          {String? artistId}) =>
      AlbumArrival(
        albumId: album,
        albumName: 'Album $album',
        artistId: artistId ?? 'ar-$artist',
        artistName: artist,
        createdAtMs: at,
      );

  group('pickArrivals', () {
    test('only albums newer than the last look, by artists I play', () {
      final picked = pickArrivals(
        [
          arrival('old', 'Alcest', 100),
          arrival('new', 'Alcest', 300),
          arrival('stranger', 'Strangers', 400),
        ],
        myArtistIds: {'ar-Alcest'},
        sinceMs: 200,
        notified: {},
      );

      expect(picked.map((a) => a.albumId), ['new']);
    });

    test('an album announced before is not announced again', () {
      final picked = pickArrivals(
        [arrival('new', 'Alcest', 300)],
        myArtistIds: {'ar-Alcest'},
        sinceMs: 200,
        notified: {'new'},
      );

      expect(picked, isEmpty);
    });

    test('newest first and capped', () {
      final picked = pickArrivals(
        [for (var i = 1; i <= 20; i++) arrival('a$i', 'Alcest', 1000 + i)],
        myArtistIds: {'ar-Alcest'},
        sinceMs: 0,
        notified: {},
        max: 5,
      );

      expect(picked.length, 5);
      expect(picked.first.albumId, 'a20');
    });
  });

  group('pickReleases', () {
    final today = DateTime.utc(2026, 10, 15);

    ReleaseCandidate release(
            String id, String artist, String title, String? date,
            {String? kind}) =>
        ReleaseCandidate(
          catalogueAlbumId: id,
          title: title,
          artistName: artist,
          releaseDate: date,
          kind: kind,
        );

    test('recent, not owned, not announced', () {
      final picked = pickReleases(
        [
          release('1', 'Alcest', 'Fresh', '2026-10-10'),
          release('2', 'Alcest', 'Old', '2025-01-01'),
          release('3', 'Alcest', 'Owned', '2026-10-01'),
          release('4', 'Alcest', 'Told', '2026-10-02'),
        ],
        today: today,
        notified: {'4'},
        owned: (r) => r.title == 'Owned',
      );

      expect(picked.map((r) => r.catalogueAlbumId), ['1']);
    });

    test('an upcoming release waits for its day', () {
      final picked = pickReleases(
        [
          release('9', 'Alcest', 'Tomorrow', '2026-10-16'),
          release('8', 'Alcest', 'Today', '2026-10-15'),
        ],
        today: today,
        notified: {},
        owned: (_) => false,
      );

      expect(picked.map((r) => r.catalogueAlbumId), ['8']);
    });

    test('releases without a date, and duplicates, are dropped', () {
      final picked = pickReleases(
        [
          release('1', 'Alcest', 'Same', '2026-10-10'),
          release('2', 'ALCEST', 'same', '2026-10-11'),
          release('3', 'Alcest', 'Undated', null),
        ],
        today: today,
        notified: {},
        owned: (_) => false,
      );

      expect(picked.length, 1);
    });

    test('newest first', () {
      final picked = pickReleases(
        [
          release('a', 'Alcest', 'A', '2026-10-01'),
          release('b', 'Opeth', 'B', '2026-10-12'),
        ],
        today: today,
        notified: {},
        owned: (_) => false,
      );

      expect(picked.map((r) => r.catalogueAlbumId), ['b', 'a']);
    });
  });

  group('copy', () {
    test('one arrival opens that album', () {
      final copy = copyForArrivals([arrival('al1', 'Alcest', 5)])!;

      expect(copy.title, 'New from Alcest');
      expect(copy.body, 'Album al1 is on your server now.');
      expect(copy.route, '/home/album/al1');
      expect(copy.ids, ['al1']);
    });

    test('several by one artist open the artist', () {
      final copy = copyForArrivals([
        arrival('a', 'Alcest', 5),
        arrival('b', 'Alcest', 6),
      ])!;

      expect(copy.title, 'New from Alcest');
      expect(copy.body, '2 new albums are on your server.');
      expect(copy.route, '/home/artist/ar-Alcest');
    });

    test('several artists are listed, with a count beyond two', () {
      final two = copyForArrivals([
        arrival('a', 'Alcest', 5),
        arrival('b', 'Opeth', 6),
      ])!;
      final four = copyForArrivals([
        arrival('a', 'Alcest', 5),
        arrival('b', 'Opeth', 6),
        arrival('c', 'Katatonia', 7),
        arrival('d', 'Periphery', 8),
      ])!;

      expect(two.body, 'Alcest and Opeth - on your server now.');
      expect(four.body, 'Alcest, Opeth and 2 more - on your server now.');
      expect(four.route, '/home');
    });

    test('a release says it is not on the server and offers the request', () {
      final copy = copyForReleases([
        const ReleaseCandidate(
          catalogueAlbumId: '77',
          title: 'Kodama',
          artistName: 'Alcest',
          kind: 'ep',
        ),
      ])!;

      expect(copy.title, 'Alcest has new music');
      expect(copy.body, contains('"Kodama" (EP)'));
      expect(copy.body, contains('request'));
      expect(copy.route, '/home/catalogue/album/77');
    });

    test('nothing to say gives no notification', () {
      expect(copyForArrivals(const []), isNull);
      expect(copyForReleases(const []), isNull);
      expect(copyForImports(const []), isNull);
      expect(copyForRequests(const []), isNull);
    });
  });

  group('imports', () {
    ImportSnapshot snap(String name, int tracks, int have) =>
        ImportSnapshot(name: name, tracks: tracks, inLibrary: have);

    test('the first look is a baseline, never news', () {
      final updates = pickImportUpdates(
        [snap('Road trip', 50, 20)],
        seen: {},
      );

      expect(updates, isEmpty);
    });

    test('a few songs are not worth a ping, a tenth of the list is', () {
      final few =
          pickImportUpdates([snap('List', 100, 23)], seen: {'List': 20});
      final enough =
          pickImportUpdates([snap('List', 100, 31)], seen: {'List': 20});

      expect(few, isEmpty);
      expect(enough.single.gained, 11);
      expect(enough.single.finished, isFalse);
    });

    test('finishing always counts, even for a small gain', () {
      final updates =
          pickImportUpdates([snap('List', 100, 100)], seen: {'List': 98});

      expect(updates.single.finished, isTrue);
    });

    test('an import that was already complete stays quiet', () {
      final updates =
          pickImportUpdates([snap('List', 10, 10)], seen: {'List': 10});

      expect(updates, isEmpty);
    });

    test('words: one import, and several', () {
      final one = copyForImports([
        ImportUpdate(
            snapshot: snap('Road trip', 50, 32), gained: 12, finished: false),
      ])!;
      final done = copyForImports([
        ImportUpdate(
            snapshot: snap('Road trip', 50, 50), gained: 3, finished: true),
      ])!;
      final many = copyForImports([
        ImportUpdate(snapshot: snap('A', 10, 10), gained: 4, finished: true),
        ImportUpdate(snapshot: snap('B', 20, 12), gained: 6, finished: false),
      ])!;

      expect(one.title, '"Road trip" is filling up');
      expect(one.body, '12 more songs arrived - 32 of 50 are on your server.');
      expect(done.title, '"Road trip" is complete');
      expect(many.title, 'Your imports are filling up');
      expect(many.body, 'A and B - more songs arrived.');
      expect(one.route, '/settings/import');
    });
  });

  group('requests', () {
    test('one album request opens that album', () {
      final copy = copyForRequests(const [
        RequestArrival(
            artist: 'Alcest', album: 'Kodama', route: '/home/album/al1'),
      ])!;

      expect(copy.title, 'Your request arrived');
      expect(copy.body, '"Kodama" by Alcest is in your library now.');
      expect(copy.route, '/home/album/al1');
    });

    test('an artist request is worded as the artist', () {
      final copy = copyForRequests(const [
        RequestArrival(artist: 'Alcest', route: '/home/artist/ar1'),
      ])!;

      expect(copy.body, 'Alcest is in your library now.');
    });

    test('several are counted and listed', () {
      final copy = copyForRequests(const [
        RequestArrival(artist: 'Alcest', album: 'Kodama', route: '/x'),
        RequestArrival(artist: 'Opeth', route: '/y'),
        RequestArrival(artist: 'Katatonia', album: 'Dead End', route: '/z'),
      ])!;

      expect(copy.title, '3 requests arrived');
      expect(copy.body, 'Kodama, Opeth and 1 more - in your library now.');
      expect(copy.route, '/library');
    });
  });
}
