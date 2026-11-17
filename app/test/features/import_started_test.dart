import 'package:encore/app/notifications.dart';
import 'package:encore/design/theme.dart';
import 'package:encore/design/tokens.dart';
import 'package:encore/features/downloads/download_notifications_prompt.dart';
import 'package:encore/features/import/import_started.dart';
import 'package:encore/features/import/import_watch.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../support/test_app.dart';

/// docs/design S-95 and D-52 (P2-29): the phone's notification question is asked at the first Import as well as at the first Download, once, our
/// sentence first; the import itself never waits for it, and the card's watch is told at once.
class _Notifications extends LocalNotifications {
  int asked = 0;

  @override
  Future<bool> areAllowed() async => false;

  @override
  Future<bool> requestPermission() async {
    asked++;
    return true;
  }
}

class _Watch extends ImportWatch {
  static int resyncs = 0;

  @override
  ImportWatchState build() => const ImportWatchState();

  @override
  Future<void> resync() async => resyncs++;
}

void main() {
  setUpAll(loadAppFonts);
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    _Watch.resyncs = 0;
  });

  Future<_Notifications> open(WidgetTester tester) async {
    final notifications = _Notifications();
    await tester.pumpWidget(ProviderScope(
      overrides: [
        localNotificationsProvider.overrideWithValue(notifications),
        importWatchProvider.overrideWith(_Watch.new),
      ],
      child: MaterialApp(
        theme:
            buildEncoreTheme(EncoreColors.dark(), brightness: Brightness.dark),
        home: Scaffold(
          body: Center(
            child: Consumer(
              builder: (context, ref, _) => TextButton(
                onPressed: () => importStarted(context, ref),
                child: const Text('Import'),
              ),
            ),
          ),
        ),
      ),
    ));
    return notifications;
  }

  testWidgets(
      'the first Import asks once, with our sentence first, then the phone; the watch is told',
      (tester) async {
    final notifications = await open(tester);

    await tester.tap(find.text('Import'));
    await tester.pumpAndSettle();
    expect(find.text(DownloadNotificationsPage.title), findsOneWidget);
    expect(notifications.asked, 0, reason: 'not before "Allow"');
    expect(_Watch.resyncs, 1);

    await tester.tap(find.text('Allow'));
    await tester.pumpAndSettle();
    expect(notifications.asked, 1);

    await tester.tap(find.text('Import'));
    await tester.pumpAndSettle();
    expect(find.text(DownloadNotificationsPage.title), findsNothing,
        reason: 'once, whatever the answer');
    expect(notifications.asked, 1);
    expect(_Watch.resyncs, 2);
  });

  testWidgets('"Not now" is the answer for good', (tester) async {
    final notifications = await open(tester);

    await tester.tap(find.text('Import'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Not now'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Import'));
    await tester.pumpAndSettle();

    expect(find.text(DownloadNotificationsPage.title), findsNothing);
    expect(notifications.asked, 0);
  });
}
