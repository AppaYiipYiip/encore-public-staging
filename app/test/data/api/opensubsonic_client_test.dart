import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:encore/core/result.dart';
import 'package:encore/data/api/opensubsonic/opensubsonic_client.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_http.dart';

OpenSubsonicClient _client(
  FakeHttpAdapter adapter, {
  String base = 'http://10.0.0.2:4533',
}) =>
    OpenSubsonicClient(
      dio: fakeDio(adapter),
      baseUrl: () => Uri.parse(base),
      credentials: const SubsonicCredentials(
        username: 'tester',
        password: 'p@ss word!',
      ),
    );

const _song = {
  'id': 's1',
  'parent': 'al1',
  'title': 'Autre temps',
  'album': 'Les Voyages de l’âme',
  'artist': 'Alcest',
  'track': 1,
  'year': 2012,
  'duration': 350,
  'size': 37069852,
  'suffix': 'flac',
  'bitRate': 842,
  'albumId': 'al1',
  'artistId': 'ar1',
  'created': '2026-10-09T21:27:43.340141227Z',
  'starred': '2026-10-10T10:00:00Z',
  'isrc': ['DES561212201'],
  'replayGain': {'trackGain': -7.5},
};

void main() {
  group('authentication', () {
    test('uses token auth: t = md5(password + salt), never the password',
        () async {
      final adapter = FakeHttpAdapter(routes: {
        'ping': (_) => FakeResponse.json(subsonicOk({})),
      });
      await _client(adapter).ping();

      final r = adapter.requests.single;
      final salt = r.param('s')!;
      final expected = md5.convert(utf8.encode('p@ss word!$salt')).toString();
      expect(r.param('t'), expected);
      expect(r.param('u'), 'tester');
      expect(r.param('f'), 'json');
      expect(r.uri.toString(), isNot(contains('p%40ss')));
      expect(r.params.containsKey('p'), isFalse);
    });

    test('salt is stable within a client (stable media URLs)', () {
      final client = _client(FakeHttpAdapter());
      final a = client.streamUrl('s1');
      final b = client.streamUrl('s1');
      expect(a, b);
    });

    test('stream URL carries bitrate/format only when meaningful', () {
      final client = _client(FakeHttpAdapter());
      final url = client.streamUrl('s1', maxBitRate: 160, format: 'opus');
      expect(url.queryParameters['maxBitRate'], '160');
      expect(url.queryParameters['format'], 'opus');
      final raw = client.streamUrl('s1', format: 'raw');
      expect(raw.queryParameters.containsKey('format'), isFalse);
    });

    test('base path prefixes are preserved (reverse proxy sub-path)', () {
      final client = _client(FakeHttpAdapter(), base: 'https://x.org/music/');
      expect(client.downloadUrl('s1').path, '/music/rest/download');
    });
  });

  group('error mapping', () {
    test('Subsonic error 40 -> AuthFailure (not retryable)', () async {
      final adapter = FakeHttpAdapter(routes: {
        'ping': (_) => FakeResponse.json(subsonicError(40, 'Wrong password')),
      });
      final result = await _client(adapter).ping();

      expect(result.failureOrNull, isA<AuthFailure>());
      expect(result.failureOrNull!.isRetryable, isFalse);
    });

    test('Subsonic error 70 -> NotFoundFailure', () async {
      final adapter = FakeHttpAdapter(routes: {
        'getAlbum': (_) => FakeResponse.json(subsonicError(70, 'gone')),
      });
      final result = await _client(adapter).getAlbum('nope');
      expect(result.failureOrNull, isA<NotFoundFailure>());
    });

    test('socket failure -> retryable NetworkFailure', () async {
      final adapter = FakeHttpAdapter(routes: {
        'ping': (_) => const FakeResponse.connectionError(),
      });
      final result = await _client(adapter).ping();

      expect(result.failureOrNull, isA<NetworkFailure>());
      expect(result.failureOrNull!.isRetryable, isTrue);
    });

    test('HTTP 502 -> retryable ServerFailure with status', () async {
      final adapter = FakeHttpAdapter(routes: {
        'ping': (_) => const FakeResponse.json({}, status: 502),
      });
      final result = await _client(adapter).ping();

      final failure = result.failureOrNull! as ServerFailure;
      expect(failure.statusCode, 502);
      expect(failure.isRetryable, isTrue);
    });

    test('HTTP 200 without a subsonic-response -> ServerFailure', () async {
      final adapter = FakeHttpAdapter(routes: {
        'ping': (_) => const FakeResponse.json({'hello': 'world'}),
      });
      final result = await _client(adapter).ping();
      expect(result.failureOrNull, isA<ServerFailure>());
    });
  });

  group('parsing', () {
    test('ping exposes server type and version', () async {
      final adapter = FakeHttpAdapter(routes: {
        'ping': (_) => FakeResponse.json(subsonicOk({})),
      });
      final ping = (await _client(adapter).ping()).getOrThrow();

      expect(ping.isNavidrome, isTrue);
      expect(ping.serverVersion, startsWith('0.64'));
      expect(ping.openSubsonic, isTrue);
    });

    test('says whether a person administers the server', () async {
      Future<bool?> asks(Object user) async {
        final adapter = FakeHttpAdapter(routes: {
          'getUser': (r) => FakeResponse.json(subsonicOk({'user': user})),
        });
        final client = _client(adapter);
        final result = await client.isAdministrator('owner');
        expect(adapter.requests.single.param('username'), 'owner');
        return result.valueOrNull;
      }

      expect(await asks({'username': 'owner', 'adminRole': true}), isTrue);
      expect(await asks({'username': 'owner', 'adminRole': false}), isFalse);
      expect(await asks({'username': 'owner'}), isFalse,
          reason: 'no role in the answer is no role');
    });

    test('a server that cannot say is not an administrator of anything',
        () async {
      final adapter = FakeHttpAdapter(routes: {
        'getUser': (_) => FakeResponse.json(subsonicError(50, 'not allowed')),
      });

      final result = await _client(adapter).isAdministrator('owner');

      expect(result.isOk, isFalse);
    });

    test('scan status parses nanosecond timestamps', () async {
      final adapter = FakeHttpAdapter(routes: {
        'getScanStatus': (_) => FakeResponse.json(subsonicOk({
              'scanStatus': {
                'scanning': false,
                'count': 5049,
                'folderCount': 261,
                'lastScan': '2026-10-14T18:52:43.299546277Z',
              },
            })),
      });
      final status = (await _client(adapter).getScanStatus()).getOrThrow();

      expect(status.count, 5049);
      expect(status.scanning, isFalse);
      expect(status.lastScanMs,
          DateTime.utc(2026, 10, 14, 18, 52, 43, 299).millisecondsSinceEpoch);
    });

    test('song fields, starred date and replay gain', () async {
      final adapter = FakeHttpAdapter(routes: {
        'search3': (_) => FakeResponse.json(subsonicOk({
              'searchResult3': {
                'song': [_song]
              },
            })),
      });
      final page = (await _client(adapter).search3(songCount: 1)).getOrThrow();
      final s = page.songs.single;

      expect(s.id, 's1');
      expect(s.albumId, 'al1');
      expect(s.suffix, 'flac');
      expect(s.isrc, 'DES561212201');
      expect(s.rgTrackGain, -7.5);
      expect(s.starredAtMs, isNotNull);
      expect(s.createdAtMs, isNotNull);
    });

    test('a single object instead of a list is tolerated', () async {
      final adapter = FakeHttpAdapter(routes: {
        'search3': (_) => FakeResponse.json(subsonicOk({
              'searchResult3': {'song': _song},
            })),
      });
      final page = (await _client(adapter).search3(songCount: 1)).getOrThrow();
      expect(page.songs, hasLength(1));
    });

    test('numbers delivered as strings are accepted', () async {
      final adapter = FakeHttpAdapter(routes: {
        'search3': (_) => FakeResponse.json(subsonicOk({
              'searchResult3': {
                'song': [
                  {'id': 7, 'title': 'T', 'duration': '200', 'bitRate': '320'}
                ]
              },
            })),
      });
      final s = (await _client(adapter).search3(songCount: 1))
          .getOrThrow()
          .songs
          .single;
      expect(s.id, '7');
      expect(s.durationSec, 200);
      expect(s.bitRate, 320);
    });

    test('smart playlist flags and entries', () async {
      final adapter = FakeHttpAdapter(routes: {
        'getPlaylists': (_) => FakeResponse.json(subsonicOk({
              'playlists': {
                'playlist': [
                  {
                    'id': 'p1',
                    'name': 'Phone Offline',
                    'songCount': 800,
                    'readonly': true,
                    'validUntil': '2026-10-11T16:15:58.653912896Z',
                    'changed': '2026-10-11T16:15:53.653912896Z',
                  },
                  {'id': 'p2', 'name': 'Mine', 'songCount': 2},
                ],
              },
            })),
      });
      final list = (await _client(adapter).getPlaylists()).getOrThrow();

      expect(list.first.readonly, isTrue);
      expect(list.first.validUntilMs, isNotNull);
      expect(list.first.entries, isNull,
          reason: 'list endpoint has no entries');
      expect(list.last.readonly, isFalse);
    });

    test('structured lyrics prefer the synced variant', () async {
      final adapter = FakeHttpAdapter(routes: {
        'getLyricsBySongId': (_) => FakeResponse.json(subsonicOk({
              'lyricsList': {
                'structuredLyrics': [
                  {
                    'synced': false,
                    'line': [
                      {'value': 'plain'}
                    ],
                  },
                  {
                    'synced': true,
                    'lang': 'fr',
                    'line': [
                      {'start': 28500, 'value': 'Tes yeux sans âge'},
                      {'start': 31830, 'value': 'Sont des miroirs'},
                    ],
                  },
                ],
              },
            })),
      });
      final lyrics =
          (await _client(adapter).getLyricsBySongId('s1')).getOrThrow()!;

      expect(lyrics.synced, isTrue);
      expect(lyrics.lines.first.startMs, 28500);
      expect(lyrics.lang, 'fr');
    });

    test('no lyrics -> Ok(null), not an error', () async {
      final adapter = FakeHttpAdapter(routes: {
        'getLyricsBySongId': (_) => FakeResponse.json(subsonicOk({
              'lyricsList': {'structuredLyrics': <Object>[]},
            })),
      });
      final result = await _client(adapter).getLyricsBySongId('s1');
      expect(result.isOk, isTrue);
      expect(result.valueOrNull, isNull);
    });
  });

  group('request shape', () {
    test('library dump pages songs with an empty query', () async {
      final adapter = FakeHttpAdapter(routes: {
        'search3': (_) =>
            FakeResponse.json(subsonicOk({'searchResult3': const {}})),
      });
      await _client(adapter).search3(songCount: 500, songOffset: 1000);

      final r = adapter.requests.single;
      expect(r.param('query'), '');
      expect(r.param('songCount'), '500');
      expect(r.param('songOffset'), '1000');
      expect(r.param('artistCount'), '0');
      expect(r.param('albumCount'), '0');
    });

    test('repeated parameters are sent as repeated keys', () async {
      final adapter = FakeHttpAdapter(routes: {
        'star': (_) => FakeResponse.json(subsonicOk({})),
      });
      await _client(adapter).star(songIds: ['a', 'b'], albumIds: ['x']);

      final r = adapter.requests.single;
      expect(r.params['id'], ['a', 'b']);
      expect(r.params['albumId'], ['x']);
    });

    test('formPost is used once advertised, keeping credentials out of the URL',
        () async {
      final adapter = FakeHttpAdapter(routes: {
        'getOpenSubsonicExtensions': (_) => FakeResponse.json(subsonicOk({
              'openSubsonicExtensions': [
                {
                  'name': 'formPost',
                  'versions': [1]
                },
                {
                  'name': 'songLyrics',
                  'versions': [1, 2]
                },
              ],
            })),
        'ping': (_) => FakeResponse.json(subsonicOk({})),
      });
      final client = _client(adapter);
      await client.loadExtensions();
      expect(client.supportsFormPost, isTrue);

      await client.ping();
      final ping = adapter.requests.last;
      expect(ping.method, 'POST');
      expect(ping.uri.query, isEmpty);
      expect(ping.param('t'), isNotNull, reason: 'token travels in the body');
    });

    test('extension discovery on plain Subsonic degrades quietly', () async {
      final adapter = FakeHttpAdapter(routes: {
        'getOpenSubsonicExtensions': (_) =>
            FakeResponse.json(subsonicError(0, 'unknown method')),
      });
      final client = _client(adapter);
      final result = await client.loadExtensions();

      expect(result.isOk, isTrue);
      expect(client.extensions, isEmpty);
    });
  });
}
