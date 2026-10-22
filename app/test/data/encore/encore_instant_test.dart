import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:encore/data/encore/encore_api.dart';
import 'package:encore/data/encore/encore_instant.dart';
import 'package:encore/data/encore/encore_models.dart';
import 'package:encore/data/fetch/fetch_client.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_encore_server.dart';

/// A music server that is not there.
class _Unreachable implements HttpClientAdapter {
  @override
  Future<ResponseBody> fetch(RequestOptions options,
          Stream<Uint8List>? requestStream, Future<void>? cancelFuture) =>
      Future.error(DioException.connectionError(
          requestOptions: options, reason: 'no route to host'));

  @override
  void close({bool force = false}) {}
}

void main() {
  late FakeEncoreServer server;
  late List<EncoreRef> ingested;
  late EncoreInstantBackend backend;
  var now = DateTime(2026, 10, 22, 12);

  int hits(String endOfPath) => server.adapter.requests
      .where((r) => r.uri.path.endsWith(endOfPath))
      .length;

  setUp(() {
    server = FakeEncoreServer();
    ingested = [];
    now = DateTime(2026, 10, 22, 12);
    final api = EncoreApi(
      dio: Dio()..httpClientAdapter = server.adapter,
      baseUrl: () => Uri.parse('http://home.test:4540'),
      auth: () => {'u': 'tester', 't': 'tok', 's': 'salt'},
    );
    backend = EncoreInstantBackend(
      api: api,
      ingest: (refs) async => ingested.addAll(refs),
      now: () => now,
    );
  });

  const request = FetchRequest(
    artist: 'Stromae',
    title: 'Que ce soit clair',
    album: 'Multitude',
    durationSec: 207,
    coverUrl: 'https://img.example/c.jpg',
  );

  test(
      'a tapped song is resolved to a ref, given its row, and is ready at once: the player opens the stream',
      () async {
    final job = (await backend.start(request)).getOrThrow();

    expect(job.state, FetchState.ready);
    expect(job.id, startsWith('sr_'));
    expect(job.songId, job.id, reason: 'the row of the song has the ref\'s id');
    expect(ingested.single.id, job.id);
    expect(ingested.single.title, 'Que ce soit clair');
    expect(ingested.single.coverUrl, 'https://img.example/c.jpg');
    expect(backend.streamUri(job), isNull);
    expect(hits('library/changes'), 0,
        reason: 'playing is not saving: nothing is added to the library');
  });

  test('the same song is the same ref; a prepare and a tap are one question',
      () async {
    await backend.prepare(request);
    final first = (await backend.start(request)).getOrThrow();
    final again = (await backend.start(request)).getOrThrow();

    expect(again.id, first.id);
    expect(server.refs, hasLength(1));
    expect(hits('refs/resolve'), lessThanOrEqualTo(3));
  });

  test('a song the server keeps carries its codec; no look at YouTube is made',
      () async {
    final kept = server.addRef('Nude', 'Radiohead',
        album: 'In Rainbows', fileId: 'nd-1', meta: {'albumId': 'al0'});
    server.youtubeState = 'resting';

    final job = (await backend.start(const FetchRequest(
            artist: 'Radiohead', title: 'Nude', durationSec: 200)))
        .getOrThrow();

    expect(job.id, kept);
    expect(job.state, FetchState.ready,
        reason: 'a kept song plays whatever YouTube thinks of the server');
  });

  test(
      'while YouTube has the server resting a new song says so in words, once, and nothing is saved',
      () async {
    server.youtubeState = 'resting';

    final job = (await backend.start(request)).getOrThrow();
    await backend.start(request);

    expect(job.state, FetchState.failed);
    expect(job.error, 'resting');
    expect(job.message, contains('YouTube'));
    expect(ingested, isEmpty);
    expect(hits('/info'), 1,
        reason: 'the answer is remembered for a little while');
  });

  test('the server\'s answer about YouTube is asked again after a while',
      () async {
    server.youtubeState = 'resting';
    await backend.start(request);
    server.youtubeState = 'ok';
    now = now.add(const Duration(minutes: 1));

    final job = (await backend.start(request)).getOrThrow();

    expect(job.state, FetchState.ready);
  });

  test('a server that cannot be reached fails the song with the reason',
      () async {
    final dead = EncoreInstantBackend(
      api: EncoreApi(
        dio: Dio()..httpClientAdapter = _Unreachable(),
        baseUrl: () => Uri.parse('http://home.test:4540'),
        auth: () => const {},
      ),
      ingest: (_) async {},
    );

    final result = await dead.start(request);

    expect(result.isErr, isTrue);
  });
}
