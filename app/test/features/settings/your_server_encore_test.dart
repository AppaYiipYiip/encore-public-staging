import 'dart:async';

import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/encore/encore_models.dart';
import 'package:encore/features/settings/encore_play_section.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../support/test_app.dart';

/// "Your server" on an Encore server (audit, P2): the page speaks about what that server does (songs it does not have are fetched as they
/// are played, playing does not save, a short rest when the web asks it to slow down) and says nothing about a helper service to install.
EncoreInfo info({String youtube = 'ok', int resumesInSec = 0}) => EncoreInfo(
      apiVersion: '1.0',
      minAppVersion: '0.1.0',
      serverVersion: '0.1.0',
      name: 'Home',
      features: const {'library', 'playback', 'live', 'refs', 'keep'},
      youtubeState: youtube,
      youtubeResumesInSec: resumesInSec,
    );

void main() {
  setUpAll(loadAppFonts);
  setUp(() => SharedPreferences.setMockInitialValues({}));

  Future<AppDatabase> openServerPage(WidgetTester tester,
      {required bool encore, EncoreInfo? answer}) async {
    final app = await pumpApp(tester, size: const Size(390, 6000), overrides: [
      onEncoreServerProvider.overrideWith((ref) async => encore),
      encoreServerInfoProvider.overrideWith((ref) async => answer),
    ]);
    final element = tester.element(find.byType(Scaffold).first);
    unawaited(GoRouter.of(element).push<void>('/settings/server'));
    await settle(tester);
    return app.db;
  }

  Finder text(String part) => find.textContaining(part, skipOffstage: false);

  testWidgets('a ready Encore server: plain words, nothing to install',
      (tester) async {
    final db = await openServerPage(tester, encore: true, answer: info());

    expect(text('Play songs your server does not have'), findsOneWidget);
    expect(text('Ready'), findsOneWidget);
    expect(text('Playing does not save it'), findsOneWidget);
    // Wording of the old helper service must not appear.
    expect(text('encore-fetch'), findsNothing);
    expect(text('docs/19'), findsNothing);
    expect(text('WHAT DOES MY SERVER NEED?'), findsNothing);
    expect(text('download service'), findsNothing);
    expect(text('Navidrome'), findsNothing);
    await closeApp(tester, db);
  });

  testWidgets('a resting Encore server says for how long, in minutes',
      (tester) async {
    final db = await openServerPage(tester,
        encore: true, answer: info(youtube: 'resting', resumesInSec: 290));

    expect(text('Taking a short rest'), findsOneWidget);
    expect(text('about 5 minutes'), findsOneWidget);
    expect(text('Ready'), findsNothing);
    await closeApp(tester, db);
  });

  testWidgets('an Encore server that is switched off for songs from the web',
      (tester) async {
    final db = await openServerPage(tester,
        encore: true, answer: info(youtube: 'off'));

    expect(text('Not available on this server'), findsOneWidget);
    await closeApp(tester, db);
  });

  testWidgets('an Encore server that does not answer', (tester) async {
    final db = await openServerPage(tester, encore: true, answer: null);

    expect(text('Your server did not answer'), findsOneWidget);
    await closeApp(tester, db);
  });

  testWidgets('any other server still shows what it always showed',
      (tester) async {
    final db = await openServerPage(tester, encore: false);

    expect(text('WHAT DOES MY SERVER NEED?'), findsOneWidget);
    expect(text('Taking a short rest'), findsNothing);
    await closeApp(tester, db);
  });

  test('how long a rest lasts, in words', () {
    expect(restWords(0), 'about 1 minute');
    expect(restWords(30), 'about 1 minute');
    expect(restWords(61), 'about 2 minutes');
    expect(restWords(290), 'about 5 minutes');
    expect(restWords(3600), 'about 60 minutes');
    expect(restWords(5400), 'about 2 hours');
    expect(restWords(86400), 'about 24 hours');
  });
}
