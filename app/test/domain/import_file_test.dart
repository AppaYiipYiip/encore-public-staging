import 'package:encore/domain/import_file.dart';
import 'package:flutter_test/flutter_test.dart';

/// The files a person can get out of Spotify and Google, as they really look
/// (the layouts were checked against the services' own documentation and
/// exports; names and songs here are made up).
void main() {
  group('Spotify "Download your data"', () {
    const library = '''
{
  "tracks": [
    {"artist": "Opeth", "album": "Damnation", "track": "Windowpane", "uri": "spotify:track:1"},
    {"artist": "Opeth", "album": "Damnation", "track": "In My Time of Need", "uri": "spotify:track:2"},
    {"artist": "", "album": "x", "track": "Nobody", "uri": "spotify:track:3"}
  ],
  "albums": [{"artist": "Opeth", "album": "Blackwater Park", "uri": "spotify:album:9"}]
}''';

    const playlists = '''
{
  "playlists": [
    {"name": "Evening drive", "lastModifiedDate": "2026-01-02", "items": [
      {"track": {"trackName": "Burden", "artistName": "Opeth", "albumName": "Watershed"}, "episode": null, "localTrack": null, "addedDate": "2026-01-01"},
      {"track": null, "episode": {"name": "A podcast"}, "localTrack": null},
      {"track": {"trackName": "Harvest", "artistName": "Opeth", "albumName": "Still Life"}, "episode": null}
    ]},
    {"name": "Empty one", "items": []}
  ]
}''';

    test('the liked songs come as one list that is liked, not a playlist', () {
      final result = parseImportFile(library);

      expect(result.problem, isNull);
      final liked = result.entries.single;
      expect((liked.name, liked.liked, liked.tracks.length),
          ('Liked songs', true, 2));
      expect(liked.tracks.first.album, 'Damnation');
      expect(result.skipped, 1,
          reason: 'a row without an artist is counted, not hidden');
    });

    test(
        'every playlist is a list of its own; episodes and empty ones '
        'are left out', () {
      final result = parseImportFile(playlists);

      expect(result.entries.map((e) => e.name), ['Evening drive']);
      expect(result.entries.single.tracks.map((t) => t.title),
          ['Burden', 'Harvest']);
      expect(result.entries.single.liked, isFalse);
    });

    test('a file with both has the liked songs first', () {
      final result = parseImportFile('{"tracks":[{"artist":"A","track":"B"}],'
          '"playlists":[{"name":"P","items":[{"track":{"trackName":"C","artistName":"D"}}]}]}');
      expect(result.entries.map((e) => e.name), ['Liked songs', 'P']);
      expect(result.songs, 2);
    });
  });

  group('Exportify CSV', () {
    const csv = 'Track URI,Track Name,Album Name,Artist Name(s),Release Date,'
        'Duration (ms),Popularity\r\n'
        'spotify:track:1,Windowpane,Damnation,Opeth,2003-04-22,467000,60\r\n'
        'spotify:track:2,"Hello, World",Album,"Artist A;Artist B",2020,215500,1\r\n'
        'spotify:track:3,"She said ""yes""",Album,Someone,2020,180000,1\r\n';

    test(
        'titles, artists and lengths are read, the first artist is the '
        'artist', () {
      final result = parseImportFile(csv, fileName: 'Death_Metal_Best_Of.csv');

      final list = result.entries.single;
      expect(list.name, 'Death Metal Best Of');
      expect(list.liked, isFalse);
      expect(list.tracks.map((t) => (t.title, t.artist)), [
        ('Windowpane', 'Opeth'),
        ('Hello, World', 'Artist A'),
        ('She said "yes"', 'Someone'),
      ]);
      expect(list.tracks.first.durationSec, 467);
      expect(list.tracks.first.album, 'Damnation');
    });

    test('a file called liked songs is the liked songs', () {
      final result = parseImportFile(csv, fileName: 'liked_songs.csv');
      expect(result.entries.single.liked, isTrue);
    });

    test(
        'a byte-order mark, a semicolon separator and a line break inside '
        'a quoted title do not confuse it', () {
      const odd = '﻿Track Name;Artist Name(s);Duration (ms)\n'
          '"Two\nlines";Band;1000\n';
      final result = parseImportFile(odd);
      expect(result.entries.single.tracks.single.title, 'Two lines');
      expect(result.entries.single.tracks.single.artist, 'Band');
    });
  });

  group('Google Takeout, YouTube Music', () {
    test('the songs file has titles and artists', () {
      const csv = 'Song Title,Album Title,Artist Name 1,Artist Name 2\n'
          'Burden,Watershed,Opeth,\n'
          'Leyla,,Jah Khalib,\n';
      final result = parseImportFile(csv, fileName: 'music library songs.csv');

      expect(result.entries.single.tracks.map((t) => t.title),
          ['Burden', 'Leyla']);
      expect(result.entries.single.tracks.last.album, isNull);
    });

    test('a list of video numbers only says why it cannot be used', () {
      const csv = 'Video ID,Playlist Video Creation Timestamp\n'
          'dQw4w9WgXcQ,2026-01-01T00:00:00+00:00\n';
      final result = parseImportFile(csv, fileName: 'Liked videos-videos.csv');

      expect(result.entries, isEmpty);
      expect(result.problem, contains('only YouTube video numbers'));
    });
  });

  group('whatever else is handed over', () {
    test('a file that is not a list of songs is explained, never a crash', () {
      for (final text in [
        '',
        '   ',
        'hello',
        '{not json',
        '{"a":1}',
        '[1,2]',
        'a,b\n1,2\n'
      ]) {
        final result = parseImportFile(text);
        expect(result.entries, isEmpty, reason: text);
        expect(result.problem, contains('does not look like a list of songs'),
            reason: text);
      }
    });

    test('a bare JSON list of songs works', () {
      final result = parseImportFile(
          '[{"track":"Burden","artist":"Opeth"},{"title":"Harvest","artistName":"Opeth"}]');
      expect(result.songs, 2);
    });

    test('rows with no title or artist are counted and the rest are kept', () {
      final result =
          parseImportFile('Track Name,Artist Name(s)\nA,B\n,C\nD,\n\nE,F\n');
      expect(result.songs, 2);
      expect(result.skipped, 2);
    });

    test('the CSV reader copes with quotes, blank lines and no final newline',
        () {
      expect(parseCsv('a,"b,c",d\n\ne,f,g'), [
        ['a', 'b,c', 'd'],
        [''],
        ['e', 'f', 'g'],
      ]);
      expect(parseCsv('x,"y""z"'), [
        ['x', 'y"z']
      ]);
    });
  });
}
