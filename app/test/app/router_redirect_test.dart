import 'package:encore/app/router.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

/// Where the app opens. Field test 2026-10-31: after a glimpse of public Wi-Fi the app opened on the page that asks for a server, as if it
/// had forgotten the one it was signed in to; after a restart it opened normally. The page is for a phone with no saved server, and nothing
/// else: a database that did not answer is not "no server".
void main() {
  const server = ServerRow(
      id: 1,
      name: 'Home',
      username: 'u',
      endpointsJson: '[]',
      capabilitiesJson: '{}',
      createdAtMs: 0,
      lastUsedAtMs: 0);

  String? go(AsyncValue<ServerRow?> saved, String location,
          {bool invite = false}) =>
      redirectFor(server: saved, location: location, hasInviteLink: invite);

  test('a phone with a saved server stays on Home and leaves the sign-in page',
      () {
    expect(go(const AsyncData(server), '/home'), isNull);
    expect(go(const AsyncData(server), '/onboarding'), '/home');
  });

  test('a phone with no saved server goes to the page that asks for one', () {
    expect(go(const AsyncData(null), '/home'), '/onboarding');
    expect(go(const AsyncData(null), '/onboarding'), isNull);
  });

  test('while the saved server is being read nothing moves', () {
    expect(go(const AsyncLoading(), '/home'), isNull);
  });

  test(
      'a database that did not answer is not "no saved server": the phone does not go to the sign-in page',
      () {
    final failed = AsyncError<ServerRow?>(StateError('busy'), StackTrace.empty);

    expect(go(failed, '/home'), isNull);
    expect(go(failed, '/profiles'), isNull);
  });
}
