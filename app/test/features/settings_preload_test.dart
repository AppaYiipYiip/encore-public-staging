import 'package:encore/domain/household.dart';
import 'package:encore/features/settings/settings_controller.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../support/test_app.dart';

/// Settings used to start on their defaults and load a moment later: a light
/// theme flashed dark, and "private listening" was OFF until the load, so music
/// that started in that window was scrobbled (docs/23, B17).
void main() {
  Future<SharedPreferences> prefsWith(Map<String, Object> values) async {
    SharedPreferences.setMockInitialValues(values);
    return SharedPreferences.getInstance();
  }

  group('reading the saved preferences', () {
    test('every saved choice comes back', () async {
      final prefs = await prefsWith({
        'encore.theme': 'light',
        'encore.amoled': true,
        'encore.privateListening': true,
        'encore.backgroundSyncHours': 12,
        'encore.libraryScope': 'mine',
      });

      final s = SettingsController.fromPrefs(prefs);

      expect(s.themeMode, ThemeMode.light);
      expect(s.amoledBlack, isTrue);
      expect(s.privateListening, isTrue);
      expect(s.backgroundSyncHours, 12);
      expect(s.libraryScope, LibraryScope.mine);
    });

    test(
        'no phone notification unless asked: nothing saved, every alert is off',
        () async {
      // The settings screen, the app's start-up and the background job each read the switches their own way (ADR-R44).
      final prefs = await prefsWith({});

      final fromPrefs = SettingsController.fromPrefs(prefs);
      expect(fromPrefs.alertsOnServer, isFalse);
      expect(fromPrefs.alertsReleases, isFalse);
      expect(fromPrefs.alertsImports, isFalse);
      expect(const AppSettings().alerts.onServer, isFalse);
      expect(const AppSettings().alerts.releases, isFalse);
      expect(const AppSettings().alerts.imports, isFalse);

      final background = await readAlertSettings();
      expect(background.onServer, isFalse);
      expect(background.releases, isFalse);
      expect(background.imports, isFalse);
    });

    test('a switch the person turned on is still on for the background job',
        () async {
      await prefsWith({'encore.alerts.releases': true});

      final background = await readAlertSettings();

      expect(background.releases, isTrue);
      expect(background.onServer, isFalse);
      expect(background.imports, isFalse);
    });

    test('nothing saved gives the defaults', () async {
      final s = SettingsController.fromPrefs(await prefsWith({}));

      expect(s.themeMode, ThemeMode.dark);
      expect(s.privateListening, isFalse);
      expect(s.backgroundSyncHours, 6);
    });

    test('a damaged value falls back or is kept in range', () async {
      final s = SettingsController.fromPrefs(await prefsWith({
        'encore.theme': 'neon',
        'encore.lyricsScale': 9.0,
        'encore.backgroundSyncHours': -5,
        'encore.playbackSpeed': 40.0,
      }));

      expect(s.themeMode, ThemeMode.dark);
      expect(s.lyricsTextScale, 1.6);
      expect(s.backgroundSyncHours, 0);
      expect(s.playbackSpeed, 1.0, reason: 'D-23: a saved speed is dropped');
    });
  });

  group('the controller', () {
    test('has the saved choices on its very first read, before any await',
        () async {
      final prefs = await prefsWith({
        'encore.theme': 'light',
        'encore.privateListening': true,
      });
      final container = ProviderContainer(overrides: [
        initialSettingsProvider
            .overrideWithValue(SettingsController.fromPrefs(prefs)),
      ]);
      addTearDown(container.dispose);

      final first = container.read(settingsProvider); // no pump, no await

      expect(first.themeMode, ThemeMode.light);
      expect(first.privateListening, isTrue,
          reason: 'music that starts now must not be scrobbled');
    });

    test('still loads on its own when nothing was preloaded (tests, the job)',
        () async {
      await prefsWith({'encore.theme': 'light'});
      final container = ProviderContainer();
      addTearDown(container.dispose);

      expect(container.read(settingsProvider).themeMode, ThemeMode.dark,
          reason: 'defaults until the async load lands');
      await pumpEventQueue();

      expect(container.read(settingsProvider).themeMode, ThemeMode.light);
    });

    test('a change is saved and survives the next start', () async {
      final prefs = await prefsWith({});
      final container = ProviderContainer(overrides: [
        initialSettingsProvider
            .overrideWithValue(SettingsController.fromPrefs(prefs)),
      ]);
      addTearDown(container.dispose);

      container.read(settingsProvider.notifier).setPrivateListening(true);
      await pumpEventQueue();

      final again =
          SettingsController.fromPrefs(await SharedPreferences.getInstance());
      expect(again.privateListening, isTrue);
    });
  });

  testWidgets('the very first frame already has the saved theme',
      (tester) async {
    final prefs = await prefsWith({'encore.theme': 'light'});
    final app = await pumpApp(tester, overrides: [
      initialSettingsProvider
          .overrideWithValue(SettingsController.fromPrefs(prefs)),
    ]);

    final material = tester.widget<MaterialApp>(find.byType(MaterialApp));
    expect(material.themeMode, ThemeMode.light);
    await closeApp(tester, app.db);
  });
}
