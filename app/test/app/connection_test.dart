import 'dart:async';

import 'package:encore/app/connection.dart';
import 'package:encore/app/providers.dart';
import 'package:encore/features/jam/jam_providers.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';

/// "A widget to show you lost the internet, etc." (the owner, 2026-10-17): what
/// the person is told about the connection, and when. A blink is not news; a
/// few seconds is.
class _Jam extends JamController {
  @override
  JamSession build() => const JamSession();

  void set(JamSession s) => state = s;
}

void main() {
  late StreamController<NetworkKind> network;
  late StreamController<bool> reachable;
  late ProviderContainer container;

  ProviderContainer open({Duration grace = const Duration(milliseconds: 30)}) {
    network = StreamController<NetworkKind>.broadcast();
    reachable = StreamController<bool>.broadcast();
    final overrides = <Override>[
      connectionGraceProvider.overrideWithValue(grace),
      networkKindProvider.overrideWith((ref) async* {
        yield NetworkKind.wifi;
        yield* network.stream;
      }),
      serverReachableProvider.overrideWith((ref) async* {
        yield true;
        yield* reachable.stream;
      }),
      jamControllerProvider.overrideWith(_Jam.new),
    ];
    container = ProviderContainer(overrides: overrides);
    addTearDown(() async {
      container.dispose();
      await network.close();
      await reachable.close();
    });
    container.listen(connectionProblemProvider, (_, __) {});
    return container;
  }

  ConnectionProblem problem() => container.read(connectionProblemProvider);

  Future<void> wait([int ms = 80]) =>
      Future<void>.delayed(Duration(milliseconds: ms));

  test('nothing is said while everything works', () async {
    open();
    await wait();

    expect(problem(), ConnectionProblem.none);
  });

  test('losing the internet is said after a few seconds, not at once',
      () async {
    open(grace: const Duration(milliseconds: 100));
    await wait(20);

    network.add(NetworkKind.none);
    await wait(30);
    expect(problem(), ConnectionProblem.none, reason: 'it may be a blink');

    await wait(120);
    expect(problem(), ConnectionProblem.offline);
  });

  test('a blink shorter than that shows nothing at all', () async {
    open(grace: const Duration(milliseconds: 100));
    await wait(20);

    network.add(NetworkKind.none);
    await wait(30);
    network.add(NetworkKind.wifi);
    await wait(200);

    expect(problem(), ConnectionProblem.none);
  });

  test('it goes away at once when the internet is back', () async {
    open();
    await wait(20);
    network.add(NetworkKind.none);
    await wait(80);
    expect(problem(), ConnectionProblem.offline);

    network.add(NetworkKind.mobile);
    await wait(10);

    expect(problem(), ConnectionProblem.none);
  });

  test('online but the server does not answer is another sentence', () async {
    open();
    await wait(20);

    reachable.add(false);
    await wait(80);

    expect(problem(), ConnectionProblem.serverUnreachable);
  });

  test('a Jam that lost its connection says it is reconnecting', () async {
    open();
    await wait(20);

    (container.read(jamControllerProvider.notifier) as _Jam)
        .set(const JamSession(phase: JamPhase.active, reconnecting: true));
    await wait(80);

    expect(problem(), ConnectionProblem.jamReconnecting);
  });

  test('no internet comes before the rest: it is the reason for them',
      () async {
    open();
    await wait(20);
    (container.read(jamControllerProvider.notifier) as _Jam)
        .set(const JamSession(phase: JamPhase.active, reconnecting: true));
    reachable.add(false);
    network.add(NetworkKind.none);
    await wait(80);

    expect(problem(), ConnectionProblem.offline);
  });

  test('a person who has no server yet is told nothing about one', () async {
    open();
    await wait(20);

    // Nothing is configured: the reachability stream says "fine".
    expect(problem(), ConnectionProblem.none);
  });
}
