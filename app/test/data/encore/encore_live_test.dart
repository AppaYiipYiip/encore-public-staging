import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:encore/data/auth/credential_store.dart';
import 'package:encore/data/encore/encore_api.dart';
import 'package:encore/data/encore/encore_device.dart';
import 'package:encore/data/encore/encore_live.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_encore_server.dart';

/// A server's end of the live channel, driven by the test.
class _Socket implements LiveSocket {
  final StreamController<String> _in = StreamController();
  final List<Map<String, dynamic>> sent = [];
  int? code;
  bool closed = false;

  @override
  Stream<String> get messages => _in.stream;

  @override
  void send(String text) => sent.add(jsonDecode(text) as Map<String, dynamic>);

  @override
  int? get closeCode => code;

  @override
  Future<void> close() async {
    closed = true;
    if (!_in.isClosed) await _in.close();
  }

  void push(Map<String, Object?> event) => _in.add(jsonEncode(event));

  /// The server ends the connection (with the code it chose, if any).
  void serverCloses([int? withCode]) {
    code = withCode;
    unawaited(_in.close());
  }
}

class _Manual implements Timer {
  _Manual(this.delay, this.cb);
  final Duration delay;
  final void Function() cb;
  bool cancelled = false;

  void fire() {
    if (!cancelled) cb();
  }

  @override
  void cancel() => cancelled = true;
  @override
  bool get isActive => !cancelled;
  @override
  int get tick => 0;
}

Future<void> until(bool Function() ok, {String? what}) async {
  final end = DateTime.now().add(const Duration(seconds: 5));
  while (!ok()) {
    if (DateTime.now().isAfter(end)) {
      fail('timed out waiting for ${what ?? 'it'}');
    }
    await Future<void>.delayed(const Duration(milliseconds: 2));
  }
}

