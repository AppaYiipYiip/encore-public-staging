import 'dart:async';

import 'package:encore/app/connection.dart';
import 'package:encore/app/providers.dart';
import 'package:encore/core/network_validation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';

/// "A widget to show you lost the internet, etc." (the owner, 2026-10-17): what the person is told about the connection, and when. A blink is not
/// news; a few seconds is. Since P1-17 (AUDIT B-17) there is ONE state of "can I reach my server" (`serverReachabilityProvider`), made of three raw
/// facts (the link, what the last look at the server found, Android's own "internet found"); the strip is a presenter over it.
class _Validation implements NetworkValidation {
  bool? answer = true;
  int asked = 0;

  @override
  Future<bool?> validated() async {
    asked++;
    return answer;
  }
}

void main() {
  late StreamController<NetworkKind> network;
  late StreamController<ServerFinding> finding;
  late StreamController<Uri?> another;
  late _Validation validation;
  late ProviderContainer container;

  ProviderContainer open({
    Duration grace = const Duration(milliseconds: 30),
    Duration shownFor = const Duration(seconds: 5),
    Duration recovered = const Duration(milliseconds: 40),
    ServerFinding first = ServerFinding.answering,
  }) {
    network = StreamController<NetworkKind>.broadcast();
    finding = StreamController<ServerFinding>.broadcast();
    another = StreamController<Uri?>.broadcast();
    validation = _Validation();
    final overrides = <Override>[
      connectionGraceProvider.overrideWithValue(grace),
      connectionShownForProvider.overrideWithValue(shownFor),
      connectionRecoveredProvider.overrideWithValue(recovered),
      networkValidationProvider.overrideWithValue(validation),
      networkKindProvider.overrideWith((ref) async* {
        yield NetworkKind.wifi;
        yield* network.stream;
      }),
      serverFindingProvider.overrideWith((ref) async* {
        yield first;
        yield* finding.stream;
      }),
      anotherServerAtProvider.overrideWith((ref) async* {
        yield null;
        yield* another.stream;
      }),
    ];
    container = ProviderContainer(overrides: overrides);
    addTearDown(() async {
      container.dispose();
      await network.close();
      await finding.close();
      await another.close();
    });
    container.listen(serverReachabilityProvider, (_, __) {});
    container.listen(connectionStripProvider, (_, __) {});
    return container;
  }

  ServerReachability reach() => container.read(serverReachabilityProvider);
  ServerReachability? strip() => container.read(connectionStripProvider);

  Future<void> wait([int ms = 80]) =>
      Future<void>.delayed(Duration(milliseconds: ms));

  group('the state', () {
    test('nothing is said while everything works', () async {
      open();
      await wait();

      expect(reach(), ServerReachability.ok);
      expect(strip(), isNull);
    });

    test('a server nobody has looked for yet is not "away": nothing is said',
        () async {
      open(first: ServerFinding.unknown);
      await wait(150);

      expect(reach(), ServerReachability.unknown);
      expect(reach().isAway, isFalse);
      expect(strip(), isNull);
    });

    test(
        'no network is said to the rows and the player AT ONCE (P1-09), not after a few seconds',
        () async {
      open(grace: const Duration(milliseconds: 100));
      await wait(20);

      network.add(NetworkKind.none);
      await wait(10);

      expect(reach(), ServerReachability.noNetwork);
    });

    test('it goes away at once when the network is back', () async {
      open();
      await wait(20);
      network.add(NetworkKind.none);
      await wait(10);
      expect(reach(), ServerReachability.noNetwork);

      network.add(NetworkKind.mobile);
      await wait(10);

      expect(reach().isAway, isFalse);
    });

    test(
        'a server that goes silent is said after the few seconds of a blink, not at once',
        () async {
      open(grace: const Duration(milliseconds: 100));
      await wait(20);

      finding.add(ServerFinding.silent);
      await wait(30);
      expect(reach(), ServerReachability.ok,
          reason: 'it may be a blink: nothing changes before the grace');

      await wait(150);
      expect(reach(), ServerReachability.serverAway);
    });

    test('a blink of the server shorter than that changes nothing at all',
        () async {
      open(grace: const Duration(milliseconds: 100));
      await wait(20);

      finding.add(ServerFinding.silent);
      await wait(30);
      finding.add(ServerFinding.answering);
      await wait(200);

      expect(reach(), ServerReachability.ok);
      expect(validation.asked, 0,
          reason: 'nothing was decided, so nobody asked');
    });

    test('the server is back: the state leaves away at once', () async {
      open();
      await wait(20);
      finding.add(ServerFinding.silent);
      await wait(80);
      expect(reach(), ServerReachability.serverAway);

      finding.add(ServerFinding.answering);
      await wait(10);

      expect(reach(), ServerReachability.ok);
    });

    test(
        'a change of network (the finding forgets what it found) leaves away at once: what was found at the old place says nothing about the new one',
        () async {
      open();
      await wait(20);
      finding.add(ServerFinding.silent);
      await wait(80);
      expect(reach(), ServerReachability.serverAway);

      finding.add(ServerFinding.unknown);
      await wait(10);

      expect(reach(), ServerReachability.unknown);
      expect(reach().isAway, isFalse);
    });

    test(
        'Android is asked when the state decides, never before: a silent server on a network it found no internet on is "no internet"',
        () async {
      open();
      await wait(20);
      validation.answer = false;
      expect(validation.asked, 0);

      finding.add(ServerFinding.silent);
      await wait(80);

      expect(reach(), ServerReachability.noInternet);
      expect(validation.asked, 1);
    });

    test(
        'Android is not asked at all while the server answers: a home Wi-Fi with no line out is fine',
        () async {
      open();
      validation.answer = false;
      await wait(20);
      network.add(NetworkKind.wifi);
      network.add(NetworkKind.mobile);
      await wait(80);

      expect(reach(), ServerReachability.ok);
      expect(validation.asked, 0);
    });

    test(
        'Android finds internet and the server is silent: only the server is away',
        () async {
      open();
      await wait(20);
      validation.answer = true;

      finding.add(ServerFinding.silent);
      await wait(80);

      expect(reach(), ServerReachability.serverAway);
    });

    test('Android cannot say: internet is assumed', () async {
      open();
      await wait(20);
      validation.answer = null;

      finding.add(ServerFinding.silent);
      await wait(80);

      expect(reach(), ServerReachability.serverAway);
    });

    test(
        'while away, the answer is asked again when the network changes (a sign-in page was passed, a mobile network came back with data)',
        () async {
      open();
      await wait(20);
      validation.answer = false;
      finding.add(ServerFinding.silent);
      await wait(80);
      expect(reach(), ServerReachability.noInternet);

      validation.answer = true;
      network.add(NetworkKind.mobile);
      await wait(40);

      expect(reach(), ServerReachability.serverAway);
    });

    test('no network comes before the rest: it is the reason for them',
        () async {
      open();
      await wait(20);
      finding.add(ServerFinding.silent);
      await wait(80);
      expect(reach(), ServerReachability.serverAway);

      network.add(NetworkKind.none);
      await wait(10);

      expect(reach(), ServerReachability.noNetwork);
    });

    test('a person who has no server yet is told nothing about one', () async {
      open(first: ServerFinding.unknown);
      await wait(150);

      expect(reach(), ServerReachability.unknown);
      expect(strip(), isNull);
    });

    group('CN-11, O-6: an address that answers as another server', () {
      final impostor = Uri.parse('http://192.168.1.10:4533');

      test(
          'is the wrong server, not the sentence of a server that does not answer',
          () async {
        open();
        await wait(20);

        another.add(impostor);
        finding.add(ServerFinding.anotherServer);
        await wait(80);

        expect(reach(), ServerReachability.wrongServer);
      });

      test('a server that does not answer, and nobody else, stays that',
          () async {
        open();
        await wait(20);

        finding.add(ServerFinding.silent);
        await wait(80);

        expect(reach(), ServerReachability.serverAway);
      });

      test('no network comes before it: that is the reason', () async {
        open();
        await wait(20);
        another.add(impostor);
        finding.add(ServerFinding.anotherServer);
        await wait(80);

        network.add(NetworkKind.none);
        await wait(20);

        expect(reach(), ServerReachability.noNetwork);
      });

      test('it goes at once when the server is found again', () async {
        open();
        await wait(20);
        another.add(impostor);
        finding.add(ServerFinding.anotherServer);
        await wait(80);
        expect(reach(), ServerReachability.wrongServer);

        another.add(null);
        finding.add(ServerFinding.answering);
        await wait(20);

        expect(reach(), ServerReachability.ok);
      });

      test('it is said once like any outage, and the cross puts it away',
          () async {
        open();
        await wait(20);
        another.add(impostor);
        finding.add(ServerFinding.anotherServer);
        await wait(80);
        expect(strip(), ServerReachability.wrongServer);

        container.read(connectionStripProvider.notifier).dismiss();

        expect(strip(), isNull);
      });
    });
  });

  group(
      'an outage is said once (owner, 2026-10-31: "all day telling me it cannot connect, sure we get it")',
      () {
    test(
        'the strip says no network after the few seconds of a blink of the radio, not at once',
        () async {
      open(grace: const Duration(milliseconds: 100));
      await wait(20);

      network.add(NetworkKind.none);
      await wait(30);
      expect(strip(), isNull, reason: 'it may be a blink');

      await wait(120);
      expect(strip(), ServerReachability.noNetwork);
    });

    test('a blink of the radio shorter than that shows nothing at all',
        () async {
      open(grace: const Duration(milliseconds: 100));
      await wait(20);

      network.add(NetworkKind.none);
      await wait(30);
      network.add(NetworkKind.wifi);
      await wait(200);

      expect(strip(), isNull);
    });

    test('a silent server is on the strip as soon as the state says it',
        () async {
      open();
      await wait(20);

      finding.add(ServerFinding.silent);
      await wait(80);

      expect(strip(), ServerReachability.serverAway,
          reason: 'the state already waited out the blink of the server');
    });

    test('it shows for a few seconds and goes by itself', () async {
      open(shownFor: const Duration(milliseconds: 100));
      await wait(20);

      network.add(NetworkKind.none);
      await wait(70);
      expect(strip(), ServerReachability.noNetwork);

      await wait(150);
      expect(strip(), isNull, reason: 'still offline, and it has said so');
      expect(reach(), ServerReachability.noNetwork,
          reason: 'the lasting state does not go with the strip');
    });

    test(
        'it does not come back while the same outage goes on, whatever the reason is now (the radio is on, there is no data)',
        () async {
      open(shownFor: const Duration(milliseconds: 60));
      await wait(20);
      network.add(NetworkKind.none);
      await wait(150);
      expect(strip(), isNull);

      network.add(NetworkKind.mobile);
      finding.add(ServerFinding.silent);
      await wait(150);

      expect(strip(), isNull);
    });

    test('a new outage, after everything worked again, is said again',
        () async {
      open(shownFor: const Duration(milliseconds: 60));
      await wait(20);
      network.add(NetworkKind.none);
      await wait(150);
      expect(strip(), isNull);

      network.add(NetworkKind.wifi);
      await wait(60);
      network.add(NetworkKind.none);
      await wait(
          60); // after the blink's wait, before it has been shown for 60 ms

      expect(strip(), ServerReachability.noNetwork);
    });

    test('the cross puts it away and keeps it away', () async {
      open();
      await wait(20);
      network.add(NetworkKind.none);
      await wait(80);
      expect(strip(), ServerReachability.noNetwork);

      container.read(connectionStripProvider.notifier).dismiss();
      expect(strip(), isNull);
      network.add(NetworkKind.mobile);
      finding.add(ServerFinding.silent);
      await wait(120);

      expect(strip(), isNull);
    });
  });
}
