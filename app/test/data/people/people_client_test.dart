import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:encore/core/result.dart';
import 'package:encore/data/people/people_client.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_http.dart';

/// The client of the server's people service (docs/35): invitations and friend
/// activity. Every request carries the music server's own token (never the
/// password), and only what the design allows ever leaves the phone.
void main() {
  late FakeHttpAdapter adapter;

  Dio dio() => Dio(BaseOptions(validateStatus: (_) => true))
    ..httpClientAdapter = adapter;

  PeopleClient at(String base) => PeopleClient(
        baseUrl: Uri.parse(base),
        auth: () => {'u': 'sara', 't': 'tok', 's': 'salt'},
        dio: dio(),
      );

  late PeopleClient client;

  FakeResponse ok(Object body, {int status = 200}) =>
      FakeResponse.json(body, status: status);

  setUp(() {
    adapter = FakeHttpAdapter();
    client = at('https://music.example.ts.net');
  });

  RecordedRequest last() => adapter.requests.last;

  group('is the people service there?', () {
    test('asks without any login', () async {
      adapter.routes['/people/api/info'] = (_) => ok({
            'service': 'encore-people',
            'version': 1,
            'features': ['invites', 'activity'],
          });

      final found = await PeopleClient.probe(
          Uri.parse('https://music.example.ts.net'),
          dio: dio());

      expect(found, isTrue);
      expect(last().uri.path, '/people/api/info');
      expect(last().uri.query, isEmpty, reason: 'no token goes to a stranger');
    });

    test('keeps a path the music server lives under', () async {
      adapter.routes['/music/people/api/info'] =
          (_) => ok({'service': 'encore-people', 'version': 1});

      expect(
          await PeopleClient.probe(Uri.parse('https://host.example/music/'),
              dio: dio()),
          isTrue);
    });

    test('nothing else counts as the service', () async {
      Future<bool> probe() =>
          PeopleClient.probe(Uri.parse('https://music.example.ts.net'),
              dio: dio());

      adapter.routes['/people/api/info'] = (_) => ok('not found', status: 404);
      expect(await probe(), isFalse);

      adapter.routes['/people/api/info'] =
          (_) => ok('bad gateway', status: 502);
      expect(await probe(), isFalse);

      adapter.routes['/people/api/info'] = (_) => ok('<html>Navidrome</html>');
      expect(await probe(), isFalse);

      adapter.routes['/people/api/info'] =
          (_) => ok({'service': 'encore-fetch'});
      expect(await probe(), isFalse,
          reason: 'another companion is not this one');

      adapter.routes['/people/api/info'] =
          (_) => const FakeResponse.connectionError();
      expect(await probe(), isFalse);
    });
  });

  group('the login only travels over a safe address (docs/23, B25)', () {
    test('a public address without https gets nothing', () async {
      final unsafe = at('http://music.example.org');

      final me = await unsafe.me();
      final friends = await unsafe.friends();
      final shared = await unsafe.setSharing(true);

      for (final r in [
        me.failureOrNull,
        friends.failureOrNull,
        shared.failureOrNull
      ]) {
        expect(r, isNotNull);
        expect(r!.message, contains('https://'));
      }
      expect(adapter.requests, isEmpty,
          reason: 'the token is a replayable credential');
    });

    test('a home address over http is fine', () async {
      adapter.routes['/people/api/me'] =
          (_) => ok({'user': 'sara', 'admin': false, 'sharing': false});

      expect((await at('http://192.168.50.132:8702').me()).isOk, isTrue);
    });

    test('the token and salt are sent, the password is not', () async {
      adapter.routes['/people/api/me'] =
          (_) => ok({'user': 'sara', 'admin': false, 'sharing': false});

      await client.me();

      expect(
          last().uri.queryParameters, {'u': 'sara', 't': 'tok', 's': 'salt'});
      expect(last().uri.host, 'music.example.ts.net');
      expect(last().uri.path, '/people/api/me');
    });
  });

  group('me', () {
    test('says who I am, whether I administer the server, and my choice',
        () async {
      adapter.routes['/people/api/me'] = (_) => ok(
          {'user': 'owner', 'admin': true, 'canInvite': true, 'sharing': true});

      final me = (await client.me()).valueOrNull!;

      expect(me.user, 'owner');
      expect(me.isAdmin, isTrue);
      expect(me.canInvite, isTrue);
      expect(me.sharing, isTrue);
    });

    test(
        'a person the operator named may invite without being an administrator',
        () async {
      adapter.routes['/people/api/me'] = (_) => ok({
            'user': 'owner',
            'admin': false,
            'canInvite': true,
            'sharing': false
          });

      final me = (await client.me()).valueOrNull!;

      expect(me.isAdmin, isFalse);
      expect(me.canInvite, isTrue);
    });

    test('an older service does not say: an administrator may invite',
        () async {
      adapter.routes['/people/api/me'] =
          (_) => ok({'user': 'owner', 'admin': true, 'sharing': false});

      expect((await client.me()).valueOrNull!.canInvite, isTrue);

      adapter.routes['/people/api/me'] =
          (_) => ok({'user': 'sara', 'admin': false, 'sharing': false});

      expect((await client.me()).valueOrNull!.canInvite, isFalse);
    });
  });

  group('friend activity', () {
    test('reads what others share', () async {
      adapter.routes['/people/api/activity'] = (_) => ok({
            'friends': [
              {
                'user': 'ben',
                'title': 'Dogs',
                'artist': 'Pink Floyd',
                'album': 'Animals',
                'coverUrl': 'https://cdn.example/c.jpg',
                'state': 'playing',
                'since': 1760000000.0,
              },
              {
                'user': 'tom',
                'title': 'Sheep',
                'artist': 'Pink Floyd',
                'album': '',
                'coverUrl': null,
                'state': 'paused',
                'since': 1759999000,
              },
            ],
          });

      final friends = (await client.friends()).valueOrNull!;

      expect(friends.map((f) => f.user), ['ben', 'tom']);
      expect(friends.first.title, 'Dogs');
      expect(friends.first.album, 'Animals');
      expect(friends.first.isPlaying, isTrue);
      expect(friends.first.coverUrl, 'https://cdn.example/c.jpg');
      expect(friends.first.startedAt,
          DateTime.fromMillisecondsSinceEpoch(1760000000 * 1000));
      expect(friends.last.isPlaying, isFalse);
      expect(friends.last.coverUrl, isNull);
    });

    test('an entry the app cannot read is skipped, not a crash', () async {
      adapter.routes['/people/api/activity'] = (_) => ok({
            'friends': [
              {'user': 'ben', 'title': 'Dogs', 'artist': 'x', 'since': 1.0},
              {'nonsense': true},
              'text',
            ],
          });

      final friends = (await client.friends()).valueOrNull!;

      expect(friends.map((f) => f.user), ['ben']);
    });

    test('only title, artist, album, cover and state are ever sent', () async {
      adapter.routes['/people/api/activity'] = (_) => ok('', status: 204);

      final result = await client.report(const NowPlayingReport(
        title: 'Dogs',
        artist: 'Pink Floyd',
        album: 'Animals',
        coverUrl: 'https://cdn.example/c.jpg',
        playing: true,
      ));

      expect(result.isOk, isTrue);
      expect(last().method, 'PUT');
      final sent = jsonDecode(last().body) as Map<String, dynamic>;
      expect(
          sent.keys.toSet(), {'title', 'artist', 'album', 'coverUrl', 'state'},
          reason: 'no song id, no path, nothing that points into a library');
      expect(sent['state'], 'playing');
    });

    test('a paused song is reported as paused; a missing cover is left out',
        () async {
      adapter.routes['/people/api/activity'] = (_) => ok('', status: 204);

      await client.report(const NowPlayingReport(
          title: 'Dogs', artist: 'Pink Floyd', playing: false));

      final sent = jsonDecode(last().body) as Map<String, dynamic>;
      expect(sent['state'], 'paused');
      expect(sent.containsKey('coverUrl'), isFalse);
    });

    test('a cover address that carries a login is never sent', () async {
      adapter.routes['/people/api/activity'] = (_) => ok('', status: 204);

      for (final cover in [
        'https://music.example.ts.net/rest/getCoverArt?id=1&u=sara&t=abc&s=xyz',
        'https://music.example.ts.net/rest/getCoverArt?id=1&u=sara&p=secret',
        'https://cdn.example/c.jpg?token=abc',
        'https://sara:secret@cdn.example/c.jpg',
        'not an address',
        'file:///sdcard/c.jpg',
      ]) {
        await client.report(NowPlayingReport(
            title: 'Dogs',
            artist: 'Pink Floyd',
            coverUrl: cover,
            playing: true));

        final sent = jsonDecode(last().body) as Map<String, dynamic>;
        expect(sent.containsKey('coverUrl'), isFalse, reason: cover);
      }
    });

    test('clear sends DELETE', () async {
      adapter.routes['/people/api/activity'] = (_) => ok('', status: 204);
      expect((await client.clear()).isOk, isTrue);
      expect(last().method, 'DELETE');
    });

    test('sharing is switched with a plain on/off', () async {
      adapter.routes['/people/api/activity/sharing'] =
          (_) => ok('', status: 204);

      await client.setSharing(true);

      expect(last().method, 'PUT');
      expect(jsonDecode(last().body), {'on': true});
    });
  });

  group('roles (ADR-092)', () {
    test('me says which role I have and what that lets me do', () async {
      adapter.routes['/people/api/me'] = (_) => ok({
            'user': 'kim',
            'admin': false,
            'role': 'inviter',
            'canInvite': true,
            'canManage': false,
            'sharing': false,
          });

      final me = (await client.me()).valueOrNull!;

      expect(me.role, PersonRole.inviter);
      expect(me.canInvite, isTrue);
      expect(me.canManage, isFalse);
    });

    test('an older service that sends no role: who may invite is an owner',
        () async {
      adapter.routes['/people/api/me'] = (_) => ok({
            'user': 'owner',
            'admin': true,
            'canInvite': true,
            'sharing': false
          });
      final owner = (await client.me()).valueOrNull!;
      expect((owner.role, owner.canManage), (PersonRole.owner, true));

      adapter.routes['/people/api/me'] = (_) => ok({
            'user': 'sara',
            'admin': false,
            'canInvite': false,
            'sharing': false
          });
      final guest = (await client.me()).valueOrNull!;
      expect((guest.role, guest.canManage), (PersonRole.guest, false));
    });

    test('lists the people with their role, who invited them and when',
        () async {
      adapter.routes['/people/api/people'] = (_) => ok({
            'people': [
              {
                'user': 'owner',
                'role': 'owner',
                'fixed': true,
                'invitedBy': null,
                'joinedAt': null,
              },
              {
                'user': 'ben',
                'role': 'guest',
                'fixed': false,
                'invitedBy': 'kim',
                'joinedAt': 1760000000.0,
              },
              {'nonsense': true},
            ],
          });

      final people = (await client.people()).valueOrNull!;

      expect(people.map((p) => (p.user, p.role, p.isFounding, p.invitedBy)), [
        ('owner', PersonRole.owner, true, null),
        ('ben', PersonRole.guest, false, 'kim'),
      ]);
      expect(people.last.joinedAt,
          DateTime.fromMillisecondsSinceEpoch(1760000000 * 1000));
    });

    test('changes a role with a plain request', () async {
      adapter.routes['/people/api/people/ben'] = (_) => ok('', status: 204);

      final result = await client.setRole('ben', PersonRole.inviter);

      expect(result.isOk, isTrue);
      expect(last().method, 'PUT');
      expect(jsonDecode(last().body), {'role': 'inviter'});
    });

    test('removes a person, whatever characters the name has', () async {
      adapter.routes['/people/api/people/ben.k_1'] = (_) => ok('', status: 204);

      expect((await client.removePerson('ben.k_1')).isOk, isTrue);

      expect(last().method, 'DELETE');
      expect(last().uri.path, '/people/api/people/ben.k_1');
    });

    test('a name can never change where the request goes', () async {
      adapter.routes['/people/api/people/..%2Fme'] = (_) => ok('', status: 204);

      await client.removePerson('../me');

      expect(last().uri.path, isNot('/people/api/me'),
          reason: 'a name with slashes must stay one segment');
      expect(last().uri.path, startsWith('/people/api/people/'));
    });

    test('an invitation says what the invited person becomes', () async {
      adapter.routes['/people/api/invites'] = (_) => ok({
            'id': 9,
            'url': 'https://music.example.ts.net/people/join/xyz',
            'expiresAt': 1760604800.0,
            'role': 'inviter',
          }, status: 201);

      final made =
          (await client.createInvite(role: PersonRole.inviter)).valueOrNull!;

      expect(jsonDecode(last().body), {'role': 'inviter'});
      expect(made.role, PersonRole.inviter);
    });

    test('an invitation made without a choice is for a guest', () async {
      adapter.routes['/people/api/invites'] = (_) => ok({
            'id': 9,
            'url': 'https://music.example.ts.net/people/join/xyz',
            'expiresAt': 1760604800.0,
          }, status: 201);

      final made = (await client.createInvite()).valueOrNull!;

      expect(made.role, PersonRole.guest);
    });

    test('the invitation list says who made each one and for which role',
        () async {
      adapter.routes['/people/api/invites'] = (_) => ok({
            'invites': [
              {
                'id': 2,
                'inviter': 'kim',
                'createdAt': 1.0,
                'expiresAt': 9999999999.0,
                'state': 'open',
                'redeemedBy': null,
                'redeemedAt': null,
                'role': 'guest',
              },
            ],
          });

      final row = (await client.invites()).valueOrNull!.single;

      expect((row.inviter, row.role), ('kim', PersonRole.guest));
    });
  });

  group('invitations (administrator)', () {
    test('makes a link', () async {
      adapter.routes['/people/api/invites'] = (_) => ok({
            'id': 7,
            'url': 'https://music.example.ts.net/people/join/abc',
            'expiresAt': 1760604800.0,
          }, status: 201);

      final made = (await client.createInvite()).valueOrNull!;

      expect(last().method, 'POST');
      expect(made.id, '7');
      expect(made.url, 'https://music.example.ts.net/people/join/abc');
      expect(made.expiresAt,
          DateTime.fromMillisecondsSinceEpoch(1760604800 * 1000));
    });

    test('lists invitations with their state and no code', () async {
      adapter.routes['/people/api/invites'] = (_) => ok({
            'invites': [
              {
                'id': 2,
                'inviter': 'owner',
                'createdAt': 1.0,
                'expiresAt': 2.0,
                'state': 'used',
                'redeemedBy': 'ben',
                'redeemedAt': 1.5,
              },
              {
                'id': 3,
                'inviter': 'owner',
                'createdAt': 1.0,
                'expiresAt': 9999999999.0,
                'state': 'open',
                'redeemedBy': null,
                'redeemedAt': null,
              },
            ],
          });

      final rows = (await client.invites()).valueOrNull!;

      expect(rows.map((r) => (r.id, r.state, r.redeemedBy)),
          [('2', 'used', 'ben'), ('3', 'open', null)]);
      expect(rows.last.isOpen, isTrue);
      expect(rows.first.isOpen, isFalse);
    });

    test('revokes one by id', () async {
      adapter.routes['/people/api/invites/3'] = (_) => ok('', status: 204);

      expect((await client.revokeInvite('3')).isOk, isTrue);

      expect(last().method, 'DELETE');
      expect(last().uri.path, '/people/api/invites/3');
    });
  });

  group('failures say what happened in plain words', () {
    test('401 is a login problem', () async {
      adapter.routes['/people/api/me'] =
          (_) => ok({'error': 'Sign in again.'}, status: 401);

      final failure = (await client.me()).failureOrNull;

      expect(failure, isA<AuthFailure>());
      expect(failure!.message, 'Sign in again.');
    });

    test('a refusal from the server carries its own sentence', () async {
      adapter.routes['/people/api/invites'] = (_) => ok({
            'error': 'Switch on remote access first: an invitation needs the '
                "server's public address.",
          }, status: 409);

      final failure = (await client.createInvite()).failureOrNull;

      expect(failure, isA<ServerFailure>());
      expect(failure!.message, contains('remote access'));
      expect((failure as ServerFailure).statusCode, 409);
    });

    test('403 is not a sign-out: the login is fine, the right is missing',
        () async {
      adapter.routes['/people/api/invites'] = (_) =>
          ok({'error': 'Only an administrator can do that.'}, status: 403);

      final failure = (await client.createInvite()).failureOrNull;

      expect(failure, isA<ServerFailure>());
      expect(failure!.message, 'Only an administrator can do that.');
    });

    test('no route is a network failure, and nothing throws', () async {
      adapter.routes['/people/api/activity'] =
          (_) => const FakeResponse.connectionError();

      expect((await client.friends()).failureOrNull, isA<NetworkFailure>());
      expect((await client.clear()).failureOrNull, isA<NetworkFailure>());
    });

    test('an unreadable answer is a failure, not a crash', () async {
      adapter.routes['/people/api/me'] = (_) => ok('<html>oops</html>');

      expect((await client.me()).isOk, isFalse);
    });
  });
}
