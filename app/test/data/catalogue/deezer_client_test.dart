import 'package:dio/dio.dart';
import 'package:encore/data/catalogue/deezer_client.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_http.dart';

Dio dio(FakeHttpAdapter adapter) =>
    Dio(BaseOptions(baseUrl: 'https://api.deezer.com'))
      ..httpClientAdapter = adapter;

void main() {
  late FakeHttpAdapter adapter;
  late DeezerClient client;

  const artistJson = {
    'data': [
      {
        'id': 27,
        'name': 'Daft Punk',
        'picture_xl': 'https://img/xl.jpg',
        'nb_fan': 4500000,
        'nb_album': 36,
      },
      {'id': null, 'name': 'Broken'},
    ],
  };
  const albumJson = {
    'data': [
      {
        'id': 302127,
        'title': 'Discovery',
        'cover_xl': 'https://img/disc.jpg',
        'nb_tracks': 14,
        'record_type': 'album',
        'release_date': '2001-03-12',
        'artist': {'id': 27, 'name': 'Daft Punk'},
      },
    ],
  };
  const trackJson = {
    'data': [
      {
        'id': 3135556,
        'title': 'Harder, Better, Faster, Stronger',
        'duration': 224,
        'preview': 'https://cdns-preview/abc.mp3',
        'artist': {'id': 27, 'name': 'Daft Punk'},
        'album': {
          'id': 302127,
          'title': 'Discovery',
          'cover_xl': 'https://img/disc.jpg',
        },
      },
    ],
  };

  setUp(() {
    adapter = FakeHttpAdapter(routes: {
      '/search/artist': (_) => const FakeResponse.json(artistJson),
      '/search/album': (_) => const FakeResponse.json(albumJson),
      '/search/track': (_) => const FakeResponse.json(trackJson),
    });
    client = DeezerClient(dio: dio(adapter));
  });

  test('search combines artists, albums and tracks', () async {
    final r = await client.search('daft punk');
    expect(r.artists.single.name, 'Daft Punk');
    expect(r.artists.single.imageUrl, 'https://img/xl.jpg');
    expect(r.albums.single.title, 'Discovery');
    expect(r.albums.single.year, 2001);
    expect(r.albums.single.artistName, 'Daft Punk');
    expect(r.tracks.single.duration, const Duration(seconds: 224));
    expect(r.tracks.single.coverUrl, 'https://img/disc.jpg');
  });

  test('entries without an id are dropped, not crashed on', () async {
    final r = await client.search('daft');
    expect(r.artists.length, 1);
  });

  test('queries shorter than two characters do no request', () async {
    final r = await client.search(' a ');
    expect(r.isEmpty, isTrue);
    expect(adapter.requests, isEmpty);
  });

  test('a Deezer error (HTTP 200 with error body) yields nothing', () async {
    adapter.routes['/search/artist'] = (_) => const FakeResponse.json({
          'error': {'type': 'Exception', 'message': 'Quota', 'code': 4},
        });
    final r = await client.search('daft punk');
    expect(r.artists, isEmpty);
    expect(r.albums, isNotEmpty, reason: 'other endpoints still answer');
  });

  test('an unreachable catalogue is "no extra results", never an error',
      () async {
    adapter.routes['/search/artist'] =
        (_) => const FakeResponse.connectionError();
    adapter.routes['/search/album'] =
        (_) => const FakeResponse.connectionError();
    adapter.routes['/search/track'] =
        (_) => const FakeResponse.connectionError();
    final r = await client.search('daft punk');
    expect(r.isEmpty, isTrue);
  });

  test('album tracks inherit the cover and title from the album', () async {
    adapter.routes['/album/302127/tracks'] = (_) => const FakeResponse.json({
          'data': [
            {
              'id': 1,
              'title': 'One More Time',
              'duration': 320,
              'preview': 'https://cdns-preview/1.mp3',
              'artist': {'id': 27, 'name': 'Daft Punk'},
            },
          ],
        });
    adapter.routes['/album/302127'] = (_) => const FakeResponse.json({
          'id': 302127,
          'title': 'Discovery',
          'cover_xl': 'https://img/disc.jpg',
        });
    final tracks = await client.albumTracks('302127');
    expect(tracks.single.albumTitle, 'Discovery');
    expect(tracks.single.coverUrl, 'https://img/disc.jpg');
    expect(tracks.single.albumId, '302127');
  });

  test('all of an artist\'s releases are asked for, not the first fifty',
      () async {
    // Pink Floyd has 64 releases and Ramones 61: asking for 50 silently
    // dropped the last of the singles and EPs from "Singles and EPs".
    adapter.routes['/artist/860/albums'] = (_) => const FakeResponse.json({
          'data': [
            {
              'id': 1,
              'title': 'Animals',
              'record_type': 'album',
              'release_date': '1977-01-23',
              'artist': {'id': 860, 'name': 'Pink Floyd'},
            },
          ],
        });

    final albums = await client.artistAlbums('860');

    expect(albums.single.title, 'Animals');
    final request =
        adapter.requests.firstWhere((r) => r.uri.path == '/artist/860/albums');
    expect(int.parse(request.uri.queryParameters['limit']!), greaterThan(64));
  });

  test('the chart of a genre is its top songs, artists and albums', () async {
    adapter.routes['/chart/152/tracks'] = (_) => const FakeResponse.json({
          'data': [
            {
              'id': 1,
              'title': 'Sparks',
              'duration': 240,
              'preview': 'https://cdns-preview/1.mp3',
              'artist': {'id': 7, 'name': 'Coldplay'},
              'album': {
                'id': 9,
                'title': 'Parachutes',
                'cover_xl': 'https://img/c.jpg'
              },
            },
          ],
        });
    adapter.routes['/chart/152/artists'] = (_) => const FakeResponse.json({
          'data': [
            {
              'id': 7,
              'name': 'Coldplay',
              'picture_medium': 'https://img/a.jpg'
            },
          ],
        });
    adapter.routes['/chart/152/albums'] = (_) => const FakeResponse.json({
          'data': [
            {
              'id': 9,
              'title': 'Parachutes',
              'artist': {'id': 7, 'name': 'Coldplay'},
              'record_type': 'album',
            },
          ],
        });

    final chart = await client.genreChart(152);

    expect(chart.tracks.single.title, 'Sparks');
    expect(chart.tracks.single.artistId, '7');
    expect(chart.artists.single.name, 'Coldplay');
    expect(chart.albums.single.title, 'Parachutes');
  });

  test('a genre that cannot be reached is an empty chart, not an error',
      () async {
    adapter.routes['/chart/152/tracks'] =
        (_) => const FakeResponse.connectionError();
    adapter.routes['/chart/152/artists'] =
        (_) => const FakeResponse.connectionError();
    adapter.routes['/chart/152/albums'] =
        (_) => const FakeResponse.connectionError();

    final chart = await client.genreChart(152);

    expect(chart.isEmpty, isTrue);
  });

  test('requests carry the query and limits', () async {
    await client.search('Periphery', limit: 6);
    final tracksReq =
        adapter.requests.firstWhere((r) => r.uri.path == '/search/track');
    expect(tracksReq.uri.queryParameters['q'], 'Periphery');
    expect(tracksReq.uri.queryParameters['limit'], '6');
  });
}
