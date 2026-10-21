import 'package:encore/data/catalogue/catalogue_models.dart';
import 'package:encore/features/detail/album_gap.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fake_catalogue.dart';

/// "Animals by Pink Floyd has 5 songs, not 2" (B39, found by the owner): an
/// album the library holds only part of should say so, and show the rest, from
/// the catalogue, only when the catalogue album is certainly the same one.
void main() {
  CatalogueAlbum album(
    String id,
    String title, {
    String artist = 'Pink Floyd',
    int tracks = 5,
  }) =>
      CatalogueAlbum(
        id: id,
        title: title,
        artistName: artist,
        artistId: 'artist-1',
        year: 1977,
        trackCount: tracks,
        recordType: 'album',
      );

  CatalogueTrack track(String id, String title, int no) => CatalogueTrack(
        id: id,
        title: title,
        artistName: 'Pink Floyd',
        albumTitle: 'Animals',
        trackNumber: no,
      );

  final animals = [
    track('t1', 'Pigs on the Wing 1', 1),
    track('t2', 'Dogs', 2),
    track('t3', 'Pigs (Three Different Ones)', 3),
    track('t4', 'Sheep', 4),
    track('t5', 'Pigs on the Wing 2', 5),
  ];

  const ownedTwo = [
    OwnedTrack(title: 'Dogs', number: 2),
    OwnedTrack(title: 'Sheep', number: 4),
  ];

  FakeCatalogue catalogue(
      {List<CatalogueAlbum>? albums,
      Map<String, List<CatalogueTrack>>? tracks}) {
    final c = FakeCatalogue.withAlbums(albums ?? [album('a1', 'Animals')]);
    c.tracksByAlbum.addAll(tracks ?? {'a1': animals});
    return c;
  }

  Future<AlbumGap?> look(
    FakeCatalogue c, {
    List<OwnedTrack> owned = ownedTwo,
    String artist = 'Pink Floyd',
    String title = 'Animals',
  }) =>
      findAlbumGap(catalogue: c, artist: artist, album: title, owned: owned);

  test('names what is missing from a partly owned album', () async {
    final gap = await look(catalogue());

    expect(gap!.total, 5);
    expect(gap.ownedCount, 2);
    expect(gap.missing.map((t) => t.title), [
      'Pigs on the Wing 1',
      'Pigs (Three Different Ones)',
      'Pigs on the Wing 2',
    ]);
  });

  test('nothing to say about an album the library holds whole', () async {
    final whole = [
      for (final t in animals)
        OwnedTrack(title: t.title, number: t.trackNumber),
    ];

    expect(await look(catalogue(), owned: whole), isNull);
  });

  test('case, accents and punctuation do not make a song look missing',
      () async {
    final owned = [
      const OwnedTrack(title: 'DOGS', number: 2),
      const OwnedTrack(title: 'sheep!', number: 4),
    ];

    final gap = await look(catalogue(), owned: owned);

    expect(gap!.missing.map((t) => t.title), isNot(contains('Dogs')));
    expect(gap.missing, hasLength(3));
  });

  test(
      'a song named a little differently is the same song when the number '
      'agrees', () async {
    final owned = [
      const OwnedTrack(title: 'Pigs on the Wing', number: 1),
      const OwnedTrack(title: 'Dogs', number: 2),
    ];

    final gap = await look(catalogue(), owned: owned);

    expect(gap!.missing.map((t) => t.title),
        isNot(contains('Pigs on the Wing 1')));
    expect(gap.missing, hasLength(3));
  });

  test('song names that line up with nothing are not guessed at', () async {
    // The library calls them by names of its own: whatever "missing" held
    // could be songs that are here.
    final owned = [
      const OwnedTrack(title: 'Hunde', number: 2),
      const OwnedTrack(title: 'Schafe', number: 4),
      const OwnedTrack(title: 'Schweine', number: 3),
    ];

    expect(await look(catalogue(), owned: owned), isNull);
  });

  test(
      'the real Animals: "Pigs On The Wing (Part One)" is "Pigs on the Wing 1"',
      () async {
    // What the owner's server holds for `tester` (2 of 5) against what the
    // catalogue calls the songs.
    final owned = [
      const OwnedTrack(title: 'Pigs On The Wing (Part One)', number: 1),
      const OwnedTrack(title: 'Dogs', number: 2),
    ];

    final gap = await look(catalogue(), owned: owned);

    expect(gap, isNotNull,
        reason: 'the very album the owner reported must be recognised');
    expect(gap!.total, 5);
    expect(gap.ownedCount, 2);
    expect(gap.missing.map((t) => t.title), [
      'Pigs (Three Different Ones)',
      'Sheep',
      'Pigs on the Wing 2',
    ]);
  });

  test('the same words at another position are another song', () async {
    // "Another Brick in the Wall" has three parts: the position tells them apart.
    final wall = [
      track('w1', 'Another Brick in the Wall (Part 1)', 1),
      track('w2', 'Another Brick in the Wall (Part 2)', 2),
    ];
    final c = catalogue(
        albums: [album('w', 'The Wall', tracks: 2)], tracks: {'w': wall});
    final owned = [
      const OwnedTrack(title: 'Another Brick in the Wall, Pt. 2', number: 2),
    ];

    final gap = await look(c, title: 'The Wall', owned: owned);

    expect(gap!.missing.map((t) => t.title),
        ['Another Brick in the Wall (Part 1)']);
  });

  test('a namesake by another artist is not this album', () async {
    final c = catalogue(albums: [
      album('a9', 'Animals', artist: 'Animals as Leaders', tracks: 12),
    ]);

    expect(await look(c), isNull);
  });

  test('a different album whose name merely starts the same is not this album',
      () async {
    final c = catalogue(albums: [album('a9', 'Animals Live', tracks: 9)]);

    expect(await look(c), isNull);
  });

  test('a remaster is the same album', () async {
    final c = catalogue(
        albums: [album('a2', 'Animals (2018 Remastered Version)')],
        tracks: {'a2': animals});

    expect((await look(c))!.total, 5);
  });

  test('of two editions it takes the one closest to what is owned', () async {
    final deluxe = [
      ...animals,
      track('t6', 'Bonus One', 6),
      track('t7', 'Bonus Two', 7),
    ];
    final c = catalogue(albums: [
      album('deluxe', 'Animals (Deluxe Edition)', tracks: 7),
      album('std', 'Animals'),
    ], tracks: {
      'deluxe': deluxe,
      'std': animals,
    });

    expect((await look(c))!.total, 5);
  });

  test('an edition with fewer songs than the library holds is not this album',
      () async {
    final c = catalogue(albums: [
      album('a3', 'Animals', tracks: 1)
    ], tracks: {
      'a3': [animals.first]
    });

    expect(await look(c), isNull);
  });

  test('no catalogue match, no answer', () async {
    expect(await look(catalogue(albums: const [])), isNull);
  });

  test('a catalogue with no songs for the album gives no answer', () async {
    expect(await look(catalogue(tracks: const {})), isNull);
  });

  test('an unreachable catalogue gives no answer and never throws', () async {
    expect(await look(_Broken()), isNull);
  });

  test('asks only for the artist and the album', () async {
    final c = catalogue();

    await look(c);

    expect(c.queries, ['Pink Floyd Animals']);
  });
}

class _Broken extends FakeCatalogue {
  @override
  Future<CatalogueResults> search(String query, {int limit = 8}) async =>
      throw const FormatException('offline');
}
