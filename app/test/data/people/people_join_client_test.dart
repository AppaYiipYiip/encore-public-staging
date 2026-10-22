import 'dart:convert';

import 'package:encore/core/result.dart';
import 'package:encore/data/people/people_join_client.dart';
import 'package:encore/domain/invite_link.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_http.dart';

/// What the people service answers a person who was invited (verified on the
/// reference server, 2026-10-17): `GET /join/<code>/info` says who invited and
/// what the server is called; `POST /join/<code>/redeem` makes the account and
/// answers 201 with the name and the address to sign in at. The app does these
/// two calls itself, so nobody is sent to a browser and back (docs/39 F3).
void main() {
  late FakeHttpAdapter adapter;
  late PeopleJoinClient client;
  final link = findInviteLink('https://music.example/people/join/Code123')!;

  void serve(Map<String, FakeHandler> routes) {
    adapter = FakeHttpAdapter(routes: routes);
    client = PeopleJoinClient(dio: fakeDio(adapter));
  }

  test('says who invited the person and what the server is called', () async {
    serve({
      '/people/join/Code123/info': (_) => const FakeResponse.json({
            'valid': true,
            'inviter': 'owner',
            'server': 'Our music',
            'address': 'https://music.example',
            'expiresAt': 1792000000,
          }),
    });

    final info = (await client.info(link)).valueOrNull!;

    expect(info.inviter, 'owner');
    expect(info.serverName, 'Our music');
    expect(info.address, Uri.parse('https://music.example'));
  });

  test('an invitation that is used up or old says so, in the server\'s words',
      () async {
    serve({
      '/people/join/Code123/info': (_) =>
          const FakeResponse.json({'valid': false}, status: 404),
    });

    final failure = (await client.info(link)).failureOrNull!;

    expect(failure, isA<NotFoundFailure>());
    expect(failure.message, contains('not valid any more'));
    expect(failure.message, contains('Ask whoever sent it'));
  });

  test('makes the account with the name and password, in the body only',
      () async {
    serve({
      '/people/join/Code123/redeem': (_) => const FakeResponse.json(
          {'username': 'mia', 'address': 'https://music.example'},
          status: 201),
    });

    final joined = (await client.redeem(link,
            username: 'mia', password: 'a long password'))
        .valueOrNull!;

    expect(joined.username, 'mia');
    expect(joined.address, Uri.parse('https://music.example'));
    final sent = adapter.requests.single;
    expect(sent.method, 'POST');
    expect(jsonDecode(sent.body),
        {'username': 'mia', 'password': 'a long password'});
    expect(sent.uri.hasQuery, isFalse,
        reason: 'a password is never put in an address');
  });

  test('a name that is taken is told as the server says it', () async {
    serve({
      '/people/join/Code123/redeem': (_) => const FakeResponse.json(
          {'error': 'Somebody on this server already has that name.'},
          status: 400),
    });

    final failure = (await client.redeem(link,
            username: 'mia', password: 'a long password'))
        .failureOrNull!;

    expect(failure, isA<ServerFailure>());
    expect(failure.message, 'Somebody on this server already has that name.');
  });

  test('too many tries are told as a wait, not as a broken server', () async {
    serve({
      '/people/join/Code123/redeem': (_) => const FakeResponse.json(
          {'error': 'Too many tries. Wait a minute and try again.'},
          status: 429),
    });

    final failure = (await client.redeem(link,
            username: 'mia', password: 'a long password'))
        .failureOrNull!;

    expect(failure.message, contains('Wait a minute'));
    expect(failure.isRetryable, isFalse,
        reason: 'the person decides when to try again');
  });

  test('without a network it says it cannot reach the server', () async {
    serve({
      '/people/join/Code123/info': (_) => const FakeResponse.connectionError(),
    });

    final failure = (await client.info(link)).failureOrNull!;

    expect(failure, isA<NetworkFailure>());
    expect(failure.message, contains('music.example'));
  });

  test('a password never goes over plain http to an address on the internet',
      () async {
    serve({});
    final unsafe =
        InviteLink(server: Uri.parse('http://music.example'), code: 'Code123');

    final result =
        await client.redeem(unsafe, username: 'mia', password: 'a long one');

    expect(result.isErr, isTrue);
    expect(adapter.requests, isEmpty);
  });

  group('on an Encore server (the invitation is on its own API, same address)',
      () {
    final encore = findInviteLink(
        'Come and listen: http://192.168.50.133:4540/encore/join/ABCD-EFGH-JKLM')!;

    test('the link is read, and its calls go to the own API of the server', () {
      expect(encore.encore, isTrue);
      expect(encore.server, Uri.parse('http://192.168.50.133:4540'));
      expect(encore.code, 'ABCD-EFGH-JKLM');
      expect(encore.infoUrl.path, '/encore/api/v1/invites/check');
      expect(encore.infoUrl.queryParameters, {'code': 'ABCD-EFGH-JKLM'});
      expect(encore.redeemUrl.path, '/encore/api/v1/auth/join');
    });

    test('says who invited the person and what the server is called', () async {
      serve({
        '/encore/api/v1/invites/check': (r) {
          expect(r.uri.queryParameters['code'], 'ABCD-EFGH-JKLM');
          return const FakeResponse.json(
              {'invitedBy': 'marwa', 'expiresAt': 1792000000000});
        },
        '/encore/api/v1/info': (_) => const FakeResponse.json(
            {'name': 'Home music', 'apiVersion': '1.0'}),
      });

      final info = (await client.info(encore)).valueOrNull!;

      expect(info.inviter, 'marwa');
      expect(info.serverName, 'Home music');
    });

    test('an invitation that is used up says so in the words of the server',
        () async {
      serve({
        '/encore/api/v1/invites/check': (_) => const FakeResponse.json({
              'error': {
                'code': 'not_found',
                'message': 'This invitation is not valid any more.'
              }
            }, status: 404),
      });

      final failure = (await client.info(encore)).failureOrNull!;

      expect(failure, isA<NotFoundFailure>());
      expect(failure.message, 'This invitation is not valid any more.');
    });

    test('makes the account: the code, the name and the password in the body',
        () async {
      late String body;
      serve({
        '/encore/api/v1/auth/join': (r) {
          body = r.body;
          return const FakeResponse.json({
            'deviceToken': 'x',
            'device': {'id': 'dv_1', 'name': 'Phone'},
            'person': {'id': 'pn_1', 'name': 'mia', 'role': 'member'},
          }, status: 201);
        },
      });

      final joined = (await client.redeem(encore,
              username: 'mia', password: 'a long password'))
          .valueOrNull!;

      expect(joined.username, 'mia');
      final sent = jsonDecode(body) as Map;
      expect(sent['code'], 'ABCD-EFGH-JKLM');
      expect(sent['username'], 'mia');
      expect(sent['password'], 'a long password');
      expect(adapter.requests.single.uri.query, isNot(contains('password')),
          reason: 'never in an address');
    });

    test('a name that is taken is said in the words of the server', () async {
      serve({
        '/encore/api/v1/auth/join': (_) => const FakeResponse.json({
              'error': {
                'code': 'conflict',
                'message': 'That name is already taken. Choose another.'
              }
            }, status: 409),
      });

      final failure = (await client.redeem(encore,
              username: 'mia', password: 'a long password'))
          .failureOrNull!;

      expect(failure.message, 'That name is already taken. Choose another.');
    });
  });
}
