import 'dart:async';

import 'package:encore/app/share_out.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/features/settings/diagnostics_screen.dart';
import 'package:encore/features/settings/report_problem_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../support/test_app.dart';

/// Stands in for the phone's share sheet; [opens] false is a phone without one.
class _Out implements ShareOut {
  _Out(this.sent, {this.opens = true});
  final List<String> sent;
  final bool opens;

  @override
  Future<bool> text(String text) async {
    sent.add(text);
    return opens;
  }
}

void main() {
  setUpAll(loadAppFonts);
  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('the message carries the person\'s words first, details after', () {
    final text = buildFeedbackMessage(
        message: '  The lyrics never show.  ', details: '== App ==\nEncore');
    expect(text, contains('feedback'));
    expect(text.indexOf('The lyrics never show.'),
        lessThan(text.indexOf('== App ==')));
    expect(text, contains('no passwords'));
    expect(text, isNot(contains('  The lyrics')));
  });

  test('addresses are taken out of the details, version numbers are not', () {
    final text =
        hideAddresses('GET https://encore.tail1234.ts.net/rest/ping failed\n'
            'Jam hub at 192.168.50.116:4533 and 10.0.2.2\n'
            'Encore 0.1.0+118 on Android 15, kernel 6.1.99');
    expect(text, isNot(contains('ts.net')));
    expect(text, isNot(contains('192.168')));
    expect(text, isNot(contains('10.0.2.2')));
    expect(text, contains('https://<address>'));
    expect(text, contains('Encore 0.1.0+118 on Android 15, kernel 6.1.99'));
  });

  test('the message hides addresses in the details but not in the words', () {
    final text = buildFeedbackMessage(
        message: 'It says 192.168.1.5 is down',
        details: 'host 192.168.1.5:4533');
    expect(text, contains('It says 192.168.1.5 is down'));
    expect(text, contains('host <address>'));
  });

  test('without details only the words are sent', () {
    final text = buildFeedbackMessage(message: 'Too slow', details: null);
    expect(text, contains('Too slow'));
    expect(text, isNot(contains('technical details')));
  });

  Future<AppDatabase> open(WidgetTester tester, ShareOut out) async {
    final app = await pumpApp(tester, size: const Size(390, 1200), overrides: [
      shareOutProvider.overrideWithValue(out),
      diagnosticsReportProvider
          .overrideWith((ref) => '== App ==\nEncore test report'),
    ]);
    final element = tester.element(find.byType(Scaffold).first);
    unawaited(GoRouter.of(element).push<void>('/settings/report'));
    await settle(tester);
    return app.db;
  }

  testWidgets('Help & about leads to the report screen', (tester) async {
    final app = await pumpApp(tester, size: const Size(390, 1200), overrides: [
      // The real report polls the background-sync state on a timer.
      diagnosticsReportProvider.overrideWith((ref) => 'report'),
    ]);
    final element = tester.element(find.byType(Scaffold).first);
    unawaited(GoRouter.of(element).push<void>('/settings'));
    await settle(tester);
    expect(find.text('Help & about'), findsOneWidget);
    await tester.tap(find.text('Help & about'));
    await settle(tester);
    await tester.tap(find.text('Report a problem or idea'));
    await settle(tester);
    expect(find.byKey(const Key('report-message')), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets('sends the words and the details through the share sheet',
      (tester) async {
    final sent = <String>[];
    final db = await open(tester, _Out(sent));

    await tester.enterText(
        find.byKey(const Key('report-message')), 'Lyrics did not show');
    await tester.tap(find.byKey(const Key('report-send')));
    await settle(tester);

    expect(sent, hasLength(1));
    expect(sent.single, contains('Lyrics did not show'));
    expect(sent.single, contains('Encore test report'));
    await closeApp(tester, db);
  });

  testWidgets('the details can be left out', (tester) async {
    final sent = <String>[];
    final db = await open(tester, _Out(sent));

    await tester.enterText(find.byKey(const Key('report-message')), 'Idea');
    await tester.tap(find.byKey(const Key('report-include-details')));
    await settle(tester);
    await tester.tap(find.byKey(const Key('report-send')));
    await settle(tester);

    expect(sent.single, contains('Idea'));
    expect(sent.single, isNot(contains('Encore test report')));
    await closeApp(tester, db);
  });

  testWidgets('an empty message is not sent', (tester) async {
    final sent = <String>[];
    final db = await open(tester, _Out(sent));

    await tester.tap(find.byKey(const Key('report-send')));
    await settle(tester);

    expect(sent, isEmpty);
    expect(find.text('Write a few words first.'), findsOneWidget);
    await closeApp(tester, db);
  });

  testWidgets('a phone without a share sheet: the message is copied',
      (tester) async {
    final copied = <String>[];
    tester.binding.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, (call) async {
      if (call.method == 'Clipboard.setData') {
        copied.add((call.arguments as Map)['text'] as String);
      }
      return null;
    });
    addTearDown(() => tester.binding.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, null));
    final db = await open(tester, _Out(<String>[], opens: false));

    await tester.enterText(
        find.byKey(const Key('report-message')), 'No share sheet here');
    await tester.tap(find.byKey(const Key('report-send')));
    await settle(tester);

    expect(copied.single, contains('No share sheet here'));
    expect(find.textContaining('The message is copied'), findsOneWidget);
    await closeApp(tester, db);
  });
}
