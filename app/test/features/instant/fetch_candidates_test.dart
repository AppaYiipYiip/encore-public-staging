import 'package:encore/features/instant/instant_controller.dart';
import 'package:flutter_test/flutter_test.dart';

/// Where the app looks for the instant-play service (ADR-094). At home it is on
/// its own port next to the music server. Away from home the only door is the
/// public https address, which has one port, so the service sits behind it under
/// `/fetch` (Tailscale Funnel serves `/` to the music server, `/people` to the
/// people service and `/fetch` to this one). A friend who was invited has nothing
/// else: without it they get 30-second previews and a "Request" button that goes
/// nowhere.
void main() {
  final home = Uri.parse('http://192.168.50.132:4533');
  final away = Uri.parse('https://music.tail5678.ts.net');

  test('at home: the music server\'s host on the service\'s own port', () {
    expect(fetchServiceCandidates([home]).map((u) => u.toString()),
        ['http://192.168.50.132:8701']);
  });

  test('away: the public address with /fetch behind it, asked first', () {
    final list = fetchServiceCandidates([home, away]).map((u) => u.toString());

    expect(list, contains('https://music.tail5678.ts.net/fetch'));
    expect(list.toList().indexOf('https://music.tail5678.ts.net/fetch'),
        lessThan(list.toList().indexOf('http://music.tail5678.ts.net:8701')),
        reason:
            'the door that exists is tried before the one that usually does not');
  });

  test('a saved address keeps its path and goes first', () {
    final saved = Uri.parse('https://music.tail5678.ts.net/fetch');

    final list = fetchServiceCandidates([home, away], saved: saved);

    expect(list.first.toString(), 'https://music.tail5678.ts.net/fetch');
    expect(list.where((u) => u.toString() == saved.toString()), hasLength(1),
        reason: 'no address twice');
  });

  test('a private host never gets a /fetch path (nothing is served there)', () {
    final list = fetchServiceCandidates([home]).map((u) => u.toString());

    expect(list.any((u) => u.endsWith('/fetch')), isFalse);
  });

  test('a public address with its own path keeps it', () {
    final nested = Uri.parse('https://example.org/music');

    final list = fetchServiceCandidates([nested]).map((u) => u.toString());

    expect(list, contains('https://example.org/music/fetch'));
  });
}