void main() {
  late List<_Socket> offered; // sockets the next connections will get, in order
  late List<Uri> opened;
  late List<Duration> waits;
  late List<_Manual> timers;
  late int tokenAsked;
  late int refused;
  String? token;
  late EncoreLive live;

  setUp(() {
    offered = [];
    opened = [];
    waits = [];
    timers = [];
    tokenAsked = 0;
    refused = 0;
    token = 'ed_abc';
    live = EncoreLive(
      baseUrl: () => Uri.parse('http://home.test:4540'),
      deviceToken: () async {
        tokenAsked++;
        return token;
      },
      tokenRefused: () async => refused++,
      open: (uri) async {
        opened.add(uri);
        if (offered.isEmpty) throw const SocketException('no server');
        return offered.removeAt(0);
      },
      sleep: (d) {
        waits.add(d);
        return Future<void>.delayed(const Duration(milliseconds: 1));
      },
      timerFactory: (d, cb) {
        final t = _Manual(d, cb);
        timers.add(t);
        return t;
      },
    );
  });

  tearDown(() => live.dispose());

  test('the socket address is the server address with ws or wss and the path',
      () {
    expect(
        EncoreLive.socketUri(Uri.parse('http://192.168.1.20:4540')).toString(),
        'ws://192.168.1.20:4540/encore/live');
    expect(
        EncoreLive.socketUri(Uri.parse('https://music.example.ts.net'))
            .toString(),
        'wss://music.example.ts.net/encore/live');
    expect(
        EncoreLive.socketUri(Uri.parse('https://example.org/tunnel/'))
            .toString(),
        'wss://example.org/tunnel/encore/live',
        reason: 'a path in front of the server is kept');
  });

  test('it signs in with the device token and is connected after hello',
      () async {
    final socket = _Socket();
    offered.add(socket);
    final events = <String>[];
    final states = <bool>[];
    live.events.listen((e) => events.add(e.type));
    live.connection.listen(states.add);

    live.start();
    await until(() => socket.sent.isNotEmpty, what: 'the auth message');

    expect(socket.sent.single, {'type': 'auth', 'token': 'ed_abc'});
    expect(opened.single.toString(), 'ws://home.test:4540/encore/live');
    expect(live.isConnected, isFalse,
        reason: 'not before the server says hello');

    socket.push({'type': 'hello', 'cursor': '12'});
    await until(() => live.isConnected, what: 'hello');
    socket.push({'type': 'ping'});
    socket.push({'type': 'library.changed', 'cursor': '13'});
    await until(() => events.contains('library.changed'));

    expect(events, ['hello', 'library.changed'],
        reason: 'pings only keep the connection alive');
    expect(states, [true]);
  });

  test(
      'a dropped connection is reopened with a growing pause that starts over '
      'after a connection that worked', () async {
    final first = _Socket();
    final second = _Socket();
    final third = _Socket();
    final fourth = _Socket();
    offered.addAll([first, second, third, fourth]);
    live.start();

    // 1 and 2 close without ever saying hello: the pause grows.
    await until(() => opened.length == 1);
    first.serverCloses();
    await until(() => opened.length == 2);
    second.serverCloses();
    await until(() => opened.length == 3);
    expect(waits, hasLength(2));
    expect(waits[0].inMilliseconds, inInclusiveRange(600, 1000));
    expect(waits[1].inMilliseconds, inInclusiveRange(1200, 2000));

    // 3 works, then closes: the next pause is the short one again.
    third.push({'type': 'hello'});
    await until(() => live.isConnected);
    third.serverCloses();
    await until(() => opened.length == 4);
    expect(waits, hasLength(3));
    expect(waits[2].inMilliseconds, inInclusiveRange(600, 1000));
    expect(live.isConnected, isFalse);
  });

  test('the pause never grows past 30 seconds', () async {
    live.start();
    await until(() => waits.length >= 8, what: 'eight failed attempts');
    expect(waits.map((w) => w.inMilliseconds).reduce((a, b) => a > b ? a : b),
        lessThanOrEqualTo(30000));
    expect(waits.last.inMilliseconds, inInclusiveRange(18000, 30000));
  });

  test('a refused device token is forgotten and asked for again', () async {
    final socket = _Socket();
    offered.add(socket);
    live.start();
    await until(() => opened.length == 1);

    socket.serverCloses(4401);
    await until(() => refused == 1, what: 'the token to be dropped');
    await until(() => tokenAsked >= 2, what: 'a new token to be asked for');
  });

  test('with no device sign-in no connection is opened', () async {
    token = null;
    live.start();
    await until(() => tokenAsked >= 2, what: 'a retry');

    expect(opened, isEmpty);
  });

  test('a connection that goes silent is dropped and opened again', () async {
    final first = _Socket();
    final second = _Socket();
    offered.addAll([first, second]);
    live.start();
    await until(() => opened.length == 1);
    first.push({'type': 'hello'});
    await until(() => live.isConnected);

    // The silence timer that was set after the last message.
    final silence =
        timers.lastWhere((t) => !t.cancelled && t.delay == live.silenceLimit);
    silence.fire();

    await until(() => first.closed, what: 'the silent socket to be closed');
    await until(() => opened.length == 2, what: 'a new connection');
    expect(live.isConnected, isFalse);
  });

  test('stop closes the connection and nothing is opened afterwards', () async {
    final socket = _Socket();
    offered.add(socket);
    live.start();
    await until(() => opened.length == 1);
    socket.push({'type': 'hello'});
    await until(() => live.isConnected);

    await live.stop();
    expect(socket.closed, isTrue);
    expect(live.isConnected, isFalse);

    await Future<void>.delayed(const Duration(milliseconds: 30));
    expect(opened, hasLength(1));
  });

  group('the device sign-in', () {
    late FakeEncoreServer server;
    late InMemoryCredentialStore store;
    late EncoreApi api;
    late EncoreDevice device;

    setUp(() {
      server = FakeEncoreServer();
      store = InMemoryCredentialStore();
      api = EncoreApi(
        dio: Dio()..httpClientAdapter = server.adapter,
        baseUrl: () => Uri.parse('http://home.test:4540'),
        auth: () => {'u': 'tester', 't': 'tok', 's': 'salt'},
      );
      device = EncoreDevice(
          api: api,
          store: store,
          serverId: 7,
          username: 'tester',
          password: 'pw');
    });

    test('signs in once, keeps the token, and tells the api which device it is',
        () async {
      expect(await device.token(), 'ed_fake1');
      expect(api.deviceId, 'dv_1');

      // A second start of the app: the saved token is used, no new device is made.
      api.deviceId = null;
      expect(await device.token(), 'ed_fake1');
      expect(server.logins, 1);
      expect(api.deviceId, 'dv_1');
    });

    test('forgetting the token makes the next one a new sign-in', () async {
      await device.token();
      await device.forget();

      expect(api.deviceId, isNull);
      expect(await device.token(), 'ed_fake2');
      expect(server.logins, 2);
    });

    test('a server that refuses the sign-in gives no token and keeps nothing',
        () async {
      server.failLogin = true;

      expect(await device.token(), isNull);
      expect(await store.readSecret('encore.device.7'), isNull);
    });

    test('the token lives in the secure store, not anywhere else', () async {
      await device.token();

      final saved = jsonDecode((await store.readSecret('encore.device.7'))!)
          as Map<String, dynamic>;
      expect(saved['token'], 'ed_fake1');
      expect(saved['id'], 'dv_1');
    });
  });
}
