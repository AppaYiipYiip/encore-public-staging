import 'package:dio/dio.dart';
import 'package:encore/core/result.dart';
import 'package:encore/data/fetch/fetch_client.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_http.dart';

void main() {
  late FakeHttpAdapter adapter;
  late EncoreFetchClient client;

  Dio dio() => Dio(BaseOptions(validateStatus: (_) => true))
    ..httpClientAdapter = adapter;

  setUp(() {
    adapter = FakeHttpAdapter(routes: {
      '/api/play': (r) => const FakeResponse.json(
          {'id': 'abc123def4567890', 'state': 'queued'},
          status: 202),
      '/api/play/abc123def4567890': (r) => const FakeResponse.json({
            'id': 'abc123def4567890',
            'state': 'ready',
            'songId': 'song-9',
            'path': 'Opeth/Damnation/05 - Windowpane.opus',
            'codec': 'opus',
            'bitrateKbps': 158,
          }),
    });
    client = EncoreFetchClient(
      baseUrl: Uri.parse('http://192.168.50.129:8701'),
      auth: () => {'u': 'marwa', 't': 'tok', 's': 'salt'},
      dio: dio(),
    );
  });

  test('start posts the song with the music login in the query', () async {
    final result = await client.start(const FetchRequest(
      artist: 'Opeth',
      title: 'Windowpane',
      album: 'Damnation',
      trackNumber: 5,
      durationSec: 467,
      coverUrl: 'https://cdn-images.dzcdn.net/x.jpg',
    ));

    expect(result.valueOrNull?.state, FetchState.queued);
    final sent = adapter.requests.single;
    expect(sent.method, 'POST');
    expect(sent.uri.path, '/api/play');
    expect(sent.uri.queryParameters, {'u': 'marwa', 't': 'tok', 's': 'salt'});
    expect(sent.body, contains('"artist":"Opeth"'));
    expect(sent.body, contains('"trackNumber":5'));
    expect(sent.body, contains('"durationSec":467'));
  });

  group('the stream address (P1-02)', () {
    EncoreFetchClient streaming(
            {String base = 'http://192.168.50.129:8701',
            bool canStream = true}) =>
        EncoreFetchClient(
          baseUrl: Uri.parse(base),
          auth: () => {'u': 'marwa', 't': 'tok', 's': 'salt'},
          dio: dio(),
          canStream: canStream,
        );

    test('carries the song, the video the playlist saved, and the login', () {
      final uri = streaming().streamUrlFor(const FetchRequest(
        artist: 'Reciter',
        title: 'Surat Al-Baqarah',
        durationSec: 8481,
        videoId: 'dQw4w9WgXcQ',
        official: true,
      ))!;

      expect(uri.path, '/api/stream');
      expect(uri.queryParameters, {
        'u': 'marwa',
        't': 'tok',
        's': 'salt',
        'videoId': 'dQw4w9WgXcQ',
        'official': '1',
        'artist': 'Reciter',
        'title': 'Surat Al-Baqarah',
        'durationSec': '8481',
      });
    });

    test('a service that cannot stream has none', () {
      expect(
          streaming(canStream: false)
              .streamUrlFor(const FetchRequest(artist: 'A', title: 'B')),
          isNull);
    });

    test('the login does not go to a public address without https', () {
      expect(
          streaming(base: 'http://music.example.org:8701')
              .streamUrlFor(const FetchRequest(artist: 'A', title: 'B')),
          isNull);
      expect(
          streaming(base: 'https://music.example.org')
              .streamUrlFor(const FetchRequest(artist: 'A', title: 'B')),
          isNotNull);
    });

    test('the service info says whether it can stream', () {
      expect(const FetchServiceInfo(features: ['play-now', 'stream']).canStream,
          isTrue);
      expect(const FetchServiceInfo(features: ['play-now']).canStream, isFalse);
    });
  });

  group('the music login only travels over a safe address (docs/23, B25)', () {
    EncoreFetchClient at(String base) => EncoreFetchClient(
          baseUrl: Uri.parse(base),
          auth: () => {'u': 'marwa', 't': 'tok', 's': 'salt'},
          dio: dio(),
        );
    const request = FetchRequest(artist: 'Opeth', title: 'Windowpane');

    test('a public address without https gets nothing', () async {
      final unsafe = at('http://music.example.org:8701');

      final result = await unsafe.start(request);
      await unsafe.prepare(request);
      final status = await unsafe.status('abc123def4567890');

      expect(result.isOk, isFalse);
      expect(result.failureOrNull!.message, contains('https://'));
      expect(status.isOk, isFalse);
      expect(adapter.requests, isEmpty,
          reason: 'the token is a replayable credential');
      expect(
          unsafe.streamUri(const FetchJob(
              id: 'abc123def4567890',
              state: FetchState.ready,
              stream: '/api/play/abc123def4567890/audio')),
          isNull,
          reason: 'a stream address carries the token too');
    });

    test('a public address with https carries the login as before', () async {
      final result = await at('https://music.example.org').start(request);

      expect(result.valueOrNull?.state, FetchState.queued);
      expect(adapter.requests.single.uri.queryParameters['t'], 'tok');
    });
  });

  test('empty or invalid optional fields are not sent', () {
    const r = FetchRequest(
        artist: 'A', title: 'B', trackNumber: 0, year: 5, durationSec: 1);
    expect(r.toJson(), {'artist': 'A', 'title': 'B'});
  });

  test('status reads the finished job', () async {
    final result = await client.status('abc123def4567890');
    final job = result.valueOrNull!;
    expect(job.state, FetchState.ready);
    expect(job.state.isDone, isTrue);
    expect(job.songId, 'song-9');
    expect(job.codec, 'opus');
    expect(job.bitrateKbps, 158);
  });

  test('a refused login and a rate limit are told apart', () async {
    adapter.routes['/api/play'] =
        (r) => const FakeResponse.json({'error': 'sign in'}, status: 401);
    final denied =
        await client.start(const FetchRequest(artist: 'A', title: 'B'));
    expect(denied.failureOrNull, isA<AuthFailure>());

    adapter.routes['/api/play'] = (r) => const FakeResponse.json(
        {'error': 'rate_limited', 'message': 'Too many songs at once.'},
        status: 429);
    final limited =
        await client.start(const FetchRequest(artist: 'A', title: 'B'));
    expect(limited.failureOrNull?.message, 'Too many songs at once.');
    final failure = limited.failureOrNull! as ServerFailure;
    expect((failure.statusCode, failure.code), (429, 'rate_limited'),
        reason: 'the app tells "wait and ask again" from "no more today"');
  });

  test('a service that cannot be reached is a network failure naming it',
      () async {
    adapter.routes['/api/play'] = (r) => const FakeResponse.connectionError();
    final result =
        await client.start(const FetchRequest(artist: 'A', title: 'B'));
    expect(result.failureOrNull, isA<NetworkFailure>());
    expect(result.failureOrNull!.message, contains('192.168.50.129:8701'));
  });

  group('prepare', () {
    const song = FetchRequest(artist: 'Opeth', title: 'Windowpane');

    test('posts the same song to /api/prepare', () async {
      adapter.routes['/api/prepare'] = (r) => const FakeResponse.json(
          {'id': 'abc123def4567890', 'state': 'prepared'},
          status: 202);
      await client.prepare(song);
      final sent = adapter.requests.single;
      expect(sent.method, 'POST');
      expect(sent.uri.path, '/api/prepare');
      expect(sent.uri.queryParameters['u'], 'marwa');
      expect(sent.body, contains('"title":"Windowpane"'));
    });

    test('is never an error: a failing service is simply not prepared',
        () async {
      adapter.routes['/api/prepare'] =
          (r) => const FakeResponse.connectionError();
      await client.prepare(song);
      adapter.routes['/api/prepare'] =
          (r) => const FakeResponse.json({'error': 'boom'}, status: 500);
      await client.prepare(song);
      expect(adapter.requests, hasLength(2));
    });

    test('an older service that does not know it is asked only once', () async {
      adapter.routes['/api/prepare'] =
          (r) => const FakeResponse.json({'error': 'not found'}, status: 404);
      await client.prepare(song);
      await client.prepare(song);
      expect(adapter.requests, hasLength(1));
    });

    test('the probe reports whether the service can prepare', () async {
      adapter.routes['/api/info'] = (r) => const FakeResponse.json({
            'service': 'encore-fetch',
            'version': 1,
            'features': ['play-now', 'prepare'],
          });
      final info = await EncoreFetchClient.probe(
          Uri.parse('http://192.168.50.129:8701'),
          dio: dio());
      expect(info!.canPrepare, isTrue);
    });
  });

  group('probe', () {
    test('recognises the service and what it offers', () async {
      adapter.routes['/api/info'] = (r) => const FakeResponse.json({
            'service': 'encore-fetch',
            'version': 1,
            'features': ['play-now'],
          });
      final info = await EncoreFetchClient.probe(
          Uri.parse('http://192.168.50.129:8701'),
          dio: dio());
      expect(info, isNotNull);
      expect(info!.canPlayNow, isTrue);
    });

    test('anything else answering is not the service', () async {
      adapter.routes['/api/info'] =
          (r) => const FakeResponse.json({'service': 'something-else'});
      expect(
          await EncoreFetchClient.probe(Uri.parse('http://10.0.0.5:8701'),
              dio: dio()),
          isNull);
      adapter.routes['/api/info'] = (r) => const FakeResponse.connectionError();
      expect(
          await EncoreFetchClient.probe(Uri.parse('http://10.0.0.5:8701'),
              dio: dio()),
          isNull);
    });
  });
}
