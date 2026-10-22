import 'package:dio/dio.dart';
import 'package:encore/core/result.dart';
import 'package:encore/data/fetch/fetch_client.dart';
import 'package:encore/data/fetch/import_models.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_http.dart';

/// The app's side of importing a playlist (ADR-100): read a link, hand the
/// list to the server, watch it. The server's words reach the person as they
/// are.
void main() {
  late FakeHttpAdapter adapter;
  late EncoreFetchClient client;

  Dio dio() => Dio(BaseOptions(validateStatus: (_) => true))
    ..httpClientAdapter = adapter;

  final running = <String, Object?>{
    'id': 'd6026d2b029d',
    'name': 'Evening',
    'kind': 'playlist',
    'source': 'spotify',
    'state': 'running',
    'total': 40,
    'done': 10,
    'added': 9,
    'missing': 1,
    'waiting': 30,
    'playlistReady': true,
    'playlistId': 'pl-1',
    'etaSec': 600,
  };

  setUp(() {
    adapter = FakeHttpAdapter();
    client = EncoreFetchClient(
      baseUrl: Uri.parse('https://music.example.org/fetch'),
      auth: () => {'u': 'nina', 't': 'tok', 's': 'salt'},
      dio: dio(),
    );
  });

  group('reading a link', () {
    test('asks the service for the songs and keeps what it says', () async {
      adapter.routes['/fetch/api/playlist'] = (r) => const FakeResponse.json({
            'name': 'Evening',
            'source': 'spotify',
            'kind': 'playlist',
            'count': 2,
            'truncated': true,
            'tracks': [
              {'title': 'Windowpane', 'artist': 'Opeth', 'durationSec': 467},
              {'title': 'FN8', 'artist': 'Arcangel', 'videoId': 'NFvDHYMzj9U'},
            ],
          });

      final result = await client.readPlaylist(
          'https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M');

      final list = result.valueOrNull!;
      expect((list.name, list.sourceName, list.truncated, list.tracks.length),
          ('Evening', 'Spotify', true, 2));
      expect(list.tracks.last.videoId, 'NFvDHYMzj9U');
      final sent = adapter.requests.single;
      expect(sent.method, 'POST');
      expect(sent.uri.queryParameters['u'], 'nina');
      expect(sent.body, contains('"url":"https://open.spotify.com/playlist/'));
    });

    test('a private playlist reaches the person in the service words',
        () async {
      adapter.routes['/fetch/api/playlist'] = (r) => const FakeResponse.json({
            'error': 'not_found',
            'message': 'That playlist is private or does not exist.',
          }, status: 404);

      final result = await client.readPlaylist('https://x');

      expect(result.failureOrNull?.message,
          'That playlist is private or does not exist.');
      final failure = result.failureOrNull! as ServerFailure;
      expect((failure.statusCode, failure.code), (404, 'not_found'));
    });

    test('a refused login is an auth failure, not a vague one', () async {
      adapter.routes['/fetch/api/playlist'] =
          (r) => const FakeResponse.json({'error': 'sign in'}, status: 401);
      expect((await client.readPlaylist('https://x')).failureOrNull,
          isA<AuthFailure>());
    });
  });

  group('handing the list over', () {
    test('sends the name, the kind and every song, and answers at once',
        () async {
      adapter.routes['/fetch/api/import'] =
          (r) => FakeResponse.json(running, status: 202);

      final result = await client.startImport(
        name: 'Evening',
        source: 'spotify',
        liked: true,
        tracks: const [
          ImportedTrack(title: 'Windowpane', artist: 'Opeth', durationSec: 467),
          ImportedTrack(title: 'FN8', artist: 'Arcangel', album: ''),
          ImportedTrack(
              title: 'Harvest',
              artist: 'Opeth',
              videoId: 'sj27caXHKm4',
              official: true),
        ],
      );

      expect(result.valueOrNull?.id, 'd6026d2b029d');
      final body = adapter.requests.single.body;
      expect(body, contains('"kind":"liked"'));
      expect(body, contains('"title":"Windowpane"'));
      expect(body, contains('"durationSec":467'));
      expect(body, isNot(contains('"album"')),
          reason: 'an empty album is not sent');
      expect(body, contains('"official":true'),
          reason: 'the server searches only for songs that are not official');
    });

    test('a list the server refuses says why', () async {
      adapter.routes['/fetch/api/import'] = (r) => const FakeResponse.json({
            'error': 'too_many',
            'message': 'That is more than 5000 songs in one import.',
          }, status: 413);
      final result = await client.startImport(
        name: 'x',
        source: 'file',
        tracks: const [ImportedTrack(title: 'a', artist: 'b')],
      );
      expect(result.failureOrNull?.message, contains('5000 songs'));
    });
  });

  group('watching it', () {
    test('an import is read with what is added and what is missing', () async {
      adapter.routes['/fetch/api/import/d6026d2b029d'] =
          (r) => FakeResponse.json({
                ...running,
                'missingSongs': [
                  {
                    'title': 'Burden',
                    'artist': 'Opeth',
                    'reason': 'not_found',
                    'message': 'Nothing matching was found on YouTube.',
                  },
                ],
              });

      final job = (await client.importStatus('d6026d2b029d')).valueOrNull!;

      expect((job.done, job.added, job.missing, job.total), (10, 9, 1, 40));
      expect(job.playlistId, 'pl-1');
      expect(job.missingSongs.single.message,
          'Nothing matching was found on YouTube.');
      expect(job.fraction, 0.25);
      expect(job.etaText, 'about 10 minutes left');
    });

    test('the list of imports is read in the order the service sends it',
        () async {
      adapter.routes['/fetch/api/import'] = (r) => FakeResponse.json({
            'imports': [
              {...running, 'id': 'bbbbbbbbbbbb', 'name': 'Two'},
              {...running, 'id': 'aaaaaaaaaaaa', 'name': 'One'},
            ],
          });
      final jobs = (await client.imports()).valueOrNull!;
      expect([for (final j in jobs) j.name], ['Two', 'One']);
    });

    test('stopping posts to the import and returns the stopped import',
        () async {
      adapter.routes['/fetch/api/import/d6026d2b029d/cancel'] =
          (r) => FakeResponse.json({...running, 'state': 'cancelled'});
      final job = (await client.cancelImport('d6026d2b029d')).valueOrNull!;
      expect(job.state, ImportState.cancelled);
      expect(adapter.requests.single.method, 'POST');
    });

    test('the login only travels over a safe address', () async {
      final unsafe = EncoreFetchClient(
        baseUrl: Uri.parse('http://music.example.org:8701'),
        auth: () => {'u': 'nina', 't': 'tok', 's': 'salt'},
        dio: dio(),
      );
      expect((await unsafe.imports()).isOk, isFalse);
      expect((await unsafe.readPlaylist('https://x')).isOk, isFalse);
      expect(adapter.requests, isEmpty);
    });
  });

  group('what the person is told', () {
    ImportJob job(Map<String, Object?> more) =>
        ImportJob.fromJson({...running, ...more});

    test('the time left is said in minutes or hours, not seconds', () {
      expect(job({'etaSec': 40}).etaText, 'about a minute left');
      expect(job({'etaSec': 600}).etaText, 'about 10 minutes left');
      // A long wait is never shown as a number of hours: the playlist plays at once, the rest is saved in the background.
      expect(job({'etaSec': 3000}).etaText, 'about 50 minutes left');
      expect(job({'etaSec': 7200}).etaText,
          'the rest keeps saving in the background');
      expect(job({'etaSec': 3600}).etaText,
          'the rest keeps saving in the background');
      expect(job({'etaSec': 0}).etaText, isNull);
      expect(job({'state': 'done', 'etaSec': 600}).etaText, isNull);
    });

    test('before agreeing the person is told roughly how long it takes', () {
      expect(importEstimate(5), 'about a minute');
      expect(importEstimate(100), 'about 20 minutes');
      expect(importEstimate(1000), 'about 3.3 hours');
    });

    test(
        'the review page promises the playlist at once and puts the saving in the background',
        () {
      for (final songs in [5, 100, 1000]) {
        final text = importPromise(songs);
        expect(text, contains('as soon as you tap Import'), reason: '$songs');
        expect(text, contains('in the background'), reason: '$songs');
      }
      expect(importPromise(100), contains('about 20 minutes'));
      expect(importPromise(1000), isNot(contains('hours,')));
      expect(importPromise(1000), contains('a few hours'));
    });

    test('an unknown state is not a crash and an empty list is not a bar', () {
      final odd = job({'state': 'something new', 'total': 0});
      expect(odd.state, ImportState.running);
      expect(odd.fraction, 0);
    });

    test('the service says what it can do', () {
      const old = FetchServiceInfo(features: ['play-now', 'prepare']);
      const current = FetchServiceInfo(
          features: ['play-now', 'prepare', 'playlist', 'import']);
      expect((old.canImport, old.canReadPlaylists), (false, false));
      expect((current.canImport, current.canReadPlaylists), (true, true));
    });
  });
}
