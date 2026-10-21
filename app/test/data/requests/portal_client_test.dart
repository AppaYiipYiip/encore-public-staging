import 'package:dio/dio.dart';
import 'package:encore/core/result.dart';
import 'package:encore/data/requests/portal_client.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_http.dart';

void main() {
  late FakeHttpAdapter adapter;
  late HomelabPortalClient client;
  var logins = 0;

  Dio dio() => Dio(BaseOptions(validateStatus: (_) => true))
    ..httpClientAdapter = adapter;

  setUp(() {
    logins = 0;
    adapter = FakeHttpAdapter(routes: {
      '/api/login': (r) {
        logins++;
        return const FakeResponse.json({'ok': true});
      },
      '/api/request': (r) =>
          const FakeResponse.json({'kind': 'album', 'name': 'Kodama'}),
      '/api/me': (r) => const FakeResponse.json({
            'user': 'marwa',
            'artists': [
              {
                'id': 'a1',
                'name': 'Alcest',
                'state': 'added',
                'albums': 6,
                'tracks_have': 12,
                'tracks_all': 40,
              },
            ],
            'requests': [
              {'artist': 'Alcest', 'album': 'Kodama', 'state': 'requested'},
            ],
          }),
    });
    client = HomelabPortalClient(
      baseUrl: Uri.parse('http://portal:8700'),
      username: 'marwa',
      password: 'secret',
      dio: dio(),
    );
  });

  test('request logs in once, then posts artist and album', () async {
    final r = await client.request(artist: 'Alcest', album: 'Kodama');
    expect(r.isOk, isTrue);
    expect(r.valueOrNull!.kind, 'album');
    expect(logins, 1);

    final post =
        adapter.requests.firstWhere((x) => x.uri.path == '/api/request');
    expect(post.body, contains('"artist":"Alcest"'));
    expect(post.body, contains('"album":"Kodama"'));

    await client.request(artist: 'Alcest', album: 'Other');
    expect(logins, 1, reason: 'session is reused');
  });

  group('the password only travels over a safe address (docs/23, B25)', () {
    HomelabPortalClient at(String base) => HomelabPortalClient(
          baseUrl: Uri.parse(base),
          username: 'marwa',
          password: 'secret',
          dio: dio(),
        );

    test('a public address without https gets nothing, not even a login',
        () async {
      final r =
          await at('http://portal.example.org:8700').request(artist: 'Alcest');

      expect(r.isOk, isFalse);
      expect(r.failureOrNull!.message, contains('https://'));
      expect(adapter.requests, isEmpty,
          reason: 'the password must not leave the phone in plain text');
      expect(logins, 0);
    });

    test('a public address with https works', () async {
      final r =
          await at('https://portal.example.org').request(artist: 'Alcest');

      expect(r.isOk, isTrue);
      expect(logins, 1);
    });

    test('a private address without https still works (home, Tailscale)',
        () async {
      for (final base in const [
        'http://192.168.50.113:8700',
        'http://100.90.68.57:8700',
        'http://nas.local:8700',
      ]) {
        adapter.requests.clear();
        final r = await at(base).request(artist: 'Alcest');
        expect(r.isOk, isTrue, reason: base);
      }
    });
  });

  test('an artist request sends an empty album', () async {
    await client.request(artist: 'Alcest');
    final post =
        adapter.requests.firstWhere((x) => x.uri.path == '/api/request');
    expect(post.body, contains('"album":""'));
  });

  test('overview parses artists and requests tolerantly', () async {
    final r = await client.overview();
    final o = r.valueOrNull!;
    expect(o.user, 'marwa');
    expect(o.artists.single.name, 'Alcest');
    expect(o.artists.single.tracksHave, 12);
    expect(o.artists.single.isDone, isFalse);
    expect(o.requests.single.album, 'Kodama');
  });

  test('parses a payload recorded from the real portal (2026-10-15)', () {
    final overview = HomelabPortalClient.parseOverview({
      'user': 'someone',
      'imports': <Object>[],
      'requests': [
        {'artist': 'raid', 'album': 'ether', 'state': 'requested'},
      ],
      'artists': [
        {
          'id': '31c681666e14',
          'name': 'Pause',
          'state': 'added',
          'detail': 'added: Lidarr is reading the whole catalogue',
          'albums': 3,
          'tracks_have': 0,
          'tracks_all': 18,
          'candidates': null,
        },
      ],
    });
    expect(overview.user, 'someone');
    expect(overview.requests.single.album, 'ether');
    expect(overview.requests.single.state, 'requested');
    final artist = overview.artists.single;
    expect(artist.id, '31c681666e14');
    expect(artist.state, 'added');
    expect(artist.tracksAll, 18);
    expect(artist.isDone, isFalse);
  });

  test('bad credentials surface as an auth failure', () async {
    adapter.routes['/api/login'] =
        (_) => const FakeResponse.json({'error': 'no'}, status: 401);
    final r = await client.check();
    expect(r.failureOrNull, isA<AuthFailure>());
  });

  test('server errors are reported, not thrown', () async {
    adapter.routes['/api/request'] =
        (_) => const FakeResponse.json({'error': 'boom'}, status: 500);
    final r = await client.request(artist: 'Alcest', album: 'Kodama');
    expect(r.failureOrNull, isA<ServerFailure>());
  });

  test('an unreachable portal is a network failure', () async {
    adapter.routes['/api/login'] = (_) => const FakeResponse.connectionError();
    final r = await client.request(artist: 'Alcest');
    expect(r.failureOrNull, isA<NetworkFailure>());
  });

  test('a stale session is renewed once', () async {
    var first = true;
    adapter.routes['/api/request'] = (_) {
      if (first) {
        first = false;
        return const FakeResponse.json({'error': 'login'}, status: 401);
      }
      return const FakeResponse.json({'kind': 'artist', 'name': 'Alcest'});
    };
    final r = await client.request(artist: 'Alcest');
    expect(r.isOk, isTrue);
    expect(logins, 2);
  });
}
