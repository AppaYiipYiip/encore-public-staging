import 'dart:async';

import 'package:dio/dio.dart';
import 'package:encore/data/encore/encore_api.dart';
import 'package:encore/data/encore/encore_live.dart';
import 'package:encore/features/news/news_providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import '../support/fake_encore_server.dart';
import '../support/test_app.dart';

/// The bell (docs/tasks P2-15, ADR-R44, drawing S-24): one place for news, four kinds, nothing sent to the phone.
void main() {
  setUpAll(loadAppFonts);

  late FakeEncoreServer server;
  late EncoreApi api;
  late StreamController<LiveEvent> live;

  // The test app's clock is 15 October 2026, 21:00.
  int at(int day, int hour, int minute) =>
      DateTime(2026, 10, day, hour, minute).millisecondsSinceEpoch;

  int add(String kind, String title,
      {String? body, String? route, int? createdAt}) {
    final id = server.addNews(kind, title, body: body, route: route);
    if (createdAt != null) server.news.last['createdAt'] = createdAt;
    return id;
  }

  setUp(() {
    server = FakeEncoreServer();
    api = EncoreApi(
      dio: Dio()..httpClientAdapter = server.adapter,
      baseUrl: () => Uri.parse('http://home.test:4540'),
      auth: () => {'u': 'tester', 't': 'tok', 's': 'salt'},
    );
    live = StreamController<LiveEvent>.broadcast();
  });

  tearDown(() => live.close());

  List<Override> bell() => [
        newsApiProvider.overrideWithValue(api),
        newsEventsProvider.overrideWithValue(live.stream),
      ];

  ProviderContainer container() {
    final c = ProviderContainer(overrides: bell());
    addTearDown(c.dispose);
    return c;
  }

  Future<void> until(bool Function() done) async {
    for (var i = 0; i < 200 && !done(); i++) {
      await Future<void>.delayed(const Duration(milliseconds: 5));
    }
  }

  group('what the bell holds', () {
    test('a phone that is not on an Encore server has no bell', () {
      final c = ProviderContainer(overrides: [
        newsApiProvider.overrideWithValue(null),
        newsEventsProvider.overrideWithValue(const Stream.empty()),
      ]);
      addTearDown(c.dispose);

      final news = c.read(newsProvider);

      expect(news.available, isFalse);
      expect(news.items, isEmpty);
    });

    test('it asks the server at start and keeps the unread count', () async {
      add('invite_used', 'Sara joined Our music');
      add('import_done', 'Your import is ready');
      final c = container();
      c.listen(newsProvider, (_, __) {});

      expect(c.read(newsProvider).available, isTrue);
      await until(() => c.read(newsProvider).loaded);

      final news = c.read(newsProvider);
      expect(news.items.map((n) => n.title),
          ['Your import is ready', 'Sara joined Our music']);
      expect(news.unread, 2);
    });

    test('a live "something new" fetches only what is newer', () async {
      add('invite_used', 'Sara joined Our music');
      final c = container();
      c.listen(newsProvider, (_, __) {});
      await until(() => c.read(newsProvider).loaded);
      final before = server.adapter.requests.length;

      add('jam', 'Nina invited you to a Jam');
      live.add(const LiveEvent('notification.new', {'unread': 2}));
      await until(() => c.read(newsProvider).items.length == 2);

      final news = c.read(newsProvider);
      expect(news.items.map((n) => n.title),
          ['Nina invited you to a Jam', 'Sara joined Our music']);
      expect(news.unread, 2);
      final asked = server.adapter.requests.skip(before).single;
      expect(asked.uri.queryParameters['since'], '1',
          reason: 'only what is newer than what the phone has');
    });

    test('coming back to the app ("hello") catches up on what came meanwhile',
        () async {
      final c = container();
      c.listen(newsProvider, (_, __) {});
      await until(() => c.read(newsProvider).loaded);
      expect(c.read(newsProvider).items, isEmpty);

      add('import_done', 'Your import is ready');
      live.add(const LiveEvent('hello'));
      await until(() => c.read(newsProvider).items.isNotEmpty);

      expect(c.read(newsProvider).unread, 1);
    });

    test('reading is at once on the phone and tells the server the newest id',
        () async {
      add('invite_used', 'One');
      final newest = add('invite_used', 'Two');
      final c = container();
      c.listen(newsProvider, (_, __) {});
      await until(() => c.read(newsProvider).loaded);

      await c.read(newsProvider.notifier).markAllRead();

      final news = c.read(newsProvider);
      expect(news.unread, 0);
      expect(news.items.every((n) => n.read), isTrue);
      expect(server.newsRead, [newest]);

      await c.read(newsProvider.notifier).markAllRead();
      expect(server.newsRead, [newest], reason: 'nothing to read: no call');
    });

    test('a server that does not answer leaves the bell as it was', () async {
      add('invite_used', 'One');
      final c = container();
      c.listen(newsProvider, (_, __) {});
      await until(() => c.read(newsProvider).loaded);

      server.online = false;
      add('import_done', 'Two');
      await c.read(newsProvider.notifier).refresh();

      expect(c.read(newsProvider).items.map((n) => n.title), ['One']);
    });
  });

  group('the page', () {
    Future<void> openNews(WidgetTester tester) async {
      final element = tester.element(find.byType(Scaffold).first);
      GoRouter.of(element).go('/home/news');
      await settle(tester);
    }

    testWidgets(
        'with no news it says so, and that nothing is sent to the phone',
        (tester) async {
      final app = await pumpApp(tester, overrides: bell());
      await openNews(tester);

      expect(find.text("What's new"), findsWidgets);
      expect(find.text('Nothing new yet'), findsOneWidget);
      expect(
          find.textContaining('Nothing is sent to your phone unless you ask'),
          findsOneWidget);
      await closeApp(tester, app.db);
    });

    testWidgets(
        'unread news is under "New" with its words, older news under "Earlier"; '
        'all of it is read once shown', (tester) async {
      add('invite_used', 'Sara joined Our music',
          body: 'With the invitation you made.', createdAt: at(14, 12, 0));
      server.news.last['read'] = true;
      add('import_done', 'Your import is ready',
          body: 'Road trip 2025: 47 of 48 songs',
          route: '/settings/import',
          createdAt: at(15, 20, 50));
      final app = await pumpApp(tester, overrides: bell());
      await openNews(tester);

      expect(find.text('New'), findsOneWidget);
      expect(find.text('Earlier'), findsOneWidget);
      expect(find.text('Your import is ready'), findsOneWidget);
      expect(find.text('Road trip 2025: 47 of 48 songs'), findsOneWidget);
      expect(find.text('10 min'), findsOneWidget);
      expect(find.text('Sara joined Our music'), findsOneWidget);
      expect(find.text('Yesterday'), findsOneWidget);
      expect(server.newsRead, [2], reason: 'read as soon as it was shown');
      final heading = tester.getTopLeft(find.text('New')).dy;
      expect(tester.getTopLeft(find.text('Your import is ready')).dy,
          greaterThan(heading));
      expect(tester.getTopLeft(find.text('Earlier')).dy,
          greaterThan(tester.getTopLeft(find.text('Your import is ready')).dy));
      await closeApp(tester, app.db);
    });

    testWidgets('a tap goes where the server said, inside the app',
        (tester) async {
      add('import_done', 'Your import is ready',
          route: '/settings/import', createdAt: at(15, 20, 50));
      final app = await pumpApp(tester, overrides: bell());
      await openNews(tester);

      await tester.tap(find.text('Your import is ready'));
      await settle(tester);

      expect(find.text("What's new"), findsNothing);
      await closeApp(tester, app.db);
    });

    testWidgets('a place outside the app is never followed', (tester) async {
      add('release', 'A new release',
          route: 'https://example.com/x', createdAt: at(15, 20, 50));
      add('jam', 'Another',
          route: '//example.com/x', createdAt: at(15, 20, 51));
      final app = await pumpApp(tester, overrides: bell());
      await openNews(tester);

      await tester.tap(find.text('A new release'));
      await settle(tester);
      await tester.tap(find.text('Another'));
      await settle(tester);

      expect(find.text("What's new"), findsWidgets,
          reason: 'still on the page');
      await closeApp(tester, app.db);
    });
  });

  group('the bell on Home', () {
    testWidgets('is not there where the server keeps no news', (tester) async {
      final app = await pumpApp(tester);

      expect(find.byTooltip("What's new"), findsNothing);
      await closeApp(tester, app.db);
    });

    testWidgets(
        'is there on an Encore server, with a dot when something is unread',
        (tester) async {
      add('invite_used', 'Sara joined Our music');
      final app = await pumpApp(tester, overrides: bell());
      await settle(tester);

      expect(find.byTooltip("What's new, unread"), findsOneWidget);
      expect(find.byType(Badge), findsOneWidget);
      expect(tester.widget<Badge>(find.byType(Badge)).isLabelVisible, isTrue);

      await tester.tap(find.byTooltip("What's new, unread"));
      await settle(tester);
      expect(find.text('Sara joined Our music'), findsOneWidget);
      await closeApp(tester, app.db);
    });

    testWidgets('has no dot when everything is read', (tester) async {
      add('invite_used', 'Sara joined Our music');
      server.news.last['read'] = true;
      final app = await pumpApp(tester, overrides: bell());
      await settle(tester);

      expect(find.byTooltip("What's new"), findsOneWidget);
      expect(tester.widget<Badge>(find.byType(Badge)).isLabelVisible, isFalse);
      await closeApp(tester, app.db);
    });
  });
}
