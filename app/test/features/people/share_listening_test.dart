import 'package:encore/core/result.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/people/people_client.dart';
import 'package:encore/features/people/people_providers.dart';
import 'package:encore/features/settings/settings_controller.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import '../../support/fake_people_api.dart';
import '../../support/test_app.dart';

/// Settings > Home, library & privacy: "Share what I'm listening to" (docs/35).
/// Off until the person turns it on; shown only when the server has the
/// service; what it shows is what the server holds.
void main() {
  setUpAll(loadAppFonts);

  const tall = Size(390, 2600);
  const title = "Share what I'm listening to";

  Future<void> openSettings(WidgetTester tester) async {
    final element = tester.element(find.byType(Scaffold).first);
    GoRouter.of(element).go('/settings/home');
    await settle(tester);
  }

  ProviderContainer containerOf(WidgetTester tester) =>
      ProviderScope.containerOf(tester.element(find.byType(Scaffold).first));

  Future<({FakePeopleApi api, AppDatabase db})> open(
    WidgetTester tester, {
    FakePeopleApi? api,
    bool service = true,
  }) async {
    final fake = api ?? FakePeopleApi();
    final app = await pumpApp(tester, size: tall, overrides: [
      peopleApiProvider.overrideWith((ref) async => service ? fake : null),
    ]);
    await openSettings(tester);
    return (api: fake, db: app.db);
  }

  testWidgets('is off to begin with, and turning it on tells the server',
      (tester) async {
    final opened = await open(tester);

    final tile = find.widgetWithText(SwitchListTile, title);
    expect(tester.widget<SwitchListTile>(tile).value, isFalse);

    await tester.tap(find.text(title));
    await settle(tester);

    expect(opened.api.sharingCalls, [true]);
    expect(tester.widget<SwitchListTile>(tile).value, isTrue);
    await closeApp(tester, opened.db);
  });

  testWidgets('shows what the server holds', (tester) async {
    final opened = await open(tester,
        api: FakePeopleApi(
            me_: const PeopleMe(user: 'sara', isAdmin: false, sharing: true)));

    expect(
        tester
            .widget<SwitchListTile>(find.widgetWithText(SwitchListTile, title))
            .value,
        isTrue);
    await closeApp(tester, opened.db);
  });

  testWidgets('is not there on a server without the service', (tester) async {
    final opened = await open(tester, service: false);

    expect(find.text(title), findsNothing);
    expect(find.text('Private listening'), findsOneWidget,
        reason: 'the rest of the page is as before');
    await closeApp(tester, opened.db);
  });

  testWidgets(
      'F57: is not offered where the server cannot show it to friends (an Encore server): a switch that does nothing would lie',
      (tester) async {
    final opened =
        await open(tester, api: FakePeopleApi(sharesListening: false));

    expect(find.text(title), findsNothing);
    expect(find.text('Private listening'), findsOneWidget,
        reason: 'the rest of the page is as before');
    await closeApp(tester, opened.db);
  });

  testWidgets('a switch the server did not take goes back, with the reason',
      (tester) async {
    final api = FakePeopleApi()
      ..sharingAnswer = const Result<void>.err(
          NetworkFailure('Cannot reach the people service at music.example'));
    final opened = await open(tester, api: api);

    await tester.tap(find.text(title));
    await settle(tester);

    expect(
        tester
            .widget<SwitchListTile>(find.widgetWithText(SwitchListTile, title))
            .value,
        isFalse);
    expect(
        find.textContaining('Cannot reach the people service'), findsOneWidget);
    await closeApp(tester, opened.db);
  });

  testWidgets('says so when private listening keeps it quiet', (tester) async {
    final opened = await open(tester);

    containerOf(tester)
        .read(settingsProvider.notifier)
        .setPrivateListening(true);
    await settle(tester);

    expect(find.textContaining('nothing is shared right now'), findsOneWidget);
    await closeApp(tester, opened.db);
  });
}
