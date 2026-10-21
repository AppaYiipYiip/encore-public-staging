import 'package:encore/domain/import_link.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('Spotify', () {
    test('a playlist link loses its tracking parameters', () {
      final link = ImportLink.parse(
          'https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=ab12cd')!;

      expect(link.kind, ImportKind.spotifyPlaylist);
      expect(
          link.url, 'https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M');
      expect(link.id, '37i9dQZF1DXcBWIGoYBM5M');
      expect(link.isPlaylist, isTrue);
      expect(link.isSupported, isTrue);
      expect(link.problem, isNull);
      expect(link.sourceName, 'Spotify');
    });

    test('an artist link is supported and not a playlist', () {
      final link = ImportLink.parse(
          'https://open.spotify.com/artist/0OdUWJ0sBjDrqHygGUXeCF')!;

      expect(link.kind, ImportKind.spotifyArtist);
      expect(link.isArtist, isTrue);
      expect(link.isPlaylist, isFalse);
      expect(link.isSupported, isTrue);
    });

    test('a localized path (intl-xx) is understood', () {
      final link = ImportLink.parse(
          'https://open.spotify.com/intl-fr/playlist/37i9dQZF1DXcBWIGoYBM5M')!;

      expect(link.kind, ImportKind.spotifyPlaylist);
      expect(
          link.url, 'https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M');
    });

    test('the address inside a shared sentence is found', () {
      final link = ImportLink.parse('Check out "Road trip" on Spotify: '
          'https://open.spotify.com/playlist/AbC123?si=zzz\nSent from Spotify')!;

      expect(link.kind, ImportKind.spotifyPlaylist);
      expect(link.id, 'AbC123');
    });

    test('a spotify: URI is accepted', () {
      final link = ImportLink.parse('spotify:artist:0OdUWJ0sBjDrqHygGUXeCF')!;

      expect(link.kind, ImportKind.spotifyArtist);
      expect(
          link.url, 'https://open.spotify.com/artist/0OdUWJ0sBjDrqHygGUXeCF');
    });

    test('trailing punctuation is not part of the address', () {
      final link =
          ImportLink.parse('(see https://open.spotify.com/artist/abc123).')!;

      expect(link.id, 'abc123');
    });

    test('an album or a song is recognised and explained, not sent', () {
      final album = ImportLink.parse('https://open.spotify.com/album/1A2b3C')!;
      final track =
          ImportLink.parse('https://open.spotify.com/track/9Z8y7X?si=q')!;

      expect(album.kind, ImportKind.spotifyAlbum);
      expect(album.isSupported, isFalse);
      expect(album.problem, contains('Request'));
      expect(track.kind, ImportKind.spotifyTrack);
      expect(track.isSupported, isFalse);
      expect(track.problem, contains('one song'));
    });
  });

  group('YouTube', () {
    test('a YouTube Music playlist keeps only the list id', () {
      final link = ImportLink.parse(
          'https://music.youtube.com/playlist?list=PLabc-123_x&si=tracking')!;

      expect(link.kind, ImportKind.youtubeMusicPlaylist);
      expect(link.url, 'https://music.youtube.com/playlist?list=PLabc-123_x');
      expect(link.isSupported, isTrue);
      expect(link.sourceName, 'YouTube Music');
    });

    test('a plain YouTube playlist is a playlist too', () {
      final link =
          ImportLink.parse('https://www.youtube.com/playlist?list=PLxyz')!;

      expect(link.kind, ImportKind.youtubePlaylist);
      expect(link.isPlaylist, isTrue);
    });

    test('a YouTube Music artist (channel) link is an artist', () {
      final link =
          ImportLink.parse('https://music.youtube.com/channel/UCabcDEF123')!;

      expect(link.kind, ImportKind.youtubeMusicArtist);
      expect(link.isArtist, isTrue);
    });

    test('a single video is explained, not sent', () {
      final link = ImportLink.parse('https://youtu.be/dQw4w9WgXcQ')!;

      expect(link.kind, ImportKind.youtubeVideo);
      expect(link.isSupported, isFalse);
      expect(link.problem, isNotNull);
    });
  });

  group('several links at once', () {
    test('one link per line (Spotify desktop copy) gives them all', () {
      final links =
          ImportLink.parseAll('https://open.spotify.com/playlist/aaa\n'
              'https://open.spotify.com/playlist/bbb?si=x\n'
              'https://open.spotify.com/artist/ccc');

      expect(links.map((l) => l.id), ['aaa', 'bbb', 'ccc']);
      expect(links.where((l) => l.isPlaylist), hasLength(2));
      expect(links.where((l) => l.isArtist), hasLength(1));
    });

    test('the same playlist twice (URI and URL) counts once', () {
      final links = ImportLink.parseAll(
          'spotify:playlist:aaa https://open.spotify.com/playlist/aaa?si=1');

      expect(links, hasLength(1));
    });

    test('importable links come first, unsupported ones last', () {
      final links = ImportLink.parseAll('https://open.spotify.com/track/t1 '
          'https://open.spotify.com/playlist/p1 '
          'https://example.com/x');

      expect(links.first.kind, ImportKind.spotifyPlaylist);
      expect(links.skip(1).every((l) => !l.isSupported), isTrue);
      expect(links, hasLength(3));
    });

    test('no links is an empty list', () {
      expect(ImportLink.parseAll('nothing here'), isEmpty);
      expect(ImportLink.parseAll(''), isEmpty);
    });
  });

  group('everything else', () {
    test('no link at all gives null', () {
      expect(ImportLink.parse(''), isNull);
      expect(ImportLink.parse('   '), isNull);
      expect(ImportLink.parse('my road trip playlist'), isNull);
    });

    test('another website is explained', () {
      final link = ImportLink.parse('https://example.com/music/42')!;

      expect(link.kind, ImportKind.unknown);
      expect(link.isSupported, isFalse);
      expect(link.problem, contains('Spotify or YouTube Music'));
    });

    test('a supported link wins over an unsupported one in the same text', () {
      final link = ImportLink.parse('https://open.spotify.com/track/aaa and '
          'https://open.spotify.com/playlist/bbb')!;

      expect(link.kind, ImportKind.spotifyPlaylist);
    });

    test('a Spotify page that is neither is unknown', () {
      final link = ImportLink.parse('https://open.spotify.com/user/someone')!;

      expect(link.kind, ImportKind.unknown);
    });
    test('a song opened from inside a playlist is that playlist', () {
      final link = ImportLink.parse(
          'https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLCzMQBwOQk4fjHJoB7FckjJtr-2cTUSyV')!;

      expect(link.kind, ImportKind.youtubePlaylist);
      expect(link.url,
          'https://www.youtube.com/playlist?list=PLCzMQBwOQk4fjHJoB7FckjJtr-2cTUSyV');
      expect(link.isReadable, isTrue);
    });

    test(
        'a playlist link from YouTube Music keeps its list and drops the '
        'tracking', () {
      final link = ImportLink.parse(
          'https://music.youtube.com/playlist?list=PLMXloh6Hpt1I&si=swWsEp93Soh6mkne&drli=1')!;

      expect(link.kind, ImportKind.youtubeMusicPlaylist);
      expect(link.url, 'https://music.youtube.com/playlist?list=PLMXloh6Hpt1I');
    });

    test(
        'playlists and Spotify albums can be read into a list, artists and '
        'single songs cannot', () {
      bool readable(String url) => ImportLink.parse(url)!.isReadable;

      expect(
          readable('https://open.spotify.com/playlist/3dEfExamplePlaylistC03'),
          isTrue);
      expect(readable('https://open.spotify.com/album/4kZMWfXCP5uJi6tGRJ3IA0'),
          isTrue);
      expect(readable('https://open.spotify.com/artist/0OdUWJ0sBjDrqHygGUXeCF'),
          isFalse);
      expect(readable('https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC'),
          isFalse);
      expect(readable('https://youtu.be/dQw4w9WgXcQ'), isFalse);
    });
  });
}
