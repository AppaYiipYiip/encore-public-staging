import 'package:drift/drift.dart' show driftRuntimeOptions;
import 'package:drift/native.dart';
import 'package:encore/app/providers.dart';
import 'package:encore/core/result.dart';
import 'package:encore/data/api/opensubsonic/models.dart';
import 'package:encore/data/auth/credential_store.dart';
import 'package:encore/data/auth/server_setup_service.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/sync/endpoint_resolver.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../support/test_app.dart';

/// The typed form of the first screen ("I already have an account", `docs/31` CN-30 and CN-31, `docs/32` JN-2 and JN-9): an address, a
/// username and a password, asked of the server by [ServerSetupService.check], and what the person is told when it does not work.
void main() {
  setUpAll(() async {
    // The fake service below owns a database besides the app's own.
    driftRuntimeOptions.dontWarnAboutMultipleDatabases = true;
    await loadAppFonts();
  });
  setUp(() => SharedPreferences.setMockInitialValues({}));

  Future<void> fill(
    WidgetTester tester, {
    String address = '192.168.1.10:4533',
    String username = 'ana',
    String password = 'a-test-password',
  }) async {
    Future<void> type(String label, String text) async {
      if (text.isEmpty) return;
      await tester.enterText(find.widgetWithText(TextFormField, label), text);
    }

    await type('Server address', address);
    await type('Username', username);
    await type('Password', password);
  }

  _TypedFormSetup setupAnswering(Result<ServerCheckReport> answer) {
    final db = AppDatabase(NativeDatabase.memory());
    addTearDown(db.close);
    return _TypedFormSetup(answer, db);
  }

  Future<void> connect(WidgetTester tester) async {
    await tester.tap(find.text('Connect'));
    await settle(tester);
  }

  group('the typed form', () {
    testWidgets(
        'CN-30: the server is there but the login is not accepted: it says so, and nothing is saved',
        (tester) async {
      final setup = setupAnswering(const Result.err(AuthFailure('refused')));
      final app = await pumpApp(tester, seeded: false, overrides: [
        serverSetupServiceProvider.overrideWith((ref) => setup),
      ]);

      await fill(tester);
      await connect(tester);

      expect(
          find.text('The server is there, but the username or password was '
              'not accepted.'),
          findsOneWidget);
      expect(setup.checks, hasLength(1));
      expect(setup.saved, isEmpty);
      await closeApp(tester, app.db);
    });

    testWidgets(
        'CN-31: no address answers: it names the address that was typed and asks about the network',
        (tester) async {
      final setup = setupAnswering(const Result.err(NetworkFailure('down')));
      final app = await pumpApp(tester, seeded: false, overrides: [
        serverSetupServiceProvider.overrideWith((ref) => setup),
      ]);

      await fill(tester, address: '192.168.1.77:4533');
      await connect(tester);

      expect(
          find.text("Can't reach 192.168.1.77. Are you on the same network "
              '(or connected through Tailscale)?'),
          findsOneWidget);
      expect(setup.saved, isEmpty);
      await closeApp(tester, app.db);
    });

    testWidgets(
        'JN-2: an address, a username and a password are checked together, and a server that answers is saved with them',
        (tester) async {
      final setup = setupAnswering(Result.ok(ServerCheckReport(
        ping: const SsPing(apiVersion: '1.16.1', type: 'navidrome'),
        reachableEndpoints: [
          ServerEndpoint(
              label: 'Home', url: Uri.parse('http://192.168.1.10:4533')),
        ],
      )));
      final app = await pumpApp(tester, seeded: false, overrides: [
        serverSetupServiceProvider.overrideWith((ref) => setup),
      ]);

      await fill(tester);
      await connect(tester);

      expect(setup.checks, hasLength(1));
      expect(setup.checks.single.username, 'ana');
      expect(setup.checks.single.password, 'a-test-password');
      expect(setup.checks.single.urls, ['http://192.168.1.10:4533']);
      expect(setup.saved, hasLength(1),
          reason: 'the account is kept once the server has answered');
      expect(setup.saved.single.username, 'ana');
      expect(setup.saved.single.urls, ['http://192.168.1.10:4533']);
      await closeApp(tester, app.db);
    });

    testWidgets(
        'JN-9: an address alone joins nothing: the username and the password are asked for, and the server is not asked anything',
        (tester) async {
      final setup = setupAnswering(const Result.err(AuthFailure('refused')));
      final app = await pumpApp(tester, seeded: false, overrides: [
        serverSetupServiceProvider.overrideWith((ref) => setup),
      ]);

      await fill(tester, username: '', password: '');
      await connect(tester);

      expect(find.text('Enter your username'), findsOneWidget);
      expect(find.text('Enter your password'), findsOneWidget);
      expect(setup.checks, isEmpty,
          reason: 'nothing is sent to an address on its own');
      expect(setup.saved, isEmpty);
      await closeApp(tester, app.db);
    });
  });
}

/// A setup service whose answer to "Test & continue" the test chooses; it records what the form asked and what it kept.
class _TypedFormSetup extends ServerSetupService {
  _TypedFormSetup(this.answer, AppDatabase db)
      : super(db: db, credentials: InMemoryCredentialStore());

  final Result<ServerCheckReport> answer;
  final List<({List<String> urls, String username, String password})> checks =
      [];
  final List<({List<String> urls, String username, String password})> saved =
      [];

  @override
  Future<Result<ServerCheckReport>> check({
    required List<ServerEndpoint> endpoints,
    required String username,
    required String password,
    void Function(String step)? onStep,
    String? expectedId,
  }) async {
    checks.add((
      urls: [for (final e in endpoints) e.url.toString()],
      username: username,
      password: password,
    ));
    return answer;
  }

  @override
  Future<int> save({
    required String name,
    required List<ServerEndpoint> endpoints,
    required String username,
    required String password,
    SsPing? ping,
    String? serverId,
  }) async {
    saved.add((
      urls: [for (final e in endpoints) e.url.toString()],
      username: username,
      password: password,
    ));
    return 1;
  }
}
