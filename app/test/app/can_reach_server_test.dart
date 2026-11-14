import 'dart:async';

import 'package:encore/app/connection.dart';
import 'package:encore/app/providers.dart';
import 'package:encore/core/network_validation.dart';
import 'package:encore/features/common/playability.dart';
import 'package:encore/features/providers.dart' show downloadedIdsProvider;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class _Validation implements NetworkValidation {
  _Validation(this.answer);

  final bool? answer;

  @override
  Future<bool?> validated() async => answer;
}

/// The test that fails when two readers disagree (AUDIT B-17): every reader of the ONE state of "can I reach my server", in every state. Field test
/// 2026-10-31 is the row "a network with no internet and a silent server": with the 4G radio on and no data the player believed it was online, waited
/// for the server on the first song that was not downloaded and never reached the downloaded ones behind it ("if one song is missing I can't play any").
void main() {
  Future<ProviderContainer> open({
    required NetworkKind network,
    required ServerFinding finding,
    bool? internet = true,
  }) async {
    final c = ProviderContainer(overrides: [
      connectionGraceProvider.overrideWithValue(Duration.zero),
      connectionShownForProvider.overrideWithValue(const Duration(minutes: 1)),
      networkKindProvider.overrideWith((ref) => Stream.value(network)),
      serverFindingProvider.overrideWith((ref) => Stream.value(finding)),
      networkValidationProvider.overrideWithValue(_Validation(internet)),
      anotherServerAtProvider.overrideWith((ref) => Stream.value(null)),
      downloadedIdsProvider.overrideWith((ref) => Stream.value({'on-phone'})),
    ]);
    addTearDown(c.dispose);
    c.listen(serverReachabilityProvider, (_, __) {});
    c.listen(connectionStripProvider, (_, __) {});
    c.listen(downloadedIdsProvider, (_, __) {});
    // The facts arrive, the blink filter runs out (zero here), Android answers.
    await pumpEventQueue(times: 40);
    await Future<void>.delayed(const Duration(milliseconds: 30));
    return c;
  }

  group('every reader says the same thing in every state (AUDIT B-17)', () {
    // network, finding, Android's answer -> the state, and what each reader must then say.
    final table = <(
      String,
      NetworkKind,
      ServerFinding,
      bool?,
      ServerReachability,
      AwayCause?
    )>[
      (
        'working',
        NetworkKind.wifi,
        ServerFinding.answering,
        true,
        ServerReachability.ok,
        null
      ),
      (
        'not looked yet',
        NetworkKind.wifi,
        ServerFinding.unknown,
        true,
        ServerReachability.unknown,
        null
      ),
      (
        'no network',
        NetworkKind.none,
        ServerFinding.answering,
        true,
        ServerReachability.noNetwork,
        AwayCause.noInternet
      ),
      (
        'a network with no internet and a silent server',
        NetworkKind.mobile,
        ServerFinding.silent,
        false,
        ServerReachability.noInternet,
        AwayCause.noInternet
      ),
      (
        'internet and a silent server',
        NetworkKind.wifi,
        ServerFinding.silent,
        true,
        ServerReachability.serverAway,
        AwayCause.serverSilent
      ),
      (
        'another server answering',
        NetworkKind.wifi,
        ServerFinding.anotherServer,
        true,
        ServerReachability.wrongServer,
        AwayCause.serverSilent
      ),
    ];

    for (final (name, network, finding, internet, state, cause) in table) {
      test(name, () async {
        final c =
            await open(network: network, finding: finding, internet: internet);
        final away = state.isAway;

        expect(c.read(serverReachabilityProvider), state, reason: 'the state');
        expect(c.read(awayCauseProvider), cause,
            reason: 'the words of every page that says why');
        expect(c.read(serverReachabilityProvider).isAway, away,
            reason:
                'the player reads the state itself: it refuses a song that is not downloaded only when this is true (unknown is "may try")');
        expect(c.read(playabilityProvider)('not-on-phone'), !away,
            reason: 'a row of a song that is not downloaded');
        expect(c.read(playabilityProvider)('on-phone'), isTrue,
            reason: 'a downloaded song always plays');
        expect(c.read(connectionStripProvider) != null, away,
            reason: 'the strip says it');
        expect(c.read(connectionStripProvider), away ? state : isNull,
            reason: 'and says the same thing');
      });
    }
  });
}
