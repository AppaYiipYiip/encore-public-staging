import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:encore/data/sync/server_identity.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_http.dart';
import '../../support/signing_identity.dart';

// A vector made by the real server (`server/encore_server/encore_server/identity.py`) from the private key `bytes(range(1, 33))`: the two
// implementations must agree on the id, the message and the signature, or no phone could ever verify any server.
const _serverId = 'mw3am46w5weex4a4fqrc3avnua';
const _publicKey = 'ebVWLo_mVPlAeLES6KmLp5AfhTrmlb7X4OORC60ElmQ';
const _nonce = 'test-nonce-0123456789abcdef';
const _signature =
    '6w18cE-CIfP1IoMZF4IM_PtyrTWiF9TD-BXhzgxLWYGLxIGZe28K5hF20GX-NEz-R3yM7__1YXvjdd-gzCU7Aw';

ServerIdentityProbe _probe(FakeHttpAdapter adapter) =>
    ServerIdentityProbe(dioFactory: () => Dio()..httpClientAdapter = adapter);

FakeHttpAdapter _serverThatSigns(SigningIdentity signer, {String? claimId}) =>
    FakeHttpAdapter(routes: {
      '/encore/api/v1/info': (r) async => FakeResponse.json(
          await signer.answer(r.param('challenge')!, claimId: claimId)),
    });

