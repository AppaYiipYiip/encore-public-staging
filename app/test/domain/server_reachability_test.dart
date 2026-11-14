import 'package:encore/domain/server_reachability.dart';
import 'package:flutter_test/flutter_test.dart';

/// P1-17 (AUDIT B-17): the ONE judgement of "can I reach my server", from three raw facts. Every reader in the app (the strip, the grey rows, the
/// player, the settings pages) reads this and nothing else, so every row of this table is a state the whole app agrees on (`docs/31` CN-1, CN-4b).
void main() {
  ServerReachability judge(ServerFinding finding,
          {bool network = true, bool? internet}) =>
      reachabilityOf(
          hasNetwork: network, finding: finding, internetFound: internet);

  group('no network at all', () {
    test('is no network whatever the last look at the server found', () {
      for (final finding in ServerFinding.values) {
        expect(judge(finding, network: false), ServerReachability.noNetwork,
            reason: '$finding');
      }
    });
  });

  group('with a network', () {
    test('a server nobody has looked for yet is not known: nothing is said',
        () {
      expect(judge(ServerFinding.unknown), ServerReachability.unknown);
      expect(judge(ServerFinding.unknown, internet: false),
          ServerReachability.unknown,
          reason: 'not looked yet, so there is nothing to be offline from');
    });

    test('a server that answers is ok', () {
      expect(judge(ServerFinding.answering), ServerReachability.ok);
    });

    test(
        'a server that answers is ok even when Android found no internet: a home Wi-Fi without a line out still reaches the home server',
        () {
      expect(judge(ServerFinding.answering, internet: false),
          ServerReachability.ok);
    });

    test('a silent server and internet found: only the server is away', () {
      expect(judge(ServerFinding.silent, internet: true),
          ServerReachability.serverAway);
    });

    test(
        'a silent server and Android found no internet (4G with no data, a sign-in page): the person is offline',
        () {
      expect(judge(ServerFinding.silent, internet: false),
          ServerReachability.noInternet);
    });

    test('a silent server and Android cannot say: internet is assumed', () {
      expect(judge(ServerFinding.silent), ServerReachability.serverAway);
    });

    test(
        'another server answering is the wrong server, whatever Android says: the phone is online, something answers, it is not the one',
        () {
      expect(
          judge(ServerFinding.anotherServer), ServerReachability.wrongServer);
      expect(judge(ServerFinding.anotherServer, internet: false),
          ServerReachability.wrongServer);
    });
  });

  group('what the readers take from the state', () {
    test(
        'away means no network, no internet, the server silent, or somebody else answering',
        () {
      expect([
        for (final r in ServerReachability.values)
          if (r.isAway) r
      ], [
        ServerReachability.noNetwork,
        ServerReachability.noInternet,
        ServerReachability.serverAway,
        ServerReachability.wrongServer,
      ]);
    });

    test('offline is no network or no internet, and nothing else', () {
      expect([
        for (final r in ServerReachability.values)
          if (r.isOffline) r
      ], [
        ServerReachability.noNetwork,
        ServerReachability.noInternet,
      ]);
    });

    test('not looked yet and ok are never away: nothing is greyed', () {
      expect(ServerReachability.unknown.isAway, isFalse);
      expect(ServerReachability.ok.isAway, isFalse);
    });
  });
}
