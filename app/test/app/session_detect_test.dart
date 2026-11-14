import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:drift/native.dart';
import 'package:encore/app/session.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fake_subsonic_server.dart';

/// What the address answers when the phone asks "is this an Encore server?" (`GET /encore/api/v1/info`).
typedef _InfoAnswer = Future<ResponseBody> Function(RequestOptions options);

class _Door implements HttpClientAdapter {
  _Door(this.music, this.info);

  final FakeSubsonicServer music;
  _InfoAnswer info;
  int infoAsked = 0;

  @override
  Future<ResponseBody> fetch(RequestOptions options,
      Stream<Uint8List>? requestStream, Future<void>? cancelFuture) {
    if (options.uri.path == '/encore/api/v1/info') {
      infoAsked++;
      return info(options);
    }
    return music.adapter.fetch(options, requestStream, cancelFuture);
  }

  @override
  void close({bool force = false}) {}
}

ResponseBody _json(int status, Object body) =>
    ResponseBody.fromString(jsonEncode(body), status, headers: {
      Headers.contentTypeHeader: ['application/json'],
    });

/// AUDIT B-78: "which kind of server is this?" is a question the phone may only close with a DEFINITE answer. A gateway's 503 while the Encore
/// server restarts, a 429 or a refused login says nothing about the kind: taking it for "a plain music server" released the D-24 guard ("a tap
/// waits instead of playing something else") and synced the old way until the next look, which comes 2 minutes later and then doubles.
void main() {
  late AppDatabase db;
  late _Door door;
  late ServerSession session;

  Future<void> signIn(_InfoAnswer info) async {
    db = AppDatabase(NativeDatabase.memory());
    final id = await db.into(db.servers).insert(ServersCompanion.insert(
          name: 'Home',
          username: 'tester',
          endpointsJson: '[{"label":"Home","url":"http://home.test:4540"}]',
          createdAtMs: 0,
        ));
    final server = await (db.select(db.servers)..where((s) => s.id.equals(id)))
        .getSingle();
    door = _Door(FakeSubsonicServer()..seed(songCount: 3, albumCount: 1), info);
    session = await ServerSession.create(
        verifyAddresses: false,
        db: db,
        server: server,
        password: 'hunter2-hunter2',
        dio: Dio()..httpClientAdapter = door);
  }

  tearDown(() async {
    await session.dispose();
    await db.close();
  });

  /// Starts the session and waits until the first look at the address has been answered.
  Future<void> firstLook() async {
    await session.start();
    for (var i = 0; i < 200 && door.infoAsked == 0; i++) {
      await Future<void>.delayed(const Duration(milliseconds: 10));
    }
    // The answer is handled a moment after it arrives.
    await Future<void>.delayed(const Duration(milliseconds: 100));
    expect(door.infoAsked, greaterThan(0));
  }

  final unknown = <String, _InfoAnswer>{
    'a gateway says 503 while the server restarts': (_) async =>
        ResponseBody.fromString('Service Unavailable', 503, headers: {
          Headers.contentTypeHeader: ['text/plain'],
        }),
    'the address answers 429 (too many looks)': (_) async => _json(429, {
          'error': {'code': 'rate_limited', 'message': 'Slow down'}
        }),
    'the answer is a refusal in the Encore error shape (401)': (_) async =>
        _json(401, {
          'error': {'code': 'unauthorized', 'message': 'Sign in again.'}
        }),
    'nothing answers at all': (options) async =>
        throw DioException.connectionError(
            requestOptions: options, reason: 'connection refused'),
  };

  for (final entry in unknown.entries) {
    test('${entry.key}: the phone does not know the kind yet, and keeps asking',
        () async {
      await signIn(entry.value);

      await firstLook();

      expect(session.detecting.value, isTrue,
          reason:
              'only a definite answer closes it: a tap still waits instead of playing the wrong way');
    });
  }

  final plain = <String, _InfoAnswer>{
    'the server says "not found" (404 with the Encore error shape)':
        (_) async => _json(404, {
              'error': {'code': 'not_found'}
            }),
    'a bare 404': (_) async =>
        ResponseBody.fromString('404 page not found', 404, headers: {
          Headers.contentTypeHeader: ['text/plain'],
        }),
    'a web page where the answer should be (a music server that serves its own page for every address)':
        (_) async => ResponseBody.fromString(
                '<html><body>Navidrome</body></html>', 200,
                headers: {
                  Headers.contentTypeHeader: ['text/html'],
                }),
  };

  for (final entry in plain.entries) {
    test('${entry.key}: it is a plain music server, and the phone knows',
        () async {
      await signIn(entry.value);

      await firstLook();

      expect(session.detecting.value, isFalse);
    });
  }
}
