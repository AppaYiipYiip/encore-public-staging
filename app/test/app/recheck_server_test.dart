import 'dart:async';

import 'package:drift/native.dart';
import 'package:encore/app/connection.dart';
import 'package:encore/app/providers.dart';
import 'package:encore/app/session.dart';
import 'package:encore/core/network_validation.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/sync/server_identity.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fake_http.dart';
import '../support/fake_identity_probe.dart';

class _Validation implements NetworkValidation {
  bool? answer = true;

  @override
  Future<bool?> validated() async => answer;
}

/// The player's ONE fresh look (`recheckServer`, P1-17): what it answers, when it must not look at all, and that the look also tells the state.
void main() {
  late AppDatabase db;
  late ServerSession session;
  late FakeHttpAdapter adapter;
  late _Validation validation;
  late FakeIdentityProbe addresses;

  Future<ProviderContainer> open({
    NetworkKind network = NetworkKind.wifi,
    bool withSession = true,
  }) async {
    validation = _Validation();
    db = AppDatabase(NativeDatabase.memory());
    await db.into(db.servers).insert(ServersCompanion.insert(
          name: 'Test',
          username: 'tester',
          endpointsJson: '[{"label":"Home","url":"http://home.test:4540"}]',
          createdAtMs: 0,
        ));
    adapter = FakeHttpAdapter(routes: {})
      ..fallback = (_) => const FakeResponse.connectionError();
    addresses = FakeIdentityProbe();
    session = await ServerSession.create(
      identityProbe: addresses,
      db: db,
      server: (await db.select(db.servers).get()).single,
      password: 'x',
      dio: fakeDio(adapter),
    );
    final c = ProviderContainer(overrides: [
      connectionGraceProvider.overrideWithValue(Duration.zero),
      networkKindProvider.overrideWith((ref) => Stream.value(network)),
      networkValidationProvider.overrideWithValue(validation),
      sessionProvider.overrideWith((ref) async => withSession ? session : null),
    ]);
    addTearDown(() async {
      c.dispose();
      await session.dispose();
      await db.close();
    });
    c.listen(serverReachabilityProvider, (_, __) {});
    c.listen(sessionProvider, (_, __) {});
    await c.read(sessionProvider.future);
    await pumpEventQueue(times: 20);
    return c;
  }

  Future<ServerReachability> recheck(ProviderContainer c) =>
      c.read(Provider((ref) => recheckServer(ref)));

  test('the server answers: ok, and the look is what the state follows',
      () async {
    final c = await open();
    expect(session.endpoints.finding, ServerFinding.unknown);

    expect(await recheck(c), ServerReachability.ok);
    await pumpEventQueue(times: 20);

    expect(session.endpoints.finding, ServerFinding.answering);
    expect(c.read(serverReachabilityProvider), ServerReachability.ok);
  });

  test(
      'the server is silent and Android found internet: only the server is away, and the state follows after its blink filter',
      () async {
    final c = await open();
    expect(await recheck(c), ServerReachability.ok);
    addresses.verdict = EndpointVerdict.unreachable;

    expect(await recheck(c), ServerReachability.serverAway);
    await pumpEventQueue(times: 20);
    await Future<void>.delayed(const Duration(milliseconds: 30));

    expect(c.read(serverReachabilityProvider), ServerReachability.serverAway,
        reason:
            'the look told the state: the finding it changed is what the state is made of');
  });

  test('the server is silent and Android found no internet: no internet',
      () async {
    final c = await open();
    validation.answer = false;
    addresses.verdict = EndpointVerdict.unreachable;

    expect(await recheck(c), ServerReachability.noInternet);
  });

  test('no network: answered at once and no address is asked', () async {
    final c = await open(network: NetworkKind.none);
    final asked = addresses.asked.length;

    expect(await recheck(c), ServerReachability.noNetwork);

    expect(addresses.asked.length, asked, reason: 'nothing was looked at');
    expect(session.endpoints.finding, ServerFinding.unknown);
  });

  test('no server at all: nothing to look at, so it is not away', () async {
    final c = await open(withSession: false);

    final answer = await recheck(c);

    expect(answer, ServerReachability.unknown);
    expect(answer.isAway, isFalse);
  });

  test('it is the immediate judgement: the answer does not wait out a blink',
      () async {
    final c = await open();
    expect(await recheck(c), ServerReachability.ok);
    addresses.verdict = EndpointVerdict.unreachable;

    final answer = await recheck(c);

    expect(answer, ServerReachability.serverAway,
        reason:
            'a fresh look that found nobody is conclusive for the tap that asked; the state itself may still be ok for a few seconds');
  });
}
