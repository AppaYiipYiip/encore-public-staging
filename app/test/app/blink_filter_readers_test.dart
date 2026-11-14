import 'dart:async';

import 'package:encore/app/connection.dart';
import 'package:encore/app/providers.dart';
import 'package:encore/core/network_validation.dart';
import 'package:encore/features/common/playability.dart';
import 'package:encore/features/providers.dart' show downloadedIdsProvider;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class _Validation implements NetworkValidation {
  @override
  Future<bool?> validated() async => true;
}

/// P1-17, decision D2 (accepted by the lead and the advisor): the blink filter is part of the ONE state, so the player reads it too. For the few
/// seconds after the server goes silent every reader still says "may try"; a tap on a song that is not downloaded is tried and waits (docs/33
/// PB-F7) instead of being refused, and a blink of a second never makes the player refuse and skip. After the filter every reader says away. A
/// FRESH look (`recheckServer`) is newer than the state and is the one thing that may know better (`recheck_server_test.dart`, slice 3).
void main() {
  late StreamController<NetworkKind> network;
  late StreamController<ServerFinding> finding;
  late ProviderContainer container;

  Future<void> wait(int ms) => Future<void>.delayed(Duration(milliseconds: ms));

  ProviderContainer open() {
    network = StreamController<NetworkKind>.broadcast();
    finding = StreamController<ServerFinding>.broadcast();
    container = ProviderContainer(overrides: [
      connectionGraceProvider
          .overrideWithValue(const Duration(milliseconds: 150)),
      connectionShownForProvider.overrideWithValue(const Duration(minutes: 1)),
      networkValidationProvider.overrideWithValue(_Validation()),
      networkKindProvider.overrideWith((ref) async* {
        yield NetworkKind.wifi;
        yield* network.stream;
      }),
      serverFindingProvider.overrideWith((ref) async* {
        yield ServerFinding.answering;
        yield* finding.stream;
      }),
      anotherServerAtProvider.overrideWith((ref) => Stream.value(null)),
      downloadedIdsProvider.overrideWith((ref) => Stream.value({'on-phone'})),
    ]);
    addTearDown(() async {
      container.dispose();
      await network.close();
      await finding.close();
    });
    container.listen(serverReachabilityProvider, (_, __) {});
    container.listen(connectionStripProvider, (_, __) {});
    container.listen(downloadedIdsProvider, (_, __) {});
    return container;
  }

  /// What each reader says now, as one value, so a disagreement shows in one assertion.
  ({
    ServerReachability state,
    bool playable,
    AwayCause? cause,
    ServerReachability? strip,
    bool playerMayTry
  }) readers() => (
        state: container.read(serverReachabilityProvider),
        playable: container.read(playabilityProvider)('not-on-phone'),
        cause: container.read(awayCauseProvider),
        strip: container.read(connectionStripProvider),
        playerMayTry: !container.read(serverReachabilityProvider).isAway,
      );

  test(
      'D2: in the blink filter after the server goes silent every reader still says "may try"; after it, every reader says away',
      () async {
    open();
    await wait(40);

    finding.add(ServerFinding.silent);
    await wait(40); // inside the 150 ms filter

    expect(readers(), (
      state: ServerReachability.ok,
      playable: true,
      cause: null,
      strip: null,
      playerMayTry: true
    ));

    await wait(300); // the filter has run out

    expect(readers(), (
      state: ServerReachability.serverAway,
      playable: false,
      cause: AwayCause.serverSilent,
      strip: ServerReachability.serverAway,
      playerMayTry: false
    ));
  });

  test(
      'a blink shorter than the filter changes nothing for any reader: the player does not refuse and skip for one second of bad signal',
      () async {
    open();
    await wait(40);

    finding.add(ServerFinding.silent);
    await wait(40);
    finding.add(ServerFinding.answering);
    await wait(300);

    expect(readers().state, ServerReachability.ok);
    expect(readers().playerMayTry, isTrue);
    expect(readers().strip, isNull);
  });

  test(
      'no network has no such window: every reader says away at once (P1-09), the strip alone waits out a blink of the radio',
      () async {
    open();
    await wait(40);

    network.add(NetworkKind.none);
    await wait(30);

    final now = readers();
    expect(now.state, ServerReachability.noNetwork);
    expect(now.playable, isFalse);
    expect(now.cause, AwayCause.noInternet);
    expect(now.playerMayTry, isFalse);
    expect(now.strip, isNull,
        reason: 'the strip says it after its own blink wait');
  });
}
