import 'package:encore/data/db/app_database.dart';
import 'package:encore/domain/storage_guard.dart';
import 'package:encore/features/downloads/download_providers.dart';
import 'package:encore/features/settings/settings_controller.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../support/fake_disk_space.dart';
import '../support/test_app.dart';

void main() {
  setUpAll(loadAppFonts);
  setUp(() => SharedPreferences.setMockInitialValues({}));

  Future<void> open(WidgetTester tester, String location) async {
    final element = tester.element(find.byType(Scaffold).first);
    GoRouter.of(element).go(location);
    await settle(tester);
  }

  testWidgets('the storage limit is shown, chosen and applied', (tester) async {
    final app = await pumpApp(
      tester,
      size: const Size(390, 1400),
      overrides: [
        diskSpaceProvider
            .overrideWithValue(FakeDiskSpace(12 * 1024 * 1024 * 1024)),
      ],
    );
    await open(tester, '/settings/downloads');

    expect(find.text('Storage limit'), findsOneWidget);
    expect(find.textContaining('No limit'), findsOneWidget);
    expect(find.textContaining('12.00 GB free on the phone'), findsOneWidget);

    await tester.tap(find.text('Storage limit'));
    await settle(tester);
    await tester.tap(find.text('5.00 GB'));
    await settle(tester);

    final container =
        ProviderScope.containerOf(tester.element(find.byType(Scaffold).first));
    expect(container.read(settingsProvider).downloadLimitBytes,
        5 * 1024 * 1024 * 1024);
    expect(find.textContaining('5.00 GB - downloads pause'), findsOneWidget);

    // And back to no limit.
    await tester.tap(find.text('Storage limit'));
    await settle(tester);
    await tester.tap(find.text('No limit').last);
    await settle(tester);
    expect(container.read(settingsProvider).downloadLimitBytes, isNull);
    await closeApp(tester, app.db);
  });

  testWidgets('"Remove all downloads" asks first, and Cancel keeps them',
      (tester) async {
    final app = await pumpApp(tester, size: const Size(390, 1400));
    for (final id in const ['al1', 'al3']) {
      await app.db.into(app.db.pins).insert(PinsCompanion.insert(
            serverId: app.serverId,
            targetType: 'album',
            targetId: id,
            createdAtMs: 0,
          ));
    }
    await open(tester, '/settings/downloads');
    await tester.scrollUntilVisible(find.text('Remove all downloads'), 200,
        scrollable: find.byType(Scrollable).first);

    await tester.tap(find.text('Remove all downloads'));
    await settle(tester);

    expect(find.text('Remove all downloads?'), findsOneWidget);
    expect(find.textContaining('2 downloads'), findsOneWidget);
    await tester.tap(find.text('Cancel'));
    await settle(tester);
    expect(await app.db.select(app.db.pins).get(), hasLength(2),
        reason: 'cancelled: nothing is removed');

    await tester.tap(find.text('Remove all downloads'));
    await settle(tester);
    await tester.tap(find.widgetWithText(FilledButton, 'Remove'));
    await settle(tester);
    expect(await app.db.select(app.db.pins).get(), isEmpty);
    await closeApp(tester, app.db);
  });

  testWidgets('a paused queue explains itself, a healthy one stays silent',
      (tester) async {
    final app = await pumpApp(
      tester,
      size: const Size(390, 1400),
      overrides: [
        downloadVerdictProvider
            .overrideWith((ref) => Stream.value(StorageVerdict.limitReached)),
      ],
    );
    await open(tester, '/home/downloaded');

    expect(find.textContaining('Downloads are paused'), findsOneWidget);
    expect(find.textContaining('storage limit'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets('no banner when downloads are healthy', (tester) async {
    final app = await pumpApp(
      tester,
      size: const Size(390, 1400),
      overrides: [
        downloadVerdictProvider
            .overrideWith((ref) => Stream.value(StorageVerdict.ok)),
      ],
    );
    await open(tester, '/home/downloaded');

    expect(find.textContaining('Downloads are paused'), findsNothing);
    await closeApp(tester, app.db);
  });

  testWidgets('a nearly full phone is named as the reason', (tester) async {
    final app = await pumpApp(
      tester,
      size: const Size(390, 1400),
      overrides: [
        downloadVerdictProvider
            .overrideWith((ref) => Stream.value(StorageVerdict.lowSpace)),
      ],
    );
    await open(tester, '/settings/downloads');

    expect(find.textContaining('your phone is almost full'), findsOneWidget);
    await closeApp(tester, app.db);
  });
}
