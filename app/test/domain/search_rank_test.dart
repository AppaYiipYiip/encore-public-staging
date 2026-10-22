import 'dart:convert';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:encore/data/catalogue/deezer_client.dart';
import 'package:encore/domain/search_rank.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fake_http.dart';

/// P1-07: one ranked list, the best answer on top whether the library has it or not (E5: "radiohead weird fishes" came 6th).
void main() {
  group('a song', () {
    test('artist and title, in either order, is the best answer there is', () {
      expect(
          songMatch('radiohead weird fishes',
              artist: 'Radiohead', title: 'Weird Fishes / Arpeggi'),
          lessThan(1));
      expect(
          songMatch('daft punk instant crush',
              artist: 'Daft Punk',
              title: 'Instant Crush (feat. Julian Casablancas)'),
          1,
          reason: 'a featured artist is not part of the name');
      expect(
          songMatch('instant crush daft punk',
              artist: 'Daft Punk', title: 'Instant Crush'),
          1);
    });

    test('the title alone, exactly, is nearly as good', () {
      expect(
          songMatch('blinding lights',
              artist: 'The Weeknd', title: 'Blinding Lights'),
          0.95);
    });

    test('dots and apostrophes join letters, on both sides', () {
      expect(
          songMatch('ny state of mind',
              artist: 'Nas', title: 'N.Y. State of Mind'),
          0.95);
      expect(
          songMatch('gods plan', artist: 'Drake', title: "God's Plan"), 0.95);
      expect(
          songMatch("god's plan", artist: 'Drake', title: "God's Plan"), 0.95);
    });

    test('an edition mark is not part of the name', () {
      expect(
          songMatch('hotel california',
              artist: 'Eagles', title: 'Hotel California (2013 Remaster)'),
          0.95);
    });

    test(
        'a cover or a tribute that merely contains the words ranks below the real song',
        () {
      final real =
          songMatch('opeth windowpane', artist: 'Opeth', title: 'Windowpane');
      final cover = songMatch('opeth windowpane',
          artist: '8-Bit Arcade', title: 'Windowpane (8-Bit Opeth Emulation)');
      expect(real, greaterThan(cover));
    });

    test('a shorter title beats a longer one that contains it', () {
      final plain = songMatch('mazzy star fade into you',
          artist: 'Mazzy Star', title: 'Fade Into You');
      final remix = songMatch('mazzy star fade into you',
          artist: 'Mazzy Star', title: 'Fade Into You (The Avener Rework)');
      expect(plain, greaterThan(remix));
    });

    test('only some of the typed words found is a weak answer', () {
      expect(
          songMatch('radiohead weird fishes',
              artist: 'Josh Cohen', title: 'Weird Fishes'),
          lessThan(0.4));
      expect(songMatch('abc', artist: 'Someone', title: 'Else'), 0);
      expect(songMatch('', artist: 'x', title: 'y'), 0);
    });

    test('accents and case do not matter', () {
      expect(songMatch('beyonce halo', artist: 'Beyoncé', title: 'Halo'), 1);
      expect(songMatch('BEYONCÉ HALO', artist: 'beyonce', title: 'halo'), 1);
    });
  });

  group('an artist and an album', () {
    test('the exact name is best, a start of it next', () {
      expect(artistMatch('cairokee', 'Cairokee'), 0.95);
      expect(artistMatch('cairo', 'Cairokee'), 0.7);
      expect(artistMatch('rokee', 'Cairokee'), 0);
      expect(artistMatch('billie eilish', 'Billie Eilish & ROSALÍA'), 0.7);
      expect(artistMatch('bilie eilsh', 'Billie Eilish'), 0.6,
          reason: 'a typo the catalogue corrects');
      expect(artistMatch('damian', 'Billie Eilish'), 0);
      expect(artistMatch('xyzzy', 'Billie Eilish'), 0);
    });

    test('an album by its title, or with its artist', () {
      expect(
          albumMatch('in rainbows', title: 'In Rainbows', artist: 'Radiohead'),
          0.9);
      expect(
          albumMatch('radiohead in rainbows',
              title: 'In Rainbows', artist: 'Radiohead'),
          0.97);
      expect(albumMatch('rainbows', title: 'In Rainbows', artist: 'Radiohead'),
          0.5);
    });
  });

  group('the order', () {
    test(
        'score first, then what is already in the library, then the order the catalogue gave',
        () {
      final ranked = rankHits([
        const Ranked('c-first', 0.9, owned: false),
        const Ranked('c-second', 0.9, owned: false),
        const Ranked('mine', 0.9, owned: true),
        const Ranked('better', 0.95, owned: false),
        const Ranked('worse', 0.5, owned: true),
      ]);
      expect([for (final h in ranked) h.value],
          ['better', 'mine', 'c-first', 'c-second', 'worse']);
    });
  });

  group('the top result', () {
    test('the best of the three wins', () {
      expect(
          pickTop(song: 0.6, artist: 0.95, album: 0.5)!.kind, HitKind.artist);
      expect(pickTop(song: 1, artist: 0.55, album: 0.97)!.kind, HitKind.song);
      expect(pickTop(song: 0.5, artist: 0.2, album: 0.9)!.kind, HitKind.album);
    });

    test('an exact tie goes to the artist, then the album, then the song', () {
      expect(pickTop(song: 0.95, artist: 0.95)!.kind, HitKind.artist);
      expect(pickTop(song: 0.9, album: 0.9)!.kind, HitKind.album);
    });

    test('an artist nobody knows does not take the place of the exact song',
        () {
      expect(pickTop(song: 0.95, artist: 0.95, artistWellKnown: false)!.kind,
          HitKind.song);
    });

    test('loose matches have no obvious answer, so nothing is on top', () {
      expect(pickTop(song: 0.4, artist: 0.2, album: 0.3), isNull);
      expect(pickTop(), isNull);
    });
  });

  group('twenty real searches (answers recorded from Deezer on 2026-10-22)',
      () {
    final recorded =
        jsonDecode(File('test/fixtures/deezer/search.json').readAsStringSync())
            as Map<String, dynamic>;

    final adapter = FakeHttpAdapter(routes: {
      for (final kind in ['artist', 'album', 'track'])
        '/search/$kind': (request) => FakeResponse.json({
              'data': (recorded[request.uri.queryParameters['q']]
                  as Map<String, dynamic>)[kind],
            }),
    });
    final client = DeezerClient(
        dio: Dio(BaseOptions(baseUrl: 'https://api.deezer.com'))
          ..httpClientAdapter = adapter);

    /// What the person typed -> what they meant: ('song'|'artist', artist, title or null).
    const intended = <String, (HitKind, String, String?)>{
      'daft punk instant crush': (HitKind.song, 'Daft Punk', 'Instant Crush'),
      'radiohead weird fishes': (HitKind.song, 'Radiohead', 'Weird Fishes'),
      'fairuz kifak inta': (HitKind.song, 'Fairuz', 'Kifak Inta'),
      'opeth windowpane': (HitKind.song, 'Opeth', 'Windowpane'),
      'nas ny state of mind': (HitKind.song, 'Nas', 'State of Mind'),
      'beach house space song': (HitKind.song, 'Beach House', 'Space Song'),
      'mazzy star fade into you': (HitKind.song, 'Mazzy Star', 'Fade Into You'),
      'blinding lights': (HitKind.song, 'The Weeknd', 'Blinding Lights'),
      'the weeknd blinding lights': (
        HitKind.song,
        'The Weeknd',
        'Blinding Lights'
      ),
      'taylor swift cardigan': (HitKind.song, 'Taylor Swift', 'cardigan'),
      'kendrick lamar humble': (HitKind.song, 'Kendrick Lamar', 'HUMBLE'),
      'drake gods plan': (HitKind.song, 'Drake', "God's Plan"),
      'tame impala let it happen': (
        HitKind.song,
        'Tame Impala',
        'Let It Happen'
      ),
      'cairokee': (HitKind.artist, 'Cairokee', null),
      'oum kalthoum enta omri': (HitKind.song, 'Umm Kulthum', 'انت عمري'),
      'pink floyd comfortably numb': (
        HitKind.song,
        'Pink Floyd',
        'Comfortably Numb'
      ),
      'billie eilish': (HitKind.artist, 'Billie Eilish', null),
      'hotel california': (HitKind.song, 'Eagles', 'Hotel California'),
      'bohemian rhapsody': (HitKind.song, 'Queen', 'Bohemian Rhapsody'),
      'ed sheeran shape of you': (HitKind.song, 'Ed Sheeran', 'Shape of You'),
    };

    /// Which kind and whose it is: what the Top result would be for [query].
    Future<(HitKind, String, String?)?> top(String query) async {
      final r = await client.search(query);
      final songs = rankHits([
        for (final t in r.tracks)
          Ranked(t, songMatch(query, artist: t.artistName, title: t.title),
              owned: false),
      ]);
      final artists = rankHits([
        for (final a in r.artists)
          Ranked(a, artistMatch(query, a.name), owned: false)
      ]);
      final albums = rankHits([
        for (final a in r.albums)
          Ranked(a, albumMatch(query, title: a.title, artist: a.artistName),
              owned: false),
      ]);
      final bestArtist = artists.isEmpty ? null : artists.first;
      final pick = pickTop(
        song: songs.isEmpty ? null : songs.first.score,
        artist: bestArtist?.score,
        album: albums.isEmpty ? null : albums.first.score,
        artistWellKnown: (bestArtist?.value.fans ?? 0) >= 50000,
      );
      if (pick == null) return null;
      return switch (pick.kind) {
        HitKind.song => (
            HitKind.song,
            songs.first.value.artistName,
            songs.first.value.title
          ),
        HitKind.artist => (HitKind.artist, bestArtist!.value.name, null),
        HitKind.album => (
            HitKind.album,
            albums.first.value.artistName,
            albums.first.value.title
          ),
      };
    }

    final misses = <String>[];
    for (final entry in intended.entries) {
      test('"${entry.key}"', () async {
        final got = await top(entry.key);
        final (kind, artist, title) = entry.value;
        final ok = got != null &&
            got.$1 == kind &&
            got.$2.toLowerCase() == artist.toLowerCase() &&
            (title == null ||
                got.$3!.toLowerCase().contains(title.toLowerCase()));
        if (!ok) misses.add('${entry.key} -> $got');
        // Two answers Deezer does not hold (the real song is not among its eight results; an Arabic title cannot be matched by Latin
        // letters yet, docs/19) are known and listed; every other one must be right.
        const known = {'beach house space song', 'oum kalthoum enta omri'};
        if (!known.contains(entry.key)) {
          expect(ok, isTrue, reason: 'wanted $entry, got $got');
        }
      });
    }

    test(
        'at least 18 of the 20 are right, and the two known misses are the ones named',
        () {
      // Runs after the 20 above (declaration order): `misses` holds what failed.
      expect(misses.length, lessThanOrEqualTo(2), reason: misses.join('\n'));
    });
  });
}
