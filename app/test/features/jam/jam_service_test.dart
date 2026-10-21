import 'package:encore/features/jam/jam_providers.dart';
import 'package:flutter_test/flutter_test.dart';

/// Where the app looks for the Jam hub (ADR-095): behind the public address under
/// `/hub` (the Funnel has one door), or on its own port on the home network.
void main() {
  test('behind an https address: that address with /hub', () {
    final list =
        jamServiceCandidates([Uri.parse('https://music.example.ts.net')]);

    expect(list.map((u) => u.toString()), ['https://music.example.ts.net/hub']);
  });

  test('on the home network: the hub\'s own port', () {
    final list =
        jamServiceCandidates([Uri.parse('http://192.168.50.132:4533')]);

    expect(list.map((u) => u.toString()), ['http://192.168.50.132:8703']);
  });

  test('home and away together: both, and the public door first', () {
    final list = jamServiceCandidates([
      Uri.parse('http://192.168.50.132:4533'),
      Uri.parse('https://music.example.ts.net'),
    ]);

    expect(list.map((u) => u.toString()), [
      'https://music.example.ts.net/hub',
      'http://192.168.50.132:8703',
    ]);
  });

  test('an address with a path of its own keeps it', () {
    final list =
        jamServiceCandidates([Uri.parse('https://example.org/music/')]);

    expect(list.single.toString(), 'https://example.org/music/hub');
  });

  test('the same address twice is asked once', () {
    final list = jamServiceCandidates([
      Uri.parse('https://music.example.ts.net'),
      Uri.parse('https://music.example.ts.net/'),
    ]);

    expect(list, hasLength(1));
  });
}
