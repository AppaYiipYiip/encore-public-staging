import 'package:drift/drift.dart';
import 'package:drift/native.dart';
import 'package:encore/app/providers.dart';
import 'package:encore/core/clock.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/design/theme.dart';
import 'package:encore/design/tokens.dart';
import 'package:encore/features/profiles/profiles_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

/// Owner, 2026-10-22: "in a shared tablet, Android TV, same app, same server, multiple users: switching users, after signing in; you can leave
/// the session, someone else signs in, but it is a trusted device, no need to sign out" (P4-16).
void main() {
  group('the profile in use', () {
    late AppDatabase db;
    late ProviderContainer container;

    Future<int> sign(String user, {int usedAt = 0}) =>
        db.into(db.servers).insert(ServersCompanion.insert(
              name: 'Home',
              username: user,
              endpointsJson: '[]',
              createdAtMs: 0,
              lastUsedAtMs: Value(usedAt),
            ));

    setUp(() {
      db = AppDatabase(NativeDatabase.memory());
      container = ProviderContainer(overrides: [
        databaseProvider.overrideWithValue(db),
        clockProvider.overrideWithValue(FakeClock(DateTime.utc(2026, 10, 22))),
      ]);
      container.listen(activeServerProvider, (_, __) {});
      container.listen(profilesProvider, (_, __) {});
    });

    tearDown(() async {
      container.dispose();
      await db.close();
    });

    Future<String?> inUse() async {
      await Future<void>.delayed(Duration.zero);
      return (await container.read(activeServerProvider.future))?.username;
    }

    test('with nobody chosen yet the first person who signed in is in use',
        () async {
      await sign('marwa');
      await sign('sara');

      expect(await inUse(), 'marwa');
    });

    test('the person who signed in last is the one listening', () async {
      await sign('marwa', usedAt: 1000);
      await sign('sara', usedAt: 2000);

      expect(await inUse(), 'sara');
    });

    test(
        'switching makes another person the one in use and changes nothing else',
        () async {
      final marwa = await sign('marwa', usedAt: 1000);
      await sign('sara', usedAt: 2000);
      expect(await inUse(), 'sara');

      await container.read(switchProfileProvider)(marwa);

      expect(await inUse(), 'marwa');
      final everybody = await container.read(profilesProvider.future);
      expect(everybody.map((p) => p.username), ['marwa', 'sara'],
          reason: 'nobody is signed out or reordered');
    });

    test('the session of a profile is rebuilt only when the profile changes',
        () async {
      await sign('marwa', usedAt: 1000);
      await sign('sara', usedAt: 2000);
      final ids = <int?>[];
      container.listen(activeServerIdProvider, (_, next) => ids.add(next.value),
          fireImmediately: true);
      await Future<void>.delayed(Duration.zero);

      await container.read(switchProfileProvider)(1);
      await Future<void>.delayed(Duration.zero);

      expect(ids.whereType<int>().toSet(), {2, 1});
    });
  });

  group("Who's listening?", () {
    const marwa = ServerRow(
        id: 1,
        name: 'Home music',
        username: 'marwa',
        endpointsJson: '[]',
        capabilitiesJson: '{}',
        createdAtMs: 0,
        lastUsedAtMs: 1000);
    const sara = ServerRow(
        id: 2,
        name: 'Home music',
        username: 'sara',
        endpointsJson: '[]',
        capabilitiesJson: '{}',
        createdAtMs: 0,
        lastUsedAtMs: 2000);

    Future<List<int>> open(WidgetTester tester) async {
      final switched = <int>[];
      final router = GoRouter(
        initialLocation: '/profiles',
        routes: [
          GoRoute(
              path: '/profiles', builder: (_, __) => const ProfilesScreen()),
          GoRoute(
              path: '/home',
              builder: (_, __) => const Scaffold(body: Text('HOME'))),
        ],
      );
      await tester.pumpWidget(ProviderScope(
        overrides: [
          profilesProvider.overrideWith((ref) => Stream.value([marwa, sara])),
          activeServerProvider.overrideWith((ref) => Stream.value(sara)),
          switchProfileProvider.overrideWithValue((id) async {
            switched.add(id);
          }),
        ],
        child: MaterialApp.router(
            theme: buildEncoreTheme(EncoreColors.dark(),
                brightness: Brightness.dark),
            routerConfig: router),
      ));
      await tester.pumpAndSettle();
      return switched;
    }

    testWidgets('lists everybody and says who is listening now',
        (tester) async {
      await open(tester);

      expect(find.text("Who's listening?"), findsOneWidget);
      expect(find.text('marwa'), findsOneWidget);
      expect(find.text('sara'), findsOneWidget);
      expect(find.textContaining('Listening now'), findsOneWidget);
      expect(find.text('Add someone'), findsOneWidget);
    });

    testWidgets('picking somebody needs no password and goes Home',
        (tester) async {
      final switched = await open(tester);

      await tester.tap(find.byKey(const Key('profile-1')));
      await tester.pumpAndSettle();

      expect(switched, [1]);
      expect(find.text('HOME'), findsOneWidget);
    });
  });
}
