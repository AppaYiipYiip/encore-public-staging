import 'package:encore/app/providers.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/domain/audio_quality.dart';
import 'package:encore/features/settings/settings_controller.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../support/test_app.dart';

/// P4-24: the Data saver line on Playback, in its drawn states (docs/design S-72): off; on while the phone is not on mobile data (a grey
/// note); on while it is (what is happening, and the rows that keep the person's choice say what limits them). The words are plain; the
/// person's own quality choices are never overwritten.
void main() {
  setUpAll(loadAppFonts);
  setUp(() => SharedPreferences.setMockInitialValues({}));

  Future<AppDatabase> open(
    WidgetTester tester,
    String location, {
    AppSettings settings = const AppSettings(),
    NetworkKind network = NetworkKind.wifi,
    bool reportable = true,
  }) async {
    final app = await pumpApp(tester, size: const Size(390, 2400), overrides: [
      initialSettingsProvider.overrideWithValue(settings),
      networkKindProvider.overrideWith((ref) => Stream.value(network)),
      mobileDataReportableProvider.overrideWithValue(reportable),
    ]);
    final element = tester.element(find.byType(Scaffold).first);
    GoRouter.of(element).go(location);
    await settle(tester);
    return app.db;
  }

  ProviderContainer containerOf(WidgetTester tester) =>
      ProviderScope.containerOf(tester.element(find.byType(Scaffold).first));

  Finder switchTile() => find.byKey(const Key('data-saver-switch'));

  group('Playback', () {
    testWidgets(
        'off: one line under the two quality rows, with its plain words, and no note',
        (tester) async {
      final db = await open(tester, '/settings/playback');

      expect(find.text('Data saver'), findsOneWidget);
      expect(
          find.text(
              'Uses less mobile data: lower quality, smaller pictures, less loaded ahead. Never on Wi-Fi.'),
          findsOneWidget);
      expect(tester.widget<SwitchListTile>(switchTile()).value, isFalse);
      expect(find.byKey(const Key('data-saver-note')), findsNothing);
      // Under the two quality rows, above the Sound section.
      final onMobile = tester.getTopLeft(find.text('On mobile data')).dy;
      final saver = tester.getTopLeft(find.text('Data saver')).dy;
      final sound = tester.getTopLeft(find.text('SOUND')).dy;
      expect(onMobile < saver && saver < sound, isTrue);
      await closeApp(tester, db);
    });

    testWidgets(
        'the switch turns on, is stored, and the person\'s quality choices stay as they were',
        (tester) async {
      final db = await open(tester, '/settings/playback');

      await tester.tap(switchTile());
      await settle(tester);

      final s = containerOf(tester).read(settingsProvider);
      expect(s.dataSaver, isTrue);
      expect(s.streamQualityMobile, AudioQuality.high,
          reason: 'the switch is a cap, not a second quality choice');
      expect(s.streamQualityWifi, AudioQuality.original);
      expect(
          (await SharedPreferences.getInstance()).getBool('encore.dataSaver'),
          isTrue);
      await closeApp(tester, db);
    });

    testWidgets(
        'on, the phone on Wi-Fi: a grey note says why nothing is limited, and nothing is',
        (tester) async {
      final db = await open(tester, '/settings/playback',
          settings: const AppSettings(dataSaver: true));

      expect(find.text('Only used on mobile data.'), findsOneWidget);
      expect(find.text("You're not on mobile data, so nothing is limited now."),
          findsOneWidget);
      expect(find.text('Data saver is working.'), findsNothing);
      expect(find.textContaining('is limiting this'), findsNothing,
          reason: 'the rows are what they always are on Wi-Fi');
      expect(containerOf(tester).read(dataSaverInForceProvider), isFalse);
      await closeApp(tester, db);
    });

    testWidgets('on, offline: it is not in force either, and says the same',
        (tester) async {
      final db = await open(tester, '/settings/playback',
          settings: const AppSettings(dataSaver: true),
          network: NetworkKind.none);

      expect(find.text('Only used on mobile data.'), findsOneWidget);
      expect(containerOf(tester).read(dataSaverInForceProvider), isFalse);
      await closeApp(tester, db);
    });

    testWidgets(
        'on, the phone on mobile data: it says what is happening, and the mobile row says what limits it',
        (tester) async {
      final db = await open(tester, '/settings/playback',
          settings: const AppSettings(dataSaver: true),
          network: NetworkKind.mobile);

      expect(find.text('Data saver is working.'), findsOneWidget);
      expect(
          find.text(
              'Music streams and downloads at Opus 48 kbps, pictures are small, and only the next song is loaded ahead.'),
          findsOneWidget);
      expect(
          find.text('Data saver is limiting this to Opus 48 kbps right now.'),
          findsOneWidget);
      // The row still names the person's own choice.
      expect(find.text('High'), findsOneWidget);
      expect(containerOf(tester).read(dataSaverInForceProvider), isTrue);
      await closeApp(tester, db);
    });

    testWidgets(
        'a person who chose Compatible (MP3) is told it stays as it is, and the row says nothing is limited',
        (tester) async {
      final db = await open(tester, '/settings/playback',
          settings: const AppSettings(
              dataSaver: true,
              streamQualityMobile: AudioQuality.compatible,
              downloadQuality: AudioQuality.compatible),
          network: NetworkKind.mobile);

      expect(
          find.textContaining(
              'Compatible quality stays as it is: its format cannot go lower.'),
          findsNWidgets(2),
          reason: 'under the switch\'s title and in the note');
      expect(find.textContaining('is limiting this'), findsNothing);
      expect(find.textContaining('Music streams'), findsNothing,
          reason: 'nothing is streamed lower, so the note does not claim it');
      await closeApp(tester, db);
    });

    testWidgets(
        'where the platform cannot say it is on mobile data (a browser) the line is not there',
        (tester) async {
      final db = await open(tester, '/settings/playback',
          settings: const AppSettings(dataSaver: true), reportable: false);

      expect(find.text('Data saver'), findsNothing);
      expect(switchTile(), findsNothing);
      expect(find.text('On mobile data'), findsOneWidget,
          reason: 'the rest of the page is unchanged');
      await closeApp(tester, db);
    });
  });

  group('Downloads and storage', () {
    testWidgets(
        'while it is in force the Quality line says it limits new downloads',
        (tester) async {
      final db = await open(tester, '/settings/downloads',
          settings: const AppSettings(dataSaver: true),
          network: NetworkKind.mobile);

      expect(
          find.text(
              'Applies to new downloads. Data saver is limiting them to Opus 48 kbps while you are on mobile data.'),
          findsOneWidget);
      expect(find.text('High'), findsOneWidget,
          reason: 'the person\'s own choice is still shown');
      await closeApp(tester, db);
    });

    testWidgets(
        'on Wi-Fi, or with the switch off, the line is what it always was',
        (tester) async {
      for (final (on, network) in [
        (true, NetworkKind.wifi),
        (false, NetworkKind.mobile),
      ]) {
        final db = await open(tester, '/settings/downloads',
            settings: AppSettings(dataSaver: on), network: network);
        expect(find.textContaining('Applies to new downloads. Opus 160'),
            findsOneWidget,
            reason: 'switch $on on $network');
        expect(find.textContaining('Data saver is limiting'), findsNothing);
        await closeApp(tester, db);
      }
    });

    testWidgets('"Download over Wi-Fi only" is still there, on by default',
        (tester) async {
      final db = await open(tester, '/settings/downloads');
      expect(find.text('Download over Wi-Fi only'), findsOneWidget);
      expect(
          containerOf(tester).read(settingsProvider).wifiOnlyDownloads, isTrue);
      await closeApp(tester, db);
    });
  });

  group('searching the settings', () {
    Future<void> search(WidgetTester tester, String text) async {
      await tester.enterText(find.byType(TextField), text);
      await settle(tester);
    }

    testWidgets('"data saver", "mobile data" and "metered" find Playback',
        (tester) async {
      final db = await open(tester, '/settings');
      for (final word in ['data saver', 'mobile data', 'metered']) {
        await search(tester, word);
        expect(find.text('Playback'), findsOneWidget, reason: word);
      }
      await closeApp(tester, db);
    });
  });
}
