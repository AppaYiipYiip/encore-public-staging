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
}