void main() {
  group('the check the phone makes of an answer', () {
    test('the id is made from the public key exactly as the server makes it',
        () {
      expect(serverIdForKey(base64Url.decode(base64Url.normalize(_publicKey))),
          _serverId);
    });

    test('an answer the real server signed verifies', () async {
      expect(
        await verifyServerAnswer(
            serverId: _serverId,
            publicKey: _publicKey,
            nonce: _nonce,
            signature: _signature),
        isTrue,
      );
    });

    test(
        'Dart signs the same bytes the server signed (Ed25519 is deterministic)',
        () async {
      final who = await SigningIdentity(1).identity();
      final answer = await SigningIdentity(1).answer(_nonce);

      expect(who.id, _serverId);
      expect(answer['signature'], _signature);
    });

    test('a signature for another challenge does not verify', () async {
      expect(
        await verifyServerAnswer(
            serverId: _serverId,
            publicKey: _publicKey,
            nonce: 'another-nonce-0123456789',
            signature: _signature),
        isFalse,
      );
    });

    test('a copied id with the copier\'s own key does not verify', () async {
      final impostor = SigningIdentity(100);
      final answer = await impostor.answer(_nonce, claimId: _serverId);

      expect(
        await verifyServerAnswer(
            serverId: _serverId,
            publicKey: answer['publicKey']! as String,
            nonce: _nonce,
            signature: answer['signature']! as String),
        isFalse,
        reason: 'the key does not hash to the id it claims',
      );
    });

    test('the real public key with somebody else\'s signature does not verify',
        () async {
      final answer =
          await SigningIdentity(100).answer(_nonce, claimId: _serverId);

      expect(
        await verifyServerAnswer(
            serverId: _serverId,
            publicKey: _publicKey,
            nonce: _nonce,
            signature: answer['signature']! as String),
        isFalse,
      );
    });

    test('garbage is simply no', () async {
      for (final junk in ['', 'not base64 !!', 'AAAA', 'x' * 200]) {
        expect(
            await verifyServerAnswer(
                serverId: _serverId,
                publicKey: junk,
                nonce: _nonce,
                signature: _signature),
            isFalse,
            reason: 'key "$junk"');
        expect(
            await verifyServerAnswer(
                serverId: _serverId,
                publicKey: _publicKey,
                nonce: _nonce,
                signature: junk),
            isFalse,
            reason: 'signature "$junk"');
      }
    });
  });

  group('asking an address who it is', () {
    test('a server that signs my challenge is verified, and I learn its id',
        () async {
      final adapter = _serverThatSigns(SigningIdentity(1));

      final proof =
          await _probe(adapter).check(Uri.parse('http://home.test:4540'));

      expect(proof.verdict, EndpointVerdict.verified);
      expect(proof.serverId, _serverId);
    });

    test(
        'the question carries a fresh challenge and nothing else: no login, no token',
        () async {
      final adapter = _serverThatSigns(SigningIdentity(1));

      await _probe(adapter).check(Uri.parse('http://home.test:4540'));
      await _probe(adapter).check(Uri.parse('http://home.test:4540'));

      final asked = adapter.requests;
      expect(asked, hasLength(2));
      for (final request in asked) {
        expect(request.uri.path, '/encore/api/v1/info');
        expect(request.uri.queryParameters.keys, ['challenge']);
        expect(request.headers.keys.where((k) => k.contains('auth')), isEmpty);
        expect(request.body, isEmpty);
      }
      expect(asked[0].param('challenge'), isNot(asked[1].param('challenge')),
          reason: 'a recorded answer is useless the second time');
      expect(asked[0].param('challenge')!.length, greaterThanOrEqualTo(16));
    });

    test('an address behind a path is asked under that path', () async {
      final adapter = FakeHttpAdapter(routes: {
        '/front/encore/api/v1/info': (r) async => FakeResponse.json(
            await SigningIdentity(1).answer(r.param('challenge')!)),
      });

      final proof =
          await _probe(adapter).check(Uri.parse('https://home.test/front/'));

      expect(proof.verdict, EndpointVerdict.verified);
    });

    test('with the id this phone has pinned, the same server is verified',
        () async {
      final proof = await _probe(_serverThatSigns(SigningIdentity(1)))
          .check(Uri.parse('http://home.test:4540'), expectedId: _serverId);

      expect(proof.verdict, EndpointVerdict.verified);
    });

    test(
        'a different server at the same address is the wrong key, not an error',
        () async {
      final proof = await _probe(_serverThatSigns(SigningIdentity(100)))
          .check(Uri.parse('http://home.test:4540'), expectedId: _serverId);

      expect(proof.verdict, EndpointVerdict.wrongKey);
      expect(proof.usable, isFalse);
    });

    test(
        'an impostor that copies the id and signs with its own key is the wrong key',
        () async {
      final proof = await _probe(
              _serverThatSigns(SigningIdentity(100), claimId: _serverId))
          .check(Uri.parse('http://home.test:4540'), expectedId: _serverId);

      expect(proof.verdict, EndpointVerdict.wrongKey);
    });

    test('an answer that is signed but not for my challenge is the wrong key',
        () async {
      final adapter = FakeHttpAdapter(routes: {
        '/encore/api/v1/info': (r) async => FakeResponse.json(
            await SigningIdentity(1).answer('an-old-recorded-challenge-0123')),
      });

      final proof =
          await _probe(adapter).check(Uri.parse('http://home.test:4540'));

      expect(proof.verdict, EndpointVerdict.wrongKey);
    });

    test('a server whose key I have pinned cannot downgrade to having none',
        () async {
      final adapter = FakeHttpAdapter(routes: {
        '/encore/api/v1/info': (r) => const FakeResponse.json(
            {'apiVersion': '1.0', 'name': 'Looks fine'}),
      });

      final proof = await _probe(adapter)
          .check(Uri.parse('http://home.test:4540'), expectedId: _serverId);

      expect(proof.verdict, EndpointVerdict.wrongKey);
    });

    test('an older Encore server with no key is legacy when nothing is pinned',
        () async {
      final adapter = FakeHttpAdapter(routes: {
        '/encore/api/v1/info': (r) =>
            const FakeResponse.json({'apiVersion': '1.0', 'name': 'Old'}),
      });

      final proof =
          await _probe(adapter).check(Uri.parse('http://home.test:4540'));

      expect(proof.verdict, EndpointVerdict.legacy);
      expect(proof.usable, isTrue);
    });

    test('a plain music server is recognised without sending it any login',
        () async {
      final adapter = FakeHttpAdapter(routes: {
        '/encore/api/v1/info': (r) =>
            const FakeResponse.json({'message': 'not found'}, status: 404),
        'ping.view': (r) => const FakeResponse.json({
              'subsonic-response': {
                'status': 'failed',
                'type': 'navidrome',
                'error': {'code': 10, 'message': "missing parameter: 'u'"}
              }
            }),
      });

      final proof =
          await _probe(adapter).check(Uri.parse('http://home.test:4533'));

      expect(proof.verdict, EndpointVerdict.legacy);
      for (final request in adapter.requests) {
        expect(
            request.uri.queryParameters.keys
                .toSet()
                .intersection({'u', 't', 's', 'p'}),
            isEmpty,
            reason: 'no credential of any kind');
      }
    });

    test('something that answers and is no server is unreachable', () async {
      final adapter = FakeHttpAdapter(routes: {
        '/encore/api/v1/info': (r) =>
            const FakeResponse.json('<html>hello</html>'),
        'ping.view': (r) => const FakeResponse.json('<html>hello</html>'),
      });

      final proof =
          await _probe(adapter).check(Uri.parse('http://router.test'));

      expect(proof.verdict, EndpointVerdict.unreachable);
    });

    test('nothing answering is unreachable', () async {
      final adapter = FakeHttpAdapter(routes: {
        '/encore/api/v1/info': (r) => const FakeResponse.connectionError(),
      });

      final proof =
          await _probe(adapter).check(Uri.parse('http://gone.test:4540'));

      expect(proof.verdict, EndpointVerdict.unreachable);
    });
  });
}
