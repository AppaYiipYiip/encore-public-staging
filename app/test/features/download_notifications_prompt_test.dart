import 'package:encore/app/notifications.dart';
import 'package:encore/data/repos/downloads_repository.dart';
import 'package:encore/design/theme.dart';
import 'package:encore/design/tokens.dart';
import 'package:encore/domain/audio_quality.dart';
import 'package:encore/features/common/download_button.dart';
import 'package:encore/features/downloads/download_notifications_prompt.dart';
import 'package:encore/features/downloads/download_providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../support/test_app.dart';

/// D-52: the first Download asks, once, whether to show its progress. Our sentence comes first (S-92, drawn), then the phone's own question;
/// the download is started before and never waits for the answer, and nothing is asked twice, whatever the answer was.
void main() {
  setUpAll(loadAppFonts);
  setUp(() => SharedPreferences.setMockInitialValues({}));

  Future<_Phone> open(WidgetTester tester, {bool allowed = false}) async {
    final phone = _Phone(allowed: allowed);
    await tester.pumpWidget(ProviderScope(
      overrides: [
        downloadActionsProvider.overrideWithValue(phone.actions),
        localNotificationsProvider.overrideWithValue(phone.notifications),
      ],
      child: MaterialApp(
        theme:
            buildEncoreTheme(EncoreColors.dark(), brightness: Brightness.dark),
        home: const Scaffold(
          body: Center(
            child: DownloadButton(
              type: PinTargetType.album,
              targetId: 'al1',
              name: 'Kodama',
            ),
          ),
        ),
      ),
    ));
    await tester.pump();
    return phone;
  }

  Future<void> pressDownload(WidgetTester tester) async {
    await tester.tap(find.byType(DownloadButton));
    await tester.pumpAndSettle();
  }

  testWidgets('the download starts first, then our sentence is shown',
      (tester) async {
    final phone = await open(tester);

    await pressDownload(tester);

    expect(phone.actions.pinned, ['album:al1']);
    expect(find.text(DownloadNotificationsPage.title), findsOneWidget);
    expect(find.text(DownloadNotificationsPage.message), findsOneWidget);
    expect(phone.notifications.asked, 0, reason: 'not before "Allow"');
    expect(find.byType(SnackBar), findsNothing,
        reason: 'the line of the Download button must not cover "Not now"');
  });

  testWidgets('"Allow" brings the phone\'s own question, once', (tester) async {
    final phone = await open(tester);

    await pressDownload(tester);
    await tester.tap(find.text('Allow'));
    await tester.pumpAndSettle();

    expect(find.text(DownloadNotificationsPage.title), findsNothing);
    expect(phone.notifications.asked, 1);
    expect(phone.actions.pinned, ['album:al1']);
  });

  testWidgets(
      '"Not now" sends no phone question, the download carries on, and the next Download does not ask again',
      (tester) async {
    final phone = await open(tester);

    await pressDownload(tester);
    await tester.tap(find.text('Not now'));
    await tester.pumpAndSettle();
    expect(phone.notifications.asked, 0);

    await pressDownload(tester); // a second Download, e.g. another album
    expect(find.text(DownloadNotificationsPage.title), findsNothing);
    expect(phone.actions.pinned, ['album:al1', 'album:al1']);
    expect(phone.notifications.asked, 0);
  });

  testWidgets('going back is the same as "Not now"', (tester) async {
    final phone = await open(tester);

    await pressDownload(tester);
    await tester.binding.handlePopRoute(); // the phone's own back
    await tester.pumpAndSettle();
    await pressDownload(tester);

    expect(find.text(DownloadNotificationsPage.title), findsNothing);
    expect(phone.notifications.asked, 0);
  });

  testWidgets(
      'a phone that needs no question (below Android 13, or already allowed) is shown nothing',
      (tester) async {
    final phone = await open(tester, allowed: true);

    await pressDownload(tester);

    expect(phone.actions.pinned, ['album:al1']);
    expect(find.text(DownloadNotificationsPage.title), findsNothing);
    expect(phone.notifications.asked, 0);
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.containsKey('encore.downloadNotificationsAsked'), isFalse,
        reason: 'nothing is stored when nothing was asked');
  });

  testWidgets(
      'at text size 200 % on a 390 x 844 phone nothing overflows and both buttons can be pressed',
      (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    bool? answer;
    await tester.pumpWidget(MaterialApp(
      theme: buildEncoreTheme(EncoreColors.dark(), brightness: Brightness.dark),
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(context)
            .copyWith(textScaler: const TextScaler.linear(2)),
        child: child!,
      ),
      home: Builder(
        builder: (context) => Scaffold(
          body: Center(
            child: TextButton(
              onPressed: () async => answer = await Navigator.of(context)
                  .push<bool>(MaterialPageRoute<bool>(
                      builder: (_) => const DownloadNotificationsPage())),
              child: const Text('open'),
            ),
          ),
        ),
      ),
    ));

    for (final button in const ['Allow', 'Not now']) {
      await tester.tap(find.text('open'));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull,
          reason: 'no overflow at 200 % text');
      expect(find.text(DownloadNotificationsPage.title), findsOneWidget);
      await tester.tap(find.text(button));
      await tester.pumpAndSettle();
      expect(answer, button == 'Allow');
    }
  });

  testWidgets('the phone refusing the question does not stop the download',
      (tester) async {
    final phone = await open(tester)
      ..notifications.grants = false;

    await pressDownload(tester);
    await tester.tap(find.text('Allow'));
    await tester.pumpAndSettle();
    await pressDownload(tester);

    expect(phone.notifications.asked, 1,
        reason: 'refused once is refused: the phone itself will not ask again');
    expect(find.text(DownloadNotificationsPage.title), findsNothing);
    expect(phone.actions.pinned, ['album:al1', 'album:al1']);
  });
}

class _Phone {
  _Phone({required bool allowed})
      : notifications = _Notifications(allowed),
        actions = _Actions();

  final _Notifications notifications;
  final _Actions actions;
}

class _Notifications extends LocalNotifications {
  _Notifications(this.allowed);

  final bool allowed;
  bool grants = true;
  int asked = 0;

  @override
  Future<bool> areAllowed() async => allowed;

  @override
  Future<bool> requestPermission() async {
    asked++;
    return grants;
  }
}

class _Actions implements DownloadActions {
  final List<String> pinned = [];

  @override
  Future<void> pin(PinTargetType type, String targetId,
      {AudioQuality? quality}) async {
    pinned.add('${type.name}:$targetId');
  }

  @override
  Future<void> unpin(PinTargetType type, String targetId) async {}

  @override
  Future<void> retry() async {}

  @override
  Future<void> removeAll() async {}
}
