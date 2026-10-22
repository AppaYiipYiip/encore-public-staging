import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

/// A tapped invitation (a link in a message) must be offered to Encore on both kinds of server, and nothing else of the web may be:
/// the people service's `/people/join/` and an Encore server's `/encore/join/`, the second also over plain http for a home network.
void main() {
  final manifest =
      File('android/app/src/main/AndroidManifest.xml').readAsStringSync();

  /// The `<intent-filter>` blocks that open a link (VIEW), as text.
  final filters = RegExp(r'<intent-filter>[\s\S]*?</intent-filter>')
      .allMatches(manifest)
      .map((m) => m.group(0)!)
      .where((f) => f.contains('android.intent.action.VIEW'))
      .toList();

  test(
      'Flutter does not route the link itself: the app reads it (found on a '
      'device: "Page Not Found" over the join screen)', () {
    expect(
        manifest,
        matches(RegExp(r'android:name="flutter_deeplinking_enabled"\s+'
            r'android:value="false"')));
  });

  test('there are link filters, and each one is browsable', () {
    expect(filters, isNotEmpty);
    for (final f in filters) {
      expect(f, contains('android.intent.category.BROWSABLE'));
    }
  });

  test('https invitations of both servers open Encore', () {
    final https = filters.where((f) => f.contains('android:scheme="https"'));
    expect(https, hasLength(1));
    expect(https.single, contains('android:pathPrefix="/people/join/"'));
    expect(https.single, contains('android:pathPrefix="/encore/join/"'));
  });

  test('an invitation on a home network (http) opens Encore, only that path',
      () {
    final http = filters.where((f) => f.contains('android:scheme="http"'));
    expect(http, hasLength(1));
    expect(http.single, contains('android:pathPrefix="/encore/join/"'));
    expect(RegExp('android:pathPrefix=').allMatches(http.single), hasLength(1),
        reason: 'no other http link may be offered to Encore');
    expect(http.single, isNot(contains('android:pathPattern')));
  });
}
