import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:drift/native.dart';
import 'package:encore/app/session.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fake_encore_server.dart';
import '../support/fake_subsonic_server.dart';
import '../support/signing_identity.dart';

/// One address behind which an Encore server and its music server answer, the way a real network does: a name under `.invalid` can never
/// be reached, and the server's proof of who it is (`GET /info?challenge=`) takes [identityDelay] to come back.
class _Door implements HttpClientAdapter {
  _Door(this.music, this.encore, this.signer, this.identityDelay);

  final FakeSubsonicServer music;
  final FakeEncoreServer encore;
  final SigningIdentity signer;
  final Duration identityDelay;
  final List<RequestOptions> seen = [];

  @override
  Future<ResponseBody> fetch(RequestOptions options,
      Stream<Uint8List>? requestStream, Future<void>? cancelFuture) async {
    seen.add(options);
    if (options.uri.host.endsWith('.invalid')) {
      throw DioException.connectionError(
          requestOptions: options, reason: 'no such host');
    }
    final path = options.uri.path;
    final challenge = options.uri.queryParameters['challenge'];
    if (path == '/encore/api/v1/info' && challenge != null) {
      await Future<void>.delayed(identityDelay);
      return ResponseBody.fromString(
          jsonEncode(await signer.answer(challenge)), 200,
          headers: {
            Headers.contentTypeHeader: ['application/json'],
          });
    }
    if (path.startsWith('/encore/')) {
      return encore.adapter.fetch(options, requestStream, cancelFuture);
    }
    return music.adapter.fetch(options, requestStream, cancelFuture);
  }

  @override
  void close({bool force = false}) {}
}

/// AUDIT F30 (found in `b10`): on a fresh sign-in the app stayed in the OLD music-server mode for about two minutes, so a person who
/// tapped at once got the old Download. The first look at "is this an Encore server?" came before any address had proved itself, was made
/// to a reserved name that cannot be reached (no request at all), failed, and the next look came two minutes later.
void main() {
  late AppDatabase db;
  late FakeEncoreServer encore;
  late _Door door;
  late ServerRow server;
  late ServerSession session;

  Future<void> signInFresh({
    Duration identityDelay = const Duration(milliseconds: 400),
  }) async {
    db = AppDatabase(NativeDatabase.memory());
    final id = await db.into(db.servers).insert(ServersCompanion.insert(
          name: 'Home',
          username: 'tester',
          endpointsJson: '[{"label":"Home","url":"http://home.test:4540"}]',
          createdAtMs: 0,
        ));
    server = await (db.select(db.servers)..where((s) => s.id.equals(id)))
        .getSingle();
    encore = FakeEncoreServer();
    door = _Door(FakeSubsonicServer()..seed(songCount: 3, albumCount: 1),
        encore, SigningIdentity(1), identityDelay);
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

  Future<void> until(bool Function() done, {int tries = 400}) async {
    for (var i = 0; i < tries && !done(); i++) {
      await Future<void>.delayed(const Duration(milliseconds: 15));
    }
  }

  test(
      'F30: a fresh sign-in moves onto the Encore server within seconds of the address proving itself, not two minutes later',
      () async {
    await signInFresh();

    await session.start();
    await until(() => encore.migrations > 0); // 6 s at most

    expect(encore.migrations, 1,
        reason:
            'the move began: the phone found out it is an Encore server by itself');
  });

  test(
      'F30: the first look at "is this an Encore server?" is made to the address that proved itself, never to the reserved one that cannot be reached',
      () async {
    await signInFresh();

    await session.start();
    await until(() => encore.migrations > 0);

    final looks = door.seen
        .where((r) =>
            r.uri.path == '/encore/api/v1/info' &&
            !r.uri.queryParameters.containsKey('challenge'))
        .toList();
    expect(looks, isNotEmpty);
    expect(looks.first.uri.host, 'home.test');
    expect(looks.where((r) => r.uri.host.endsWith('.invalid')), isEmpty,
        reason:
            'no look at "is this an Encore server?" was sent to the address that cannot be reached');
  });
}
