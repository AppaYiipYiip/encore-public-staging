import 'dart:async';
import 'dart:convert';

import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:drift/native.dart';
import 'package:encore/app/providers.dart';
import 'package:encore/app/server_kind.dart';
import 'package:encore/app/session.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fake_http.dart';

/// P1-17 (AUDIT B-17): which kind of server the phone talks to is ONE answer. It is `detecting` until the phone KNOWS (B-78), and every reader
/// (the screens' words, what is offered, what a tap on a catalogue song does) reads it.
void main() {
  late AppDatabase db;
  late ServerSession session;

  Future<ServerSession> build(
      {Map<String, Object?> capabilities = const {}}) async {
    db = AppDatabase(NativeDatabase.memory());
    final id = await db.into(db.servers).insert(ServersCompanion.insert(
          name: 'Test',
          username: 'tester',
          endpointsJson: '[{"label":"Home","url":"http://home.test:4540"}]',
          capabilitiesJson: Value(jsonEncode(capabilities)),
          createdAtMs: 0,
        ));
    final server = await (db.select(db.servers)..where((s) => s.id.equals(id)))
        .getSingle();
    session = await ServerSession.create(
        verifyAddresses: false,
        db: db,
        server: server,
        password: 'x',
        dio: fakeDio(FakeHttpAdapter(routes: {})
          ..fallback = (_) => const FakeResponse.connectionError()));
    addTearDown(() async {
      await session.dispose();
      await db.close();
    });
    return session;
  }

  ProviderContainer open(Future<ServerSession?> Function() sessionFuture) {
    final c = ProviderContainer(overrides: [
      sessionProvider.overrideWith((ref) => sessionFuture()),
    ]);
    addTearDown(c.dispose);
    c.listen(serverKindProvider, (_, __) {});
    return c;
  }

  test('the session is still being built: not known yet', () {
    final never = Completer<ServerSession?>();
    final c = open(() => never.future);

    expect(c.read(serverKindProvider), ServerKind.detecting);
  });

  test('a session that failed to build is not known either', () async {
    final c = open(() async => throw StateError('no database'));
    await pumpEventQueue();

    expect(c.read(serverKindProvider), ServerKind.detecting);
  });

  test('no server at all: nothing is an Encore server', () async {
    final c = open(() async => null);
    await pumpEventQueue();

    expect(c.read(serverKindProvider), ServerKind.plain);
  });

  test('a server this phone has been moved onto is an Encore server', () async {
    final s = await build(capabilities: {'encore': true});
    final c = open(() async => s);
    await pumpEventQueue();

    expect(c.read(serverKindProvider), ServerKind.encore);
  });

  test(
      'a plain session is `detecting` until the phone finds out, and the provider follows it',
      () async {
    final s = await build();
    final c = open(() async => s);
    await pumpEventQueue();
    expect(c.read(serverKindProvider), ServerKind.detecting,
        reason: 'the first minutes after a sign-in: the old way meanwhile');

    s.detecting.value =
        false; // the server answered "not found": a plain music server
    await pumpEventQueue();

    expect(c.read(serverKindProvider), ServerKind.plain);
  });

  test(
      'while the session is REBUILT (the addresses were edited, the phone was just moved onto an Encore server) the kind of the session it holds is kept: no flicker to "not an Encore server"',
      () async {
    final s = await build(capabilities: {'encore': true});
    var builds = 0;
    final second = Completer<ServerSession?>();
    final c = open(() {
      builds++;
      return builds == 1 ? Future.value(s) : second.future;
    });
    await pumpEventQueue();
    expect(c.read(serverKindProvider), ServerKind.encore);

    c.invalidate(sessionProvider);
    await pumpEventQueue();

    expect(c.read(sessionProvider).isLoading, isTrue,
        reason: 'the session is being rebuilt');
    expect(c.read(serverKindProvider), ServerKind.encore,
        reason:
            'what the screens say does not flip for the moment of a reload');
  });
}
