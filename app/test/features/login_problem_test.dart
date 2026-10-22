import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:dio/dio.dart';
import 'package:drift/native.dart';
import 'package:encore/app/providers.dart';
import 'package:encore/core/result.dart';
import 'package:encore/data/auth/credential_store.dart';
import 'package:encore/data/auth/server_setup_service.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/sync/sync_scheduler.dart';
import 'package:encore/features/auth/login_problem.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fake_http.dart';
import '../support/fake_subsonic_server.dart';
import '../support/test_app.dart';

/// P2-18 (E23): a changed password is a normal event. The person sees one state, "Sign in again", signs in with the new password,
/// and everything (library, downloads, queue) is still there. Before, the app kept showing Home with "Synced 3 d ago", a song row said
/// "the instant-play service did not accept ...", and the only way out was Sign out, which deleted every download.
void main() {
  setUpAll(loadAppFonts);

  const rejected = AuthFailure('The server did not accept your login');

  group('the service that replaces the password', () {
    late AppDatabase db;
    late InMemoryCredentialStore credentials;
    late FakeSubsonicServer server;
    late int serverId;
    late String acceptedPassword;

    ServerSetupService service() => ServerSetupService(
          db: db,
          credentials: credentials,
          dioFactory: () => Dio()..httpClientAdapter = server.adapter,
        );

    setUp(() async {
      db = AppDatabase(NativeDatabase.memory());
      serverId = await Seed.library(db);
      credentials = InMemoryCredentialStore();
      await credentials.writePassword(serverId, 'old-password');
      acceptedPassword = 'new-password';
      server = FakeSubsonicServer()..seed(songCount: 5, albumCount: 1);
      server.adapter
          .routes['ping'] = (request) => _tokenFor(acceptedPassword, request) ==
              request.uri.queryParameters['t']
          ? FakeResponse.json(subsonicOk({}))
          : FakeResponse.json(subsonicError(40, 'Wrong username or password'));
    });

    tearDown(() => db.close());

    Future<ServerRow> account() =>
        (db.select(db.servers)..where((s) => s.id.equals(serverId)))
            .getSingle();

    test('the new password is checked against the server and then stored',
        () async {
      final result =
          await service().replacePassword(await account(), 'new-password');

      expect(result.isOk, isTrue, reason: '${result.failureOrNull}');
      expect(await credentials.readPassword(serverId), 'new-password');
    });

    test('a wrong password is refused and the stored one is left alone',
        () async {
      final result = await service().replacePassword(await account(), 'typo');

      expect(result.failureOrNull, isA<AuthFailure>());
      expect(await credentials.readPassword(serverId), 'old-password');
    });

    test(
        'nothing the phone holds is touched: library, playlists and downloads stay',
        () async {
      final before = [
        (await db.select(db.tracks).get()).length,
        (await db.select(db.playlists).get()).length,
        (await db.select(db.albums).get()).length,
      ];

      await service().replacePassword(await account(), 'new-password');

      expect([
        (await db.select(db.tracks).get()).length,
        (await db.select(db.playlists).get()).length,
        (await db.select(db.albums).get()).length,
      ], before);
      expect((await db.select(db.servers).get()), hasLength(1),
          reason: 'the account is the same one');
    });
  });

  group('what the person sees', () {
    SyncStatus refused() => SyncStatus(
          initialSyncDone: true,
          lastSuccessAt: DateTime(2026, 10, 12),
          lastFailure: rejected,
        );

    testWidgets(
        'a quiet card on Home says to sign in again, and nothing else is deleted',
        (tester) async {
      final app = await pumpApp(tester, overrides: [
        syncStatusProvider.overrideWith((ref) => Stream.value(refused())),
      ]);
      await settle(tester);

      expect(find.text('Sign in again'), findsOneWidget);
      expect(find.byKey(const Key('login-problem-banner')), findsOneWidget);
      expect((await app.db.select(app.db.tracks).get()), isNotEmpty);
      await closeApp(tester, app.db);
    });

    testWidgets('no card while the login works', (tester) async {
      final app = await pumpApp(tester, overrides: [
        syncStatusProvider.overrideWith((ref) => Stream.value(SyncStatus(
            initialSyncDone: true, lastSuccessAt: DateTime(2026, 10, 15)))),
      ]);
      await settle(tester);

      expect(find.byKey(const Key('login-problem-banner')), findsNothing);
      await closeApp(tester, app.db);
    });

    testWidgets(
        'tapping the card opens the prompt; the new password is accepted and the card goes',
        (tester) async {
      final service = _FakeSetup(accept: 'new-password');
      final app = await pumpApp(tester, overrides: [
        syncStatusProvider.overrideWith((ref) => Stream.value(refused())),
        serverSetupServiceProvider.overrideWith((ref) => service),
      ]);
      await settle(tester);

      await tester.tap(find.byKey(const Key('login-problem-banner')));
      await settle(tester);
      expect(find.text('Password'), findsOneWidget);
      expect(find.text('marwa'), findsOneWidget,
          reason: 'the account is shown, not asked for again');

      await tester.enterText(
          find.byKey(const Key('sign-in-again-password')), 'typo');
      await tester.tap(find.text('Sign in'));
      await settle(tester);
      expect(find.textContaining('was not accepted'), findsOneWidget);
      expect(find.byKey(const Key('sign-in-again-password')), findsOneWidget,
          reason: 'still on the prompt');

      await tester.enterText(
          find.byKey(const Key('sign-in-again-password')), 'new-password');
      await tester.tap(find.text('Sign in'));
      await settle(tester);

      expect(find.byKey(const Key('sign-in-again-password')), findsNothing,
          reason: 'back on Home');
      expect(find.byKey(const Key('login-problem-banner')), findsNothing);
      expect(service.tried, ['typo', 'new-password']);
      await closeApp(tester, app.db);
    });

    testWidgets(
        'a song the person tapped that the login refused opens the prompt at once',
        (tester) async {
      final app = await pumpApp(tester);
      await settle(tester);
      final container = ProviderScope.containerOf(
          tester.element(find.byType(Scaffold).first));

      container.read(loginProblemProvider.notifier).rejected(fromAction: true);
      await settle(tester);

      expect(find.byKey(const Key('sign-in-again-password')), findsOneWidget);
      await closeApp(tester, app.db);
    });

    testWidgets(
        'a refused login found by the background sync alone does not interrupt: only the card',
        (tester) async {
      final app = await pumpApp(tester, overrides: [
        syncStatusProvider.overrideWith((ref) => Stream.value(refused())),
      ]);
      await settle(tester);

      expect(find.byKey(const Key('sign-in-again-password')), findsNothing);
      expect(find.byKey(const Key('login-problem-banner')), findsOneWidget);
      await closeApp(tester, app.db);
    });
  });
}

/// The token the client sends for [password] (Subsonic: md5(password + salt)).
String _tokenFor(String password, RecordedRequest request) {
  final salt = request.uri.queryParameters['s'] ?? '';
  return md5.convert(utf8.encode('$password$salt')).toString();
}

class _FakeSetup extends ServerSetupService {
  _FakeSetup({required this.accept})
      : super(
            db: AppDatabase(NativeDatabase.memory()),
            credentials: InMemoryCredentialStore());

  final String accept;
  final List<String> tried = [];

  @override
  Future<Result<void>> replacePassword(
      ServerRow server, String password) async {
    tried.add(password);
    return password == accept
        ? const Result.ok(null)
        : const Result.err(AuthFailure('no'));
  }
}
