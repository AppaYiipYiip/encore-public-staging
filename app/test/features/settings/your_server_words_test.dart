import 'dart:async';

import 'package:encore/app/providers.dart';
import 'package:encore/app/session.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/features/providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../support/fake_http.dart';
import '../../support/test_app.dart';

/// The phone-app walk (QA-UI-2026-10-31): Q12 "41 songs on this phone" next to "No downloads yet" (they are in the library, not stored), and
/// Q31 in airplane mode "Your server" kept its green "Working" and "In use" (the page read the address resolver, which is not told when the
/// phone loses its network).
void main() {
  setUpAll(loadAppFonts);
  setUp(() => SharedPreferences.setMockInitialValues({}));

  late FakeHttpAdapter adapter;
  setUp(() {
    adapter = FakeHttpAdapter(routes: {
      'ping': (_) => FakeResponse.json(subsonicOk({})),
    });
  });

  Future<AppDatabase> openServerPage(WidgetTester tester,
      {required NetworkKind network,
      Set<String> downloaded = const <String>{}}) async {
    final app = await pumpApp(
      tester,
      size: const Size(390, 6000),
      overrides: [
        onEncoreServerProvider.overrideWith((ref) async => false),
        networkKindProvider.overrideWith((ref) => Stream.value(network)),
        downloadedIdsProvider.overrideWith((ref) => Stream.value(downloaded)),
      ],
      session: (ref) async {
        final db = ref.read(databaseProvider);
        final server = (await db.select(db.servers).get()).first;
        final session = await ServerSession.create(
          verifyAddresses: false,
          db: db,
          server: server,
          password: 'x',
          dio: fakeDio(adapter),
        );
        await session.endpoints.resolve();
        ref.onDispose(() => unawaited(session.dispose()));
        return session;
      },
    );
    final element = tester.element(find.byType(Scaffold).first);
    unawaited(GoRouter.of(element).push<void>('/settings/server'));
    await settle(tester);
    return app.db;
  }

  Finder text(String part) => find.textContaining(part, skipOffstage: false);

  testWidgets('online, the server is Working and its address is In use',
      (tester) async {
    final db = await openServerPage(tester, network: NetworkKind.wifi);

    expect(text('Working'), findsOneWidget,
        reason: 'the control case: this session does reach its server');
    expect(text('In use'), findsOneWidget);
    await closeApp(tester, db);
  });

  testWidgets(
      'in airplane mode it says the server cannot be reached, with no green "Working" and no address "In use" (Q31)',
      (tester) async {
    final db = await openServerPage(tester,
        network: NetworkKind.none, downloaded: {'al1-t1'});

    expect(text('Working'), findsNothing);
    expect(text('In use'), findsNothing);
    expect(text('Not reachable'), findsOneWidget);
    expect(text('No internet'), findsOneWidget,
        reason: 'and it says why, in words');
    expect(text('Songs you downloaded still play'), findsOneWidget);
    await closeApp(tester, db);
  });

  testWidgets(
      'offline with nothing downloaded it does not say downloaded songs still play (Q31: "they do not")',
      (tester) async {
    final db = await openServerPage(tester, network: NetworkKind.none);

    expect(text('Not reachable'), findsOneWidget);
    expect(text('Songs you downloaded still play'), findsNothing,
        reason: 'there are none');
    expect(text('Nothing can play until you reconnect'), findsOneWidget);
    await closeApp(tester, db);
  });

  testWidgets(
      'the songs are "in your library", not "on this phone": they are listed there, not stored there (Q12)',
      (tester) async {
    final db = await openServerPage(tester, network: NetworkKind.wifi);

    expect(text('in your library'), findsOneWidget);
    expect(text('on this phone'), findsNothing);
    await closeApp(tester, db);
  });
}
