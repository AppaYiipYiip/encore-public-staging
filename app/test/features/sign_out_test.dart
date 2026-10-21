import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:encore/app/providers.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/features/requests/request_providers.dart';
import 'package:encore/features/settings/sign_out.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../support/test_app.dart';

/// Signing out (ADR-068): the phone forgets the account, the server keeps
/// everything, and the app is back at the first screen.
void main() {
  setUpAll(loadAppFonts);
  setUp(() => SharedPreferences.setMockInitialValues({
        'encore.requestPortal': 'http://192.168.50.113:8700',
        'encore.requestPortalUser': 'marwa',
        'encore.fetchService': 'http://192.168.50.129:8701',
        'encore.privateListening': true,
      }));

  Future<void> openSettings(WidgetTester tester) async {
    final element = tester.element(find.byType(Scaffold).first);
    GoRouter.of(element).go('/settings');
    await settle(tester);
    await tester.scrollUntilVisible(find.text('Sign out'), 200,
        scrollable: find.byType(Scrollable).first);
    await settle(tester);
  }

  testWidgets('asks first, in words that say what stays and what goes',
      (tester) async {
    final app = await pumpApp(tester, size: const Size(390, 1400), overrides: [
      coverCacheClearerProvider.overrideWithValue(() async {}),
    ]);
    await openSettings(tester);

    await tester.tap(find.text('Sign out'));
    await settle(tester);

    expect(find.text('Sign out of Home server?'), findsOneWidget);
    expect(find.textContaining('Your music and playlists stay on your server'),
        findsOneWidget);
    expect(find.textContaining('removes its copy of your library'),
        findsOneWidget);
    expect(find.textContaining('sign in again any time'), findsOneWidget);
    // No downloads: nothing is said about them.
    expect(find.textContaining('downloaded for offline'), findsNothing);
    // Nothing waiting: nothing is said about unsent changes either.
    expect(find.textContaining('not reached your server'), findsNothing);

    await tester.tap(find.text('Cancel'));
    await settle(tester);
    expect(await app.db.select(app.db.servers).get(), hasLength(1));
    expect(app.facade.calls, isNot(contains('stopAndClear')));
    await closeApp(tester, app.db);
  });

  testWidgets('the dialog says how much offline music will be deleted',
      (tester) async {
    final app = await pumpApp(tester, size: const Size(390, 1400), overrides: [
      coverCacheClearerProvider.overrideWithValue(() async {}),
    ]);
    await app.db.into(app.db.downloads).insert(DownloadsCompanion.insert(
          serverId: app.serverId,
          trackId: 'al1-t1',
          state: const Value(2),
          localPath: const Value('/x/al1-t1.opus'),
          bytes: const Value(5 * 1024 * 1024),
          updatedAtMs: 0,
        ));
    await openSettings(tester);

    await tester.tap(find.text('Sign out'));
    await settle(tester);
    expect(
        find.textContaining('The 5.0 MB of music you downloaded for '
            'offline listening is deleted from this phone'),
        findsOneWidget);
    await tester.tap(find.text('Cancel'));
    await settle(tester);
    await closeApp(tester, app.db);
  });

  testWidgets('the dialog warns about changes that have not reached the server',
      (tester) async {
    final app = await pumpApp(tester, size: const Size(390, 1400), overrides: [
      coverCacheClearerProvider.overrideWithValue(() async {}),
    ]);
    // Two waiting and one the server turned down: all three are lost on sign-out.
    for (final status in const ['pending', 'pending', 'failed']) {
      await app.db.into(app.db.outbox).insert(OutboxCompanion.insert(
            serverId: app.serverId,
            kind: 'star',
            payloadJson: '{"songIds":["al1-t1"]}',
            createdAtMs: 0,
            status: Value(status),
          ));
    }
    await openSettings(tester);

    await tester.tap(find.text('Sign out'));
    await settle(tester);

    expect(find.textContaining('3 changes have not reached your server yet'),
        findsOneWidget,
        reason: 'signing out would silently throw them away (B31)');
    await tester.tap(find.text('Cancel'));
    await settle(tester);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'signing out forgets the account and returns to the first '
      'screen', (tester) async {
    final app = await pumpApp(tester, size: const Size(390, 1400), overrides: [
      coverCacheClearerProvider.overrideWithValue(() async {}),
    ]);
    final container =
        ProviderScope.containerOf(tester.element(find.byType(Scaffold).first));
    final credentials = container.read(credentialStoreProvider);
    await credentials.writePassword(app.serverId, 'secret');
    await credentials.writeSecret(kPortalPasswordKey, 'portal-secret');
    await app.db.into(app.db.pins).insert(PinsCompanion.insert(
          serverId: app.serverId,
          targetType: 'album',
          targetId: 'al1',
          createdAtMs: 0,
        ));
    await openSettings(tester);

    await tester.tap(find.text('Sign out'));
    await settle(tester);
    await tester.tap(find.widgetWithText(FilledButton, 'Sign out'));
    await tester.runAsync(
        () => Future<void>.delayed(const Duration(milliseconds: 100)));
    await settle(tester);
    await settle(tester);

    // The phone has forgotten everything about the account...
    expect(await app.db.select(app.db.servers).get(), isEmpty);
    expect(await app.db.select(app.db.tracks).get(), isEmpty);
    expect(await app.db.select(app.db.pins).get(), isEmpty);
    expect(await credentials.readPassword(app.serverId), isNull);
    expect(await credentials.readSecret(kPortalPasswordKey), isNull);
    expect(app.facade.calls, contains('stopAndClear'));
    final prefs = await SharedPreferences.getInstance();
    for (final key in const [
      'encore.requestPortal',
      'encore.requestPortalUser',
      'encore.fetchService',
      'encore.privateListening',
    ]) {
      expect(prefs.containsKey(key), isFalse, reason: key);
    }
    // ...and the app is at the sign-in screen.
    expect(find.text('Connect'), findsWidgets);
    expect(find.text('Sign out'), findsNothing);
    await closeApp(tester, app.db);
  });
}
