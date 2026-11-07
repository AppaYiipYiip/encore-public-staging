import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:encore/core/result.dart';
import 'package:encore/data/encore/encore_api.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_encore_server.dart';

EncoreApi apiFor(FakeEncoreServer server, {String? deviceId}) {
  final dio = Dio()..httpClientAdapter = server.adapter;
  return EncoreApi(
    dio: dio,
    baseUrl: () => Uri.parse('http://home.test:4540'),
    auth: () => {'u': 'tester', 't': 'tok', 's': 'salt'},
    deviceId: deviceId,
  );
}

/// What the Wi-Fi of a cafe or a station answers instead of the server: a web page asking the visitor to sign in.
class _Portal implements HttpClientAdapter {
  _Portal(this.status);

  final int status;

  @override
  Future<ResponseBody> fetch(RequestOptions options,
          Stream<Uint8List>? requestStream, Future<void>? cancelFuture) async =>
      ResponseBody.fromString(
          '<html><body>Sign in to the Wi-Fi network</body></html>', status,
          headers: {
            Headers.contentTypeHeader: ['text/html'],
          });

  @override
  void close({bool force = false}) {}
}

void main() {
  late FakeEncoreServer server;
  late EncoreApi api;

  group(
      'a Wi-Fi sign-in page answering instead of the server (field test 2026-10-31)',
      () {
    EncoreApi behind(int status) => EncoreApi(
          dio: Dio()..httpClientAdapter = _Portal(status),
          baseUrl: () => Uri.parse('http://home.test:4540'),
          auth: () => {'u': 'tester', 't': 'tok', 's': 'salt'},
        );

    test('a page is not an answer: nothing is read from it', () async {
      final result = await behind(200).me();

      expect(result, isA<Err<Object?>>(),
          reason: 'an empty person with the role of a guest is not who I am');
      expect(result.failureOrNull, isNot(isA<AuthFailure>()));
    });

    test('a refusal that is not the own of the server is not "sign in again"',
        () async {
      for (final status in [401, 403]) {
        final result = await behind(status).me();

        expect(result.failureOrNull, isA<NetworkFailure>(),
            reason: 'status $status from a page: this is not your server');
      }
    });
  });

  setUp(() {
    server = FakeEncoreServer();
    api = apiFor(server);
  });

  test('info says what the server is and carries no login', () async {
    final info = (await api.info()).getOrThrow();

    expect(info.hasRefs, isTrue);
    expect(info.youtubeState, 'ok');
    final request = server.adapter.requests.single;
    expect(request.uri.path, '/encore/api/v1/info');
    expect(request.uri.queryParameters['u'], 'tester',
        reason: 'the music server\'s token login rides along on every call');
  });

  test('resolving a song gives it a ref, and the same song again the same ref',
      () async {
    const song = {
      'title': 'Weird Fishes',
      'artists': ['Radiohead'],
      'album': 'In Rainbows',
      'durationMs': 318000
    };

    final first = (await api.resolve([song])).getOrThrow().single;
    final again = (await api.resolve([song])).getOrThrow().single;

    expect(first.id, startsWith('sr_'));
    expect(again.id, first.id);
    expect(first.artist, 'Radiohead');
    expect(first.durationSec, 318);
    expect(first.file, isNull);
  });

  test('a song the server keeps arrives with the music server\'s ids',
      () async {
    final id = server.addRef('Nude', 'Radiohead',
        album: 'In Rainbows',
        fileId: 'nd-1',
        meta: {
          'albumId': 'al-7',
          'artistId': 'ar-3',
          'coverArt': 'al-7',
          'size': 4499697,
          'suffix': 'opus'
        });

    final ref = (await api.ref(id)).getOrThrow();

    expect(ref.file!.navidromeSongId, 'nd-1');
    expect(ref.file!.albumId, 'al-7');
    expect(ref.file!.coverArt, 'al-7');
    expect(ref.file!.size, 4499697);
    expect(ref.file!.suffix, 'opus');
  });

  test('likes are a set: liking twice is one like, unliking removes it',
      () async {
    final id = server.addRef('Nude', 'Radiohead');

    await api.like(id);
    await api.like(id);
    expect(server.likes.keys, [id]);

    await api.unlike(id);
    expect(server.likes, isEmpty);
  });

  test('changes are the state now, after a cursor', () async {
    final a = server.addRef('A', 'X');
    final b = server.addRef('B', 'X');
    await api.like(a);
    final first = (await api.changes(since: '0')).getOrThrow();
    await api.like(b);
    await api.unlike(a);
    final next = (await api.changes(since: first.cursor)).getOrThrow();

    expect([for (final l in first.likes) (l.ref, l.removed)], [(a, false)]);
    expect([for (final l in next.likes) (l.ref, l.removed)],
        [(a, true), (b, false)]);
    expect([for (final r in next.refs) r.id], [b],
        reason: 'only songs that are still wanted come with their data');
  });

  test(
      'playlists: made with an id of the phone\'s own, entries added, moved and removed',
      () async {
    final a = server.addRef('A', 'X');
    final b = server.addRef('B', 'X');

    (await api.createPlaylist('pl_${'1' * 26}', 'Road trip')).getOrThrow();
    (await api.createPlaylist('pl_${'1' * 26}', 'Road trip'))
        .getOrThrow(); // a retry
    (await api.addEntries('pl_${'1' * 26}', [
      (ref: a, entryId: 'pe_${'a' * 26}'),
      (ref: b, entryId: 'pe_${'b' * 26}')
    ]))
        .getOrThrow();
    (await api.addEntries(
            'pl_${'1' * 26}', [(ref: a, entryId: 'pe_${'a' * 26}')]))
        .getOrThrow(); // a retry
    expect(server.playlists, hasLength(1));
    expect(server.entries['pl_${'1' * 26}'], hasLength(2));

    (await api.reorder('pl_${'1' * 26}', ['pe_${'b' * 26}', 'pe_${'a' * 26}']))
        .getOrThrow();
    (await api.removeEntries('pl_${'1' * 26}', ['pe_${'a' * 26}']))
        .getOrThrow();
    (await api.renamePlaylist('pl_${'1' * 26}', 'Better')).getOrThrow();

    final changes = (await api.changes(since: '0')).getOrThrow();
    expect(changes.playlists.single.name, 'Better');
    expect({
      for (final e in changes.entries) e.id: (e.deleted, e.position)
    }, {
      'pe_${'a' * 26}': (true, 2.0),
      'pe_${'b' * 26}': (false, 1.0),
    });
  });

  test('plays are reported once however often they are sent', () async {
    final id = server.addRef('A', 'X');

    (await api.play(id: 'p1', refId: id, atMs: 5, msPlayed: 200000))
        .getOrThrow();
    (await api.play(id: 'p1', refId: id, atMs: 5, msPlayed: 200000))
        .getOrThrow();

    expect(server.plays, hasLength(1));
  });

  test(
      'the stream address of a song is made absolute against the server\'s address',
      () async {
    final id = server.addRef('A', 'X');

    final url = (await api.streamUrl(id)).getOrThrow();

    expect(url.host, 'home.test');
    expect(url.port, 4540);
    expect(url.path, '/encore/stream/$id');
  });

  test(
      'the next songs of the queue are named to the server so it can make them ready, and it says how many it took (P1-04)',
      () async {
    final a = server.addRef('A', 'X');
    final b = server.addRef('B', 'Y');

    final taken = (await api.prepare([a, b, 'sr_nobody'])).getOrThrow();

    expect(server.prepareAsked, [
      [a, b, 'sr_nobody']
    ]);
    expect(taken, 2);
  });

  test('the address of a song says when it stops working', () async {
    final id = server.addRef('A', 'X');

    final address = (await api.streamAddress(id)).getOrThrow();

    expect(address.url.queryParameters['sig'], 'abc');
  });

  test(
      'an address lives as long as the server says it does, counted by the '
      "phone's own clock (a phone whose clock is out keeps no dead address)",
      () async {
    final id = server.addRef('A', 'X');
    final phoneNow = DateTime.utc(2030, 1, 1, 12);
    final skewed = EncoreApi(
      dio: Dio()..httpClientAdapter = server.adapter,
      baseUrl: () => Uri.parse('http://home.test:4540'),
      auth: () => {'u': 'tester', 't': 'tok', 's': 'salt'},
      clock: () => phoneNow,
    );

    // The fake server says it is `clockMs` and that the address ends at 9999999999000.
    final address = (await skewed.streamAddress(id)).getOrThrow();

    expect(address.expiresAt,
        phoneNow.add(Duration(milliseconds: 9999999999000 - server.clockMs)));
  });

  test('one ticket opens every picture, and says when it ends', () async {
    final pass = (await api.coverPass()).getOrThrow();

    expect(pass.person, 'pn_x');
    expect(pass.signature, 'coversig');
    expect(pass.expires, 9999999999,
        reason: 'the end exactly as the server signed it (audit B-115)');
    expect(
        pass.expiresAt.isAfter(DateTime.now().add(const Duration(days: 365))),
        isTrue);
    expect(
        server.adapter.requests.single.uri.path, '/encore/api/v1/covers/pass');
  });

  test('the files feed lists what the server keeps, then only what changed',
      () async {
    final a = server.addRef('A', 'X', fileId: 'nd-1');
    final first = (await api.files(since: '0')).getOrThrow();
    server.addRef('B', 'X', fileId: 'nd-2');
    server.removeFile(a);
    final next = (await api.files(since: first.cursor)).getOrThrow();

    expect([for (final r in first.refs) r.id], [a]);
    expect([for (final r in next.refs) (r.title, r.file?.navidromeSongId)],
        [('B', 'nd-2'), ('A', null)]);
  });

  test('the server\'s one error shape becomes the app\'s failure types',
      () async {
    final missing = await api.ref('sr_${'9' * 26}');
    expect(missing.failureOrNull, isA<NotFoundFailure>());

    server.online = false;
    final offline = await api.info();
    expect(offline.failureOrNull, isA<NetworkFailure>());
  });

  test(
      'this device\'s id travels with every call, so the server can tell who changed what',
      () async {
    api = apiFor(server, deviceId: 'dv_${'2' * 26}');

    await api.info();

    expect(server.adapter.requests.single.headers['x-encore-device'],
        'dv_${'2' * 26}');
  });
}
