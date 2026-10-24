import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:drift/native.dart';
import 'package:encore/app/session.dart';
import 'package:encore/core/result.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/sync/endpoint_resolver.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fake_subsonic_server.dart';
import '../support/signing_identity.dart';

/// Everything a phone can reach, as the network would behave: the address `home.test` is a server (or an impostor), an address under
/// `.invalid` can never be reached, and every request that arrives is written down.
class _Door implements HttpClientAdapter {
  _Door(this.music, {this.signer, this.claimId});

  final FakeSubsonicServer music;

  /// The key of whatever answers at `home.test`; `null`: a server with no key (an older one, or a plain music server).
  SigningIdentity? signer;

  /// An impostor that says it is somebody else's id.
  String? claimId;

  /// What `GET /encore/api/v1/server` answers (signed in); `null`: not found.
  Map<String, Object?>? serverAnswer;

  final List<RequestOptions> seen = [];

  List<RequestOptions> toHome() =>
      seen.where((r) => r.uri.host == 'home.test').toList();

  ResponseBody _json(Object body, [int status = 200]) =>
      ResponseBody.fromString(jsonEncode(body), status, headers: {
        Headers.contentTypeHeader: ['application/json'],
      });

  @override
  Future<ResponseBody> fetch(RequestOptions options,
      Stream<Uint8List>? requestStream, Future<void>? cancelFuture) async {
    seen.add(options);
    if (options.uri.host.endsWith('.invalid')) {
      throw DioException.connectionError(
          requestOptions: options, reason: 'no such host');
    }
    final path = options.uri.path;
    if (path == '/encore/api/v1/info') {
      final key = signer;
      if (key == null) return _json({'message': 'not found'}, 404);
      return _json(await key.answer(options.uri.queryParameters['challenge']!,
          claimId: claimId));
    }
    if (path == '/encore/api/v1/server') {
      final answer = serverAnswer;
      return answer == null
          ? _json({
              'error': {'code': 'not_found'}
            }, 404)
          : _json(answer);
    }
    if (path == '/rest/ping.view') {
      return _json({
        'subsonic-response': {
          'status': 'failed',
          'type': 'navidrome',
          'error': {'code': 10, 'message': "missing parameter: 'u'"}
        }
      });
    }
    return music.adapter.fetch(options, requestStream, cancelFuture);
  }

  @override
  void close({bool force = false}) {}
}

