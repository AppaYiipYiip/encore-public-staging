import 'dart:convert';

import 'package:encore/core/result.dart';
import 'package:encore/data/api/opensubsonic/opensubsonic_client.dart'
    show SubsonicCredentials;
import 'package:encore/data/navidrome/play_history_client.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_http.dart';

/// Navidrome keeps every completed play of every person (the Subsonic
/// `scrobble` of any app, the web player, a car), and the person's own login
/// can read their own (ADR-064; verified on the owner's version, 0.64.2, with
/// the `tester` account of the reference server). Each row is
/// `{id, mediaFileId, submissionTime}` with the time in epoch seconds, a page
/// is asked with `_start` and `_end`, and the total is in `X-Total-Count`.
void main() {
  late FakeHttpAdapter adapter;
  late PlayHistoryClient client;
  var logins = 0;

  // 25 plays, newest first, one every ten minutes from 2026-10-01 12:00 UTC.
  final base = DateTime.utc(2026, 10, 1, 12).millisecondsSinceEpoch ~/ 1000;
  final rows = [
    for (var i = 24; i >= 0; i--)
      {
        'id': 100 + i,
        'mediaFileId': 'song-${i % 4}',
        'submissionTime': base + i * 600,
      },
  ];

  FakeResponse page(RecordedRequest r) {
    final start = int.parse(r.uri.queryParameters['_start']!);
    final end = int.parse(r.uri.queryParameters['_end']!);
    return FakeResponse.json(
      rows.sublist(start, end.clamp(0, rows.length)),
      headers: {'X-Total-Count': '${rows.length}'},
    );
  }

  setUp(() {
    logins = 0;
    adapter = FakeHttpAdapter(routes: {
      '/auth/login': (r) {
        logins++;
        final body = jsonDecode(r.body) as Map<String, dynamic>;
        return body['password'] == 'right'
            ? FakeResponse.json({'token': 'tok$logins', 'name': 'tester'})
            : const FakeResponse.json({'error': 'Invalid username or password'},
                status: 401);
      },
      '/api/scrobble': page,
    });
    client = PlayHistoryClient(
      dio: fakeDio(adapter),
      baseUrl: () => Uri.parse('https://music.example/'),
      credentials:
          const SubsonicCredentials(username: 'tester', password: 'right'),
      pageSize: 10,
    );
  });

  test('reads all of a person\'s plays, page after page', () async {
    final result = await client.fetchAll();

    final listens = result.valueOrNull!;
    expect(listens, hasLength(25));
    expect(listens.first.trackId, 'song-0');
    expect(listens.first.at.millisecondsSinceEpoch, (base + 24 * 600) * 1000,
        reason: 'the newest play first, as the server sorts it');
    expect(
        adapter.requests
            .where((r) => r.uri.path == '/api/scrobble')
            .map((r) => r.uri.queryParameters['_start']),
        containsAll(['0', '10', '20']));
  });

  test('signs in once, with the person\'s own name and password', () async {
    await client.fetchAll();

    expect(logins, 1);
    final login =
        adapter.requests.firstWhere((r) => r.uri.path == '/auth/login');
    expect(jsonDecode(login.body), {'username': 'tester', 'password': 'right'});
    for (final r
        in adapter.requests.where((r) => r.uri.path == '/api/scrobble')) {
      expect(r.headers['x-nd-authorization'], 'Bearer tok1');
    }
  });

  test('says how far it has got, so a long history shows progress', () async {
    final seen = <(int, int)>[];

    await client.fetchAll(progress: (done, total) => seen.add((done, total)));

    expect(seen.first, (10, 25));
    expect(seen.last, (25, 25));
  });

  test('a wrong password is an authentication failure, not "no history"',
      () async {
    final wrong = PlayHistoryClient(
      dio: fakeDio(adapter),
      baseUrl: () => Uri.parse('https://music.example/'),
      credentials:
          const SubsonicCredentials(username: 'tester', password: 'nope'),
    );

    final result = await wrong.fetchAll();

    expect(result.failureOrNull, isA<AuthFailure>());
  });

  test('a server without a play history says so (not Navidrome, or too old)',
      () async {
    adapter.routes['/api/scrobble'] =
        (_) => const FakeResponse.json({'error': 'not found'}, status: 404);

    final result = await client.fetchAll();

    final failure = result.failureOrNull! as ServerFailure;
    expect(failure.statusCode, 404);
  });

  test('an expired sign-in is renewed once, and the page asked again',
      () async {
    var first = true;
    adapter.routes['/api/scrobble'] = (r) {
      if (first) {
        first = false;
        return const FakeResponse.json({'error': 'expired'}, status: 401);
      }
      return page(r);
    };

    final result = await client.fetchAll();

    expect(result.valueOrNull, hasLength(25));
    expect(logins, 2);
  });

  test('a server that cannot be reached is a network failure', () async {
    adapter.routes['/auth/login'] = (_) => const FakeResponse.connectionError();

    final result = await client.fetchAll();

    expect(result.failureOrNull, isA<NetworkFailure>());
  });

  test(
      'the password is never sent over plain http to an address on the internet',
      () async {
    final plain = PlayHistoryClient(
      dio: fakeDio(adapter),
      baseUrl: () => Uri.parse('http://music.example:4533/'),
      credentials:
          const SubsonicCredentials(username: 'tester', password: 'right'),
    );

    final result = await plain.fetchAll();

    expect(result.failureOrNull, isNotNull);
    expect(adapter.requests, isEmpty, reason: 'nothing left the phone');
  });

  test('an address at home may use plain http, as the rest of the app does',
      () async {
    final home = PlayHistoryClient(
      dio: fakeDio(adapter),
      baseUrl: () => Uri.parse('http://192.168.50.132:4533/'),
      credentials:
          const SubsonicCredentials(username: 'tester', password: 'right'),
    );

    final result = await home.fetchAll();

    expect(result.valueOrNull, hasLength(25));
  });

  test('a person with no plays has an empty history', () async {
    adapter.routes['/api/scrobble'] =
        (_) => const FakeResponse.json([], headers: {'X-Total-Count': '0'});

    final result = await client.fetchAll();

    expect(result.valueOrNull, isEmpty);
  });
}
