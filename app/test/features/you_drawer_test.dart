import 'dart:async';

import 'package:dio/dio.dart';
import 'package:drift/drift.dart' show Value;
import 'package:encore/app/providers.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/encore/encore_api.dart';
import 'package:encore/data/encore/encore_live.dart';
import 'package:encore/data/people/people_client.dart';
import 'package:encore/features/jam/jam_providers.dart';
import 'package:encore/features/news/news_providers.dart';
import 'package:encore/features/people/people_providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';

import '../support/fake_encore_server.dart';
import '../support/fake_jam_api.dart';
import '../support/fake_people_api.dart';
import '../support/test_app.dart';

/// AUDIT F51, D-34: the avatar on Home and the gear opened the same page. The avatar now opens the drawer drawn as S-27 (Spotify's
/// arrangement): who is signed in, then one row per place, and only rows whose place exists: no grey placeholders.
void main() {
  setUpAll(loadAppFonts);

  const owner = PeopleMe(
      user: 'marwa', isAdmin: true, sharing: false, role: PersonRole.owner);

  late FakeEncoreServer server;
  late StreamController<LiveEvent> live;

  setUp(() {
    server = FakeEncoreServer();
    live = StreamController<LiveEvent>.broadcast();
  });
  tearDown(() => live.close());

  /// A server that keeps news (an Encore server), as the bell sees it.
  List<Override> withNews() => [
        newsApiProvider.overrideWithValue(EncoreApi(
          dio: Dio()..httpClientAdapter = server.adapter,
          baseUrl: () => Uri.parse('http://home.test:4540'),
          auth: () => {'u': 'tester', 't': 'tok', 's': 'salt'},
        )),
        newsEventsProvider.overrideWithValue(live.stream),
      ];

  Future<AppDatabase> open(
    WidgetTester tester, {
    List<Override> overrides = const [],
    bool hubThere = false,
    PeopleMe? me,
  }) async {
    final app = await pumpApp(tester, overrides: [
      jamApiProvider
          .overrideWith((ref) async => hubThere ? FakeJamApi() : null),
      if (me != null)
        peopleApiProvider.overrideWith((ref) async => FakePeopleApi(me_: me)),
      ...overrides,
    ]);
    await tester.tap(find.widgetWithText(CircleAvatar, 'M').first);
    await settle(tester);
    return app.db;
  }

  final drawer = find.byKey(const Key('you-drawer'));

  testWidgets('the avatar opens the drawer, not Settings', (tester) async {
    final db = await open(tester);

    expect(drawer, findsOneWidget);
    expect(find.descendant(of: drawer, matching: find.text('marwa')),
        findsOneWidget,
        reason: 'who is signed in');
    expect(find.byKey(const Key('drawer-settings')), findsOneWidget);
    expect(find.text('Playback'), findsNothing,
        reason: 'the Settings page did not open');
    await closeApp(tester, db);
  });

  testWidgets(
      'a plain server gets only the rows that exist: Settings, Your server, Add account, Sign out',
      (tester) async {
    final db = await open(tester);

    expect(find.byKey(const Key('drawer-settings')), findsOneWidget);
    expect(find.byKey(const Key('drawer-server')), findsOneWidget);
    expect(find.text('Home server · Not connected'), findsOneWidget,
        reason: 'the server\'s name and state');
    expect(find.byKey(const Key('drawer-add-account')), findsOneWidget);
    expect(find.byKey(const Key('drawer-sign-out')), findsOneWidget);
    for (final absent in ['drawer-news', 'drawer-people', 'drawer-jam']) {
      expect(find.byKey(Key(absent)), findsNothing,
          reason: '$absent has nowhere to go on this server');
    }
    expect(find.text('View profile'), findsNothing,
        reason: 'S-26 and S-28 are not built');
    expect(find.text('Recently played'), findsNothing,
        reason: 'there is no such screen in the app');
    expect(find.text("Who's listening"), findsNothing);
    await closeApp(tester, db);
  });

  testWidgets('What\'s new is a row where the server keeps news, with its mark',
      (tester) async {
    server.addNews('library', 'New on your server');
    final db = await open(tester, overrides: withNews());

    expect(find.byKey(const Key('drawer-news')), findsOneWidget);
    expect(find.text('1 new'), findsOneWidget);
    await closeApp(tester, db);
  });

  testWidgets('People is a row for an owner only', (tester) async {
    final ownerDb = await open(tester, me: owner);
    expect(find.byKey(const Key('drawer-people')), findsOneWidget);
    await closeApp(tester, ownerDb);

    final guestDb = await open(tester,
        me: const PeopleMe(
            user: 'ben',
            isAdmin: false,
            sharing: false,
            role: PersonRole.guest));
    expect(find.byKey(const Key('drawer-people')), findsNothing);
    await closeApp(tester, guestDb);
  });

  testWidgets('Jam is a row only where the server has Jam (D-33)',
      (tester) async {
    final withJam = await open(tester, hubThere: true);
    expect(find.byKey(const Key('drawer-jam')), findsOneWidget);
    await closeApp(tester, withJam);

    final without = await open(tester);
    expect(find.byKey(const Key('drawer-jam')), findsNothing);
    await closeApp(tester, without);
  });

  testWidgets('Settings opens from the drawer and the drawer closes',
      (tester) async {
    final db = await open(tester);

    await tester.tap(find.byKey(const Key('drawer-settings')));
    await settle(tester);

    expect(find.text('Playback'), findsOneWidget);
    expect(drawer, findsNothing);
    await closeApp(tester, db);
  });

  testWidgets('Sign out asks the same question as Settings does',
      (tester) async {
    final db = await open(tester);

    await tester.tap(find.byKey(const Key('drawer-sign-out')));
    await settle(tester);

    expect(find.text('Sign out of Home server?'), findsOneWidget);
    await tester.tap(find.text('Cancel'));
    await settle(tester);
    expect(drawer, findsOneWidget,
        reason: 'cancelling leaves the person where they were');
    await closeApp(tester, db);
  });

  group('several people on this device', () {
    Future<AppDatabase> openWithSara(WidgetTester tester) async {
      final app = await pumpApp(tester, overrides: [
        jamApiProvider.overrideWith((ref) async => null),
      ]);
      await app.db.into(app.db.servers).insert(ServersCompanion.insert(
            name: 'Home server',
            username: 'sara',
            endpointsJson: '[]',
            createdAtMs: 0,
            lastUsedAtMs: const Value(0),
          ));
      await settle(tester);
      await tester.tap(find.widgetWithText(CircleAvatar, 'M').first);
      await settle(tester);
      return app.db;
    }

    testWidgets(
        'the drawn "Who\'s listening" block comes first, with the active one checked',
        (tester) async {
      final db = await openWithSara(tester);

      expect(find.text("Who's listening"), findsOneWidget);
      expect(find.descendant(of: drawer, matching: find.text('sara')),
          findsOneWidget);
      expect(find.byIcon(Icons.check_rounded), findsOneWidget);
      expect(find.byKey(const Key('drawer-add-someone')), findsOneWidget);
      expect(find.byKey(const Key('drawer-add-account')), findsNothing,
          reason: 'one way to add somebody, in the block');
      await closeApp(tester, db);
    });

    testWidgets('switching is one tap from the avatar', (tester) async {
      final db = await openWithSara(tester);
      final container = ProviderScope.containerOf(
          tester.element(find.byType(Scaffold).first));
      expect((await container.read(activeServerProvider.future))?.username,
          'marwa');

      await tester.tap(find.descendant(
          of: find.byKey(const Key('you-drawer')),
          matching: find.text('sara')));
      await settle(tester);

      expect((await container.read(activeServerProvider.future))?.username,
          'sara');
      expect(drawer, findsNothing, reason: 'the drawer closed');
      await closeApp(tester, db);
    });
  });
}