void main() {
  late AppDatabase db;
  late _Door door;
  late ServerRow server;
  late ServerSession session;
  final real = SigningIdentity(1);
  final other = SigningIdentity(100);

  /// A phone with one saved address, `home.test`, and the server's key pinned or not.
  Future<void> start(
      {String? pinned,
      SigningIdentity? signer,
      String? claimId,
      bool encore = false}) async {
    db = AppDatabase(NativeDatabase.memory());
    final id = await db.into(db.servers).insert(ServersCompanion.insert(
          name: 'Home',
          username: 'tester',
          endpointsJson: '[{"label":"Home","url":"http://home.test:4540"}]',
          capabilitiesJson: Value(jsonEncode({
            if (pinned != null) 'serverId': pinned,
            if (encore) 'encore': true,
          })),
          createdAtMs: 0,
        ));
    server = await (db.select(db.servers)..where((s) => s.id.equals(id)))
        .getSingle();
    door = _Door(FakeSubsonicServer()..seed(songCount: 3, albumCount: 1),
        signer: signer, claimId: claimId);
    session = await ServerSession.create(
        db: db,
        server: server,
        password: 'hunter2-hunter2',
        dio: Dio()..httpClientAdapter = door);
  }

  tearDown(() async {
    await session.dispose();
    await db.close();
  });

  Future<Map<String, Object?>> capabilities() async => (jsonDecode(
          (await (db.select(db.servers)..where((s) => s.id.equals(server.id)))
                  .getSingle())
              .capabilitiesJson) as Map)
      .cast();

  bool carriesACredential(RequestOptions r) =>
      r.headers.keys.any((k) => k.toLowerCase().contains('auth')) ||
      r.uri.queryParameters.keys
          .any((k) => const {'u', 't', 's', 'p'}.contains(k));

  test('before an address has proved itself, a request does not reach it',
      () async {
    await start(pinned: await real.id(), signer: real);

    final result = await session.client.ping();

    expect(result, isA<Err<Object?>>());
    expect(door.toHome().where((r) => r.uri.path != '/encore/api/v1/info'),
        isEmpty,
        reason: 'nothing but the question "who are you?" went to the address');
    expect(session.endpoints.currentUrl, EndpointResolver.unverifiedUrl);
  });

  test(
      'an impostor at the saved address is asked who it is, answers wrongly and is never sent a login, a token or a request',
      () async {
    // The phone knows the server by the key of `real`; at this address now answers `other`, which copies the id.
    await start(
        pinned: await real.id(), signer: other, claimId: await real.id());

    final winner = await session.endpoints.resolve();
    final result = await session.client.ping();

    expect(winner, isNull);
    expect(session.endpoints.isReachable, isFalse);
    expect(session.endpoints.currentUrl, EndpointResolver.unverifiedUrl);
    expect(result, isA<Err<Object?>>());
    final sent = door.toHome();
    expect(sent, isNotEmpty, reason: 'it was asked');
    for (final request in sent) {
      expect(request.uri.path, '/encore/api/v1/info');
      expect(request.uri.queryParameters.keys, ['challenge']);
      expect(carriesACredential(request), isFalse);
      expect('${request.data}', isNot(contains('hunter2')));
    }
  });

  test(
      'a different server with its own honest key at that address is not this server either',
      () async {
    await start(pinned: await real.id(), signer: other);

    expect(await session.endpoints.resolve(), isNull);
    await session.client.ping();

    expect(door.toHome().where((r) => r.uri.path != '/encore/api/v1/info'),
        isEmpty);
  });

  test(
      'a server whose key is pinned cannot get itself accepted by saying it has no key',
      () async {
    await start(pinned: await real.id(), signer: null);

    expect(await session.endpoints.resolve(), isNull);
    expect(session.endpoints.currentUrl, EndpointResolver.unverifiedUrl);
  });

  test(
      'the server that proves its key is used, and only then does the login go to it',
      () async {
    await start(pinned: await real.id(), signer: real);

    final winner = await session.endpoints.resolve();
    final result = await session.client.ping();

    expect(winner, isNotNull);
    expect(session.endpoints.currentUrl.host, 'home.test');
    expect(result, isA<Ok<Object?>>());
    final sent = door.toHome();
    expect(sent.first.uri.path, '/encore/api/v1/info');
    expect(carriesACredential(sent.first), isFalse,
        reason: 'the question that proves the server carries no login');
    final after = sent.where((r) => r.uri.path != '/encore/api/v1/info');
    expect(after, isNotEmpty);
    expect(after.every(carriesACredential), isTrue,
        reason: 'only after the proof does the usual login ride along');
  });

  test(
      'a phone that had no key for the server learns it the first time the server proves one',
      () async {
    await start(pinned: null, signer: real);
    expect((await capabilities()).containsKey('serverId'), isFalse);

    await session.endpoints.resolve();
    await Future<void>.delayed(const Duration(milliseconds: 50));

    expect((await capabilities())['serverId'], await real.id());
  });

  test('once learned, the key is the one that counts', () async {
    await start(pinned: null, signer: real);
    await session.endpoints.resolve();
    await Future<void>.delayed(const Duration(milliseconds: 50));
    expect(session.endpoints.currentUrl.host, 'home.test');

    door.signer = other; // the same address, later, somebody else
    final winner = await session.endpoints.resolve();

    expect(winner, isNull);
    expect(session.endpoints.currentUrl, EndpointResolver.unverifiedUrl);
  });

  test(
      'an older server that has no key at all is used as before when nothing is pinned',
      () async {
    await start(pinned: null, signer: null);

    final winner = await session.endpoints.resolve();
    final result = await session.client.ping();

    expect(winner, isNotNull);
    expect(result, isA<Ok<Object?>>());
    final questions = door.toHome().where((r) =>
        r.uri.path == '/encore/api/v1/info' || r.uri.path == '/rest/ping.view');
    expect(questions.where(carriesACredential), isEmpty,
        reason: 'even a server with no key is recognised without a login');
  });

  test(
      'when the network changes nothing is sent until the address has proved itself again',
      () async {
    await start(pinned: await real.id(), signer: real);
    await session.endpoints.resolve();
    expect(await session.client.ping(), isA<Ok<Object?>>());

    session.endpoints.invalidate(); // Wi-Fi to mobile data, a café, anywhere
    door.seen.clear();
    final during = await session.client.ping();

    expect(during, isA<Err<Object?>>());
    expect(door.toHome(), isEmpty,
        reason: 'not one request went to the old address');
    await session.endpoints.resolve();
    expect(await session.client.ping(), isA<Ok<Object?>>());
  });

  group('the addresses the server tells the phone', () {
    const away = 'https://encore-home.tail1234.ts.net';

    Map<String, Object?> told(String id, List<(String, String)> addresses) => {
          'serverId': id,
          'name': 'Home music',
          'addresses': [
            for (final a in addresses) {'kind': a.$1, 'url': a.$2}
          ],
        };

    Future<void> learnFrom(List<(String, String)> addresses,
        {String? id}) async {
      await start(pinned: await real.id(), signer: real, encore: true);
      door.serverAnswer = told(id ?? await real.id(), addresses);
      await session.endpoints.resolve();
      await session.refreshAddresses();
    }

    test(
        'an address the server names is added as a candidate and remembered, not put in the person\'s own list',
        () async {
      await learnFrom([('home', 'http://192.168.1.50:4540'), ('away', away)]);

      expect(session.endpoints.candidates.map((e) => e.url.toString()),
          contains(away));
      final away1 = session.endpoints.candidates
          .firstWhere((e) => e.url.host == 'encore-home.tail1234.ts.net');
      expect(away1.label, 'Away');
      final row = await (db.select(db.servers)
            ..where((x) => x.id.equals(server.id)))
          .getSingle();
      expect(learnedAddresses(row).map((e) => e.url.host),
          contains('encore-home.tail1234.ts.net'));
      expect(row.endpointsJson, server.endpointsJson,
          reason: 'the list the person typed is left alone');
    });

    test(
        'it is only a candidate: nothing is sent to it before it has proved itself',
        () async {
      await learnFrom([('away', away)]);

      expect(session.endpoints.currentUrl.host,
          isNot('encore-home.tail1234.ts.net'));
      expect(
          door.seen.where((r) => r.uri.host == 'encore-home.tail1234.ts.net'),
          isEmpty);
    });

    test(
        'a plain http address on the internet is not taken, as when it is typed',
        () async {
      await learnFrom([('away', 'http://203.0.113.9:4533')]);

      expect(session.endpoints.candidates.map((e) => e.url.host),
          isNot(contains('203.0.113.9')));
    });

    test(
        'a list that comes with another key than the one this phone knows is ignored',
        () async {
      await learnFrom([('away', away)], id: await other.id());

      expect(session.endpoints.candidates.map((e) => e.url.host),
          isNot(contains('encore-home.tail1234.ts.net')));
    });

    test('what was learned is used the next time the session is built',
        () async {
      await learnFrom([('away', away)]);
      final row = await (db.select(db.servers)
            ..where((x) => x.id.equals(server.id)))
          .getSingle();

      final again = await ServerSession.create(
          db: db,
          server: row,
          password: 'hunter2-hunter2',
          dio: Dio()..httpClientAdapter = door);
      addTearDown(again.dispose);

      expect(again.endpoints.candidates.map((e) => e.url.host),
          contains('encore-home.tail1234.ts.net'));
    });

    test('a server that has nothing to say leaves everything as it was',
        () async {
      await start(pinned: await real.id(), signer: real, encore: true);
      door.serverAnswer = null;
      await session.endpoints.resolve();

      await session.refreshAddresses();

      expect(session.endpoints.candidates, hasLength(1));
    });
  });
}
