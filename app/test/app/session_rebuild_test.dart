import 'dart:convert';

import 'package:encore/app/providers.dart' show stableCapabilities;
import 'package:encore/data/db/app_database.dart';
import 'package:flutter_test/flutter_test.dart';

/// A running session is rebuilt when something it depends on changes; what the phone itself writes while the session runs must not do it.
void main() {
  group('what rebuilds a session', () {
    ServerRow row(Map<String, Object?> capabilities) => ServerRow(
          id: 1,
          name: 'Home',
          username: 'tester',
          endpointsJson: '[]',
          capabilitiesJson: jsonEncode(capabilities),
          createdAtMs: 0,
          lastUsedAtMs: 0,
        );

    test('learning the key or the addresses of the server does not', () {
      final before = row({'encore': true});
      final after = row({
        'encore': true,
        'serverId': 'mw3am46w5weex4a4fqrc3avnua',
        'learnedAddresses': [
          {'label': 'Away', 'url': 'https://encore-home.tail1234.ts.net'}
        ],
      });

      expect(stableCapabilities(after), stableCapabilities(before));
    });

    test('learning that it is an Encore server does', () {
      expect(stableCapabilities(row({})),
          isNot(stableCapabilities(row({'encore': true}))));
    });
  });
}
