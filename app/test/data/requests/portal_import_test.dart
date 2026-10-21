import 'package:dio/dio.dart';
import 'package:encore/data/requests/portal_client.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_http.dart';

/// The import half of the portal API (ADR-050). Shapes come from the
/// portal's own web page (read 2026-10-15):
///   POST /api/imports {url, name} -> {kind: artist|playlist, name} | {error}
///   GET  /api/me -> imports[{name, status{state, tracks, in_library,
///                                           albums, albums_requested}}]
///   DELETE /api/imports?name=   DELETE /api/artist?id=
///   POST /api/artist/pick {id, mbid}
void main() {
  late FakeHttpAdapter adapter;
  late HomelabPortalClient client;

  Dio dio() => Dio(BaseOptions(validateStatus: (_) => true))
    ..httpClientAdapter = adapter;

  setUp(() {
    adapter = FakeHttpAdapter(routes: {
      '/api/login': (r) => const FakeResponse.json({'ok': true}),
      '/api/imports': (r) => r.apiMethod == 'imports' && r.method == 'POST'
          ? const FakeResponse.json({'kind': 'playlist', 'name': 'Road trip'})
          : const FakeResponse.json({'ok': true}),
      '/api/artist': (r) => const FakeResponse.json({'ok': true}),
      '/api/artist/pick': (r) => const FakeResponse.json({'ok': true}),
    });
    client = HomelabPortalClient(
      baseUrl: Uri.parse('http://portal:8700'),
      username: 'marwa',
      password: 'secret',
      dio: dio(),
    );
  });

  test('importLink posts the address and the optional name', () async {
    final r = await client.importLink(
      url: 'https://open.spotify.com/playlist/abc',
      name: 'Road trip',
    );

    expect(r.isOk, isTrue);
    expect(r.valueOrNull!.kind, 'playlist');
    expect(r.valueOrNull!.name, 'Road trip');
    final post =
        adapter.requests.firstWhere((x) => x.uri.path == '/api/imports');
    expect(post.method, 'POST');
    expect(
        post.body, contains('"url":"https://open.spotify.com/playlist/abc"'));
    expect(post.body, contains('"name":"Road trip"'));
  });

  test('an artist link is answered with kind artist', () async {
    adapter.routes['/api/imports'] =
        (_) => const FakeResponse.json({'kind': 'artist', 'name': 'Alcest'});

    final r =
        await client.importLink(url: 'https://open.spotify.com/artist/xyz');

    expect(r.valueOrNull!.kind, 'artist');
    expect(r.valueOrNull!.name, 'Alcest');
    final post =
        adapter.requests.firstWhere((x) => x.uri.path == '/api/imports');
    expect(post.body, contains('"name":""'),
        reason: 'no name = portal default');
  });

  test('the portal\'s own error text reaches the person', () async {
    adapter.routes['/api/imports'] = (_) => const FakeResponse.json(
          {'error': 'That playlist is private or does not exist'},
          status: 400,
        );

    final r =
        await client.importLink(url: 'https://open.spotify.com/playlist/x');

    expect(r.isOk, isFalse);
    expect(
        r.failureOrNull!.message, 'That playlist is private or does not exist');
  });

  test('no connection is a clear failure, not a crash', () async {
    adapter.routes['/api/imports'] =
        (_) => const FakeResponse.connectionError();

    final r = await client.importLink(url: 'https://open.spotify.com/artist/x');

    expect(r.isOk, isFalse);
  });

  test('removeImport deletes by name, URL-encoded', () async {
    final r = await client.removeImport('Road trip & more');

    expect(r.isOk, isTrue);
    final del = adapter.requests.lastWhere((x) => x.uri.path == '/api/imports');
    expect(del.method, 'DELETE');
    expect(del.uri.queryParameters['name'], 'Road trip & more');
  });

  test('removeArtist and pickArtist use the artist endpoints', () async {
    expect((await client.removeArtist('a1')).isOk, isTrue);
    expect((await client.pickArtist(id: 'a1', mbid: 'mb-9')).isOk, isTrue);

    final del = adapter.requests.firstWhere((x) => x.uri.path == '/api/artist');
    expect(del.method, 'DELETE');
    expect(del.uri.queryParameters['id'], 'a1');
    final pick =
        adapter.requests.firstWhere((x) => x.uri.path == '/api/artist/pick');
    expect(pick.body, contains('"id":"a1"'));
    expect(pick.body, contains('"mbid":"mb-9"'));
  });

  group('overview', () {
    test('parses imports with their progress', () {
      final o = HomelabPortalClient.parseOverview({
        'user': 'marwa',
        'imports': [
          {
            'name': 'Road trip',
            'status': {
              'state': 'reading',
              'tracks': 52,
              'in_library': 37,
              'albums': 9,
              'albums_requested': 6,
            },
          },
          {
            'name': 'Just added',
            'status': {'state': 'queued'},
          },
        ],
        'artists': [
          {
            'id': 'a9',
            'name': 'Pause',
            'state': 'pick',
            'candidates': [
              {'mbid': 'm1', 'label': 'Pause (FR, rock)'},
              {'mbid': 'm2', 'label': 'Pause (DE, techno)'},
            ],
          },
        ],
        'requests': <Object>[],
      });

      final trip = o.imports.first;
      expect(trip.name, 'Road trip');
      expect(trip.state, 'reading');
      expect(trip.tracks, 52);
      expect(trip.inLibrary, 37);
      expect(trip.albumsRequested, 6);
      expect(trip.hasProgress, isTrue);
      expect(trip.isComplete, isFalse);
      expect(trip.fraction, closeTo(37 / 52, 1e-9));

      final fresh = o.imports.last;
      expect(fresh.hasProgress, isFalse);
      expect(fresh.fraction, isNull);

      expect(o.artists.single.candidates.map((c) => c.mbid), ['m1', 'm2']);
    });

    test('an import with every song present is complete', () {
      const done =
          PortalImport(name: 'x', state: 'done', tracks: 10, inLibrary: 10);
      const empty = PortalImport(name: 'y', state: 'done', tracks: 0);

      expect(done.isComplete, isTrue);
      expect(done.fraction, 1.0);
      expect(empty.isComplete, isFalse, reason: 'nothing to be complete');
    });

    test('an old portal without imports still parses', () {
      final o = HomelabPortalClient.parseOverview(
          {'user': 'marwa', 'artists': <Object>[], 'requests': <Object>[]});

      expect(o.imports, isEmpty);
    });
  });
}
