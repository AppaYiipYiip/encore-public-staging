import 'dart:async';

import 'package:encore/data/db/app_database.dart';
import 'package:encore/domain/connect_link.dart';
import 'package:encore/features/people/people_providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../support/test_app.dart';

/// The first screen (and the way in for someone who was handed a link): a
/// person who has never run a server must understand it (ADR-068).
void main() {
  setUpAll(loadAppFonts);
  setUp(() => SharedPreferences.setMockInitialValues({}));

  String? clipboard;
  setUp(() {
    clipboard = null;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, (call) async {
      switch (call.method) {
        case 'Clipboard.getData':
          return clipboard == null
              ? null
              : <String, dynamic>{'text': clipboard};
        case 'Clipboard.setData':
          clipboard = (call.arguments as Map)['text'] as String?;
      }
      return null;
    });
  });
  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, null);
  });

  group('the first screen', () {
    testWidgets('speaks plainly and asks for three things', (tester) async {
      final app = await pumpApp(tester, seeded: false);

      expect(find.text('Welcome to Encore'), findsOneWidget);
      expect(find.text('Your music, from your own server.'), findsOneWidget);
      expect(find.textContaining('Ask whoever set it up'), findsOneWidget);
      expect(find.text('Server address'), findsOneWidget);
      expect(find.text('Username'), findsOneWidget);
      expect(find.text('Password'), findsOneWidget);
      expect(find.text('Got a setup link? Paste it'), findsOneWidget);
      expect(find.text('Connect'), findsOneWidget);
      // The technical words are not on the front page.
      expect(find.textContaining('Subsonic'), findsNothing);
      expect(find.textContaining('Tailscale'), findsNothing);
      await closeApp(tester, app.db);
    });

    testWidgets('explains what a music server is, for the unsure',
        (tester) async {
      final app = await pumpApp(tester, seeded: false);

      await tester.tap(find.text('New here? What is a music server?'));
      await settle(tester);
      expect(find.textContaining('like a private Spotify'), findsOneWidget);
      expect(find.textContaining('an address, a username and a password'),
          findsOneWidget);
      expect(find.textContaining('login stays on this phone'), findsOneWidget);
      await closeApp(tester, app.db);
    });
  });

  group('a setup link', () {
    testWidgets('fills the address, the second address and the user',
        (tester) async {
      final app = await pumpApp(tester, seeded: false);
      clipboard = const ConnectLink(
        server: 'http://192.168.1.50:4533',
        away: 'https://music.tailnet.ts.net',
        user: 'sara',
      ).toInvite();

      await tester.tap(find.text('Got a setup link? Paste it'));
      await settle(tester);

      expect(find.text('http://192.168.1.50:4533'), findsOneWidget);
      expect(find.text('https://music.tailnet.ts.net'), findsOneWidget);
      expect(find.text('sara'), findsOneWidget);
      expect(find.text('Got it. Now type your password.'), findsOneWidget);
      await closeApp(tester, app.db);
    });

    testWidgets('with no user in it, asks for the username too',
        (tester) async {
      final app = await pumpApp(tester, seeded: false);
      clipboard = '192.168.1.50:4533';

      await tester.tap(find.text('Got a setup link? Paste it'));
      await settle(tester);

      expect(find.text('192.168.1.50:4533'), findsOneWidget);
      expect(find.text('Got it. Now type your username and password.'),
          findsOneWidget);
      await closeApp(tester, app.db);
    });

    testWidgets('something else on the clipboard is explained, not ignored',
        (tester) async {
      final app = await pumpApp(tester, seeded: false);
      clipboard = 'see you at 8!';

      await tester.tap(find.text('Got a setup link? Paste it'));
      await settle(tester);

      expect(find.textContaining('No setup link found'), findsOneWidget);
      await closeApp(tester, app.db);
    });
  });

  group('invite on a server without the people service', () {
    Future<AppDatabase> openServerPage(WidgetTester tester,
        {required bool administrator}) async {
      final app =
          await pumpApp(tester, size: const Size(390, 1800), overrides: [
        isMusicServerAdminProvider.overrideWith((ref) async => administrator),
      ]);
      final element = tester.element(find.byType(Scaffold).first);
      unawaited(GoRouter.of(element).push<void>('/settings/server'));
      await settle(tester);
      return app.db;
    }

    testWidgets('the administrator copies the link built from their addresses',
        (tester) async {
      final db = await openServerPage(tester, administrator: true);

      await tester.scrollUntilVisible(find.text('Invite someone'), 200,
          scrollable: find.byType(Scrollable).first);
      await settle(tester);
      await tester.tap(find.text('Invite someone'));
      await settle(tester);

      expect(find.textContaining('already has an account'), findsOneWidget);
      expect(find.textContaining('Settings, then Users'), findsNothing);
      expect(find.textContaining('encore://connect?server='), findsOneWidget);
      expect(find.textContaining('no password'), findsOneWidget);

      await tester.tap(find.text('Copy link'));
      await settle(tester);
      final text = clipboard ?? '';
      expect(text, startsWith('encore://connect?server='),
          reason: 'only the link: the owner writes the message around it');
      expect(text, isNot(contains('\n')));
      final copied = findConnectLink(text);
      expect(copied?.server, 'http://192.168.1.10:4533');
      expect(copied?.name, 'Home server');
      expect(find.text('Link copied.'), findsOneWidget);
      await closeApp(tester, db);
    });

    testWidgets('somebody who is not the administrator is not offered it',
        (tester) async {
      final db = await openServerPage(tester, administrator: false);

      await tester.scrollUntilVisible(find.text('ADDING MUSIC'), 200,
          scrollable: find.byType(Scrollable).first);
      await settle(tester);

      expect(find.text('Invite someone'), findsNothing);
      expect(find.text('People'), findsNothing);
      await closeApp(tester, db);
    });
  });
}
