import 'dart:async';
import 'dart:convert';

import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:encore/app/providers.dart';
import 'package:encore/data/auth/server_setup_service.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/sync/endpoint_resolver.dart';
import 'package:encore/data/sync/sync_scheduler.dart';
import 'package:encore/design/theme.dart';
import 'package:encore/design/tokens.dart';
import 'package:encore/features/instant/instant_controller.dart';
import 'package:encore/features/people/people_providers.dart';
import 'package:encore/features/providers.dart' show onEncoreServerProvider;
import 'package:encore/features/requests/request_providers.dart';
import 'package:encore/features/requests/request_ui.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../support/test_app.dart';

/// What the app tells a person about their server (ADR-052, ADR-056): the
/// empty server is not "unreachable", and "your server" says what is there.
void main() {
  setUpAll(loadAppFonts);
  setUp(() => SharedPreferences.setMockInitialValues({}));

  Future<void> openRoute(WidgetTester tester, String location) async {
    final element = tester.element(find.byType(Scaffold).first);
    unawaited(GoRouter.of(element).push<void>(location));
    await settle(tester);
  }

  group('empty server', () {
    Future<AppDatabase> openEmpty(WidgetTester tester,
        {required SyncStatus status}) async {
      final app = await pumpApp(
        tester,
        overrides: [
          syncStatusProvider.overrideWith((ref) => Stream.value(status)),
        ],
      );
      // A server that answered and has nothing in it.
      await app.db.delete(app.db.playlistEntries).go();
      await app.db.delete(app.db.playlists).go();
      await app.db.delete(app.db.tracks).go();
      await app.db.delete(app.db.albums).go();
      await app.db.delete(app.db.artists).go();
      await settle(tester);
      return app.db;
    }

    testWidgets('a reachable, empty server offers the two ways in',
        (tester) async {
      final db = await openEmpty(
        tester,
        status: SyncStatus(
          initialSyncDone: true,
          lastSuccessAt: DateTime(2026, 10, 15, 20),
        ),
      );

      expect(find.text('Add your first music'), findsOneWidget);
      expect(find.textContaining('connected but has no music yet'),
          findsOneWidget);
      expect(find.text('Import a playlist or artist'), findsOneWidget);
      expect(find.text('Search and request'), findsOneWidget);
      expect(find.textContaining('keep trying'), findsNothing);
      await closeApp(tester, db);
    });

    testWidgets(
        'a new friend on a server with "play any song" is told to search and '
        'tap, not to "request"', (tester) async {
      final app = await pumpApp(
        tester,
        overrides: [
          syncStatusProvider.overrideWith((ref) => Stream.value(SyncStatus(
                initialSyncDone: true,
                lastSuccessAt: DateTime(2026, 10, 15, 20),
              ))),
          fetchServiceProvider.overrideWith(
              (ref) async => Uri.parse('https://music.example.org/fetch')),
        ],
      );
      await app.db.delete(app.db.playlistEntries).go();
      await app.db.delete(app.db.playlists).go();
      await app.db.delete(app.db.tracks).go();
      await app.db.delete(app.db.albums).go();
      await app.db.delete(app.db.artists).go();
      await settle(tester);

      expect(find.text('Search for a song to start'), findsOneWidget);
      expect(find.textContaining('tap it'), findsOneWidget);
      expect(find.text('Search for a song'), findsOneWidget);
      expect(find.text('Search and request'), findsNothing);
      expect(find.text('Import a playlist or artist'), findsOneWidget,
          reason: 'still offered, second');
      await closeApp(tester, app.db);
    });

    testWidgets(
        'on an Encore server the empty Home says playing does not save, and '
        'has no "what does my server need" button', (tester) async {
      final app = await pumpApp(
        tester,
        overrides: [
          onEncoreServerProvider.overrideWith((ref) async => true),
          syncStatusProvider.overrideWith((ref) => Stream.value(SyncStatus(
                initialSyncDone: true,
                lastSuccessAt: DateTime(2026, 10, 15, 20),
              ))),
          fetchServiceProvider.overrideWith(
              (ref) async => Uri.parse('http://192.168.1.20:4533')),
        ],
      );
      await app.db.delete(app.db.playlistEntries).go();
      await app.db.delete(app.db.playlists).go();
      await app.db.delete(app.db.tracks).go();
      await app.db.delete(app.db.albums).go();
      await app.db.delete(app.db.artists).go();
      await settle(tester);

      expect(find.text('Search for a song to start'), findsOneWidget);
      expect(find.textContaining('it plays within seconds. Like a song'),
          findsOneWidget);
      expect(find.textContaining('is added to your library'), findsNothing,
          reason: 'playing a song does not save it on an Encore server');
      expect(find.text('What does my server need?'), findsNothing);
      expect(find.text('Search for a song'), findsOneWidget);
      await closeApp(tester, app.db);
    });

    testWidgets('a server that was never reached keeps the honest message',
        (tester) async {
      final db = await openEmpty(tester,
          status: const SyncStatus(initialSyncDone: false));

      expect(find.text('Your library will show up here'), findsOneWidget);
      expect(find.textContaining('keep trying'), findsOneWidget);
      expect(find.text('Add your first music'), findsNothing);
      await closeApp(tester, db);
    });
  });

  group('server addresses', () {
    Future<void> showAddresses(WidgetTester tester) async {
      await openRoute(tester, '/settings/server');
      await tester.scrollUntilVisible(find.text('Add an address'), 200,
          scrollable: find.byType(Scrollable).first);
      await settle(tester);
    }

    Future<List<String>> saved(AppDatabase db) async {
      final row = await db.select(db.servers).getSingle();
      return [
        for (final e in jsonDecode(row.endpointsJson) as List)
          '${(e as Map)['label']} ${e['url']}',
      ];
    }

    testWidgets('lists the saved addresses', (tester) async {
      final app = await pumpApp(tester, size: const Size(390, 1800));
      await showAddresses(tester);

      expect(find.text('ADDRESSES'), findsOneWidget);
      expect(find.text('Home'), findsOneWidget);
      expect(find.textContaining('192.168.1.10:4533'), findsWidgets);
      // One address cannot be removed: there would be nothing left.
      expect(find.byTooltip('Remove Home'), findsNothing);
      await closeApp(tester, app.db);
    });

    testWidgets('an address for away from home can be added and removed',
        (tester) async {
      final app = await pumpApp(tester, size: const Size(390, 1800));
      await showAddresses(tester);

      await tester.tap(find.text('Add an address'));
      await settle(tester);
      await tester.enterText(
          find.widgetWithText(TextField, 'Address'), '100.101.102.103:4533');
      await tester.enterText(
          find.widgetWithText(TextField, 'Name (optional)'), 'Tailscale');
      await tester.tap(find.text('Add'));
      await settle(tester);

      expect(await saved(app.db), [
        'Home http://192.168.1.10:4533',
        'Tailscale http://100.101.102.103:4533',
      ]);
      expect(find.text('Tailscale'), findsOneWidget);

      await tester.tap(find.byTooltip('Remove Tailscale'));
      await settle(tester);
      await tester.tap(find.text('Remove'));
      await settle(tester);
      expect(await saved(app.db), ['Home http://192.168.1.10:4533']);
      await closeApp(tester, app.db);
    });

    testWidgets('plain http over the internet is refused', (tester) async {
      final app = await pumpApp(tester, size: const Size(390, 1800));
      await showAddresses(tester);

      await tester.tap(find.text('Add an address'));
      await settle(tester);
      await tester.enterText(find.widgetWithText(TextField, 'Address'),
          'http://music.example.org');
      await tester.tap(find.text('Add'));
      await settle(tester);

      expect(find.textContaining('must use https'), findsOneWidget);
      expect(await saved(app.db), ['Home http://192.168.1.10:4533']);
      await closeApp(tester, app.db);
    });

    testWidgets('checking shows which address answers and how fast',
        (tester) async {
      final app = await pumpApp(
        tester,
        size: const Size(390, 1800),
        overrides: [
          serverSetupServiceProvider.overrideWith((ref) => _FakeSetup(
                db: ref.watch(databaseProvider),
                credentials: ref.watch(credentialStoreProvider),
              )),
        ],
      );
      await app.db.update(app.db.servers).write(ServersCompanion(
            endpointsJson: Value(jsonEncode([
              {'label': 'Home', 'url': 'http://192.168.1.10:4533'},
              {'label': 'Tailscale', 'url': 'http://100.101.102.103:4533'},
            ])),
          ));
      final element = tester.element(find.byType(Scaffold).first);
      final server = await app.db.select(app.db.servers).getSingle();
      await ProviderScope.containerOf(element)
          .read(credentialStoreProvider)
          .writePassword(server.id, 'secret');
      await settle(tester);
      await showAddresses(tester);

      await tester.tap(find.text('Check addresses'));
      await settle(tester);

      expect(find.text('38 ms'), findsOneWidget);
      expect(find.text('No answer'), findsOneWidget);
      await closeApp(tester, app.db);
    });

    testWidgets(
        'checking the addresses also looks again for friends and "play any '
        'song" (a name that did not resolve a minute ago may now)',
        (tester) async {
      var peopleLooks = 0;
      var fetchLooks = 0;
      final app = await pumpApp(
        tester,
        size: const Size(390, 1800),
        overrides: [
          serverSetupServiceProvider.overrideWith((ref) => _FakeSetup(
                db: ref.watch(databaseProvider),
                credentials: ref.watch(credentialStoreProvider),
              )),
          peopleServiceProvider.overrideWith((ref) async {
            peopleLooks++;
            return null;
          }),
          fetchServiceProvider.overrideWith((ref) async {
            fetchLooks++;
            return null;
          }),
        ],
      );
      final element = tester.element(find.byType(Scaffold).first);
      final server = await app.db.select(app.db.servers).getSingle();
      await ProviderScope.containerOf(element)
          .read(credentialStoreProvider)
          .writePassword(server.id, 'secret');
      await settle(tester);
      await showAddresses(tester);
      final peopleBefore = peopleLooks;
      final fetchBefore = fetchLooks;

      await tester.tap(find.text('Check addresses'));
      await settle(tester);

      expect(peopleLooks, greaterThan(peopleBefore),
          reason: 'the Your server page showed no People tile because the '
              'first look failed, and nothing ever looked again');
      expect(fetchLooks, greaterThan(fetchBefore));
      await closeApp(tester, app.db);
    });

    testWidgets('the same address twice is refused', (tester) async {
      final app = await pumpApp(tester, size: const Size(390, 1800));
      await showAddresses(tester);

      await tester.tap(find.text('Add an address'));
      await settle(tester);
      await tester.enterText(
          find.widgetWithText(TextField, 'Address'), '192.168.1.10:4533');
      await tester.tap(find.text('Add'));
      await settle(tester);

      expect(find.textContaining('already in the list'), findsOneWidget);
      await closeApp(tester, app.db);
    });
  });

  group('Your server page', () {
    testWidgets('is opened from the profile card and names the three parts',
        (tester) async {
      final app = await pumpApp(tester, size: const Size(390, 1800));
      await openRoute(tester, '/settings');
      await tester.tap(find.text('Home server'));
      await settle(tester);

      expect(find.text('Your server'), findsWidgets);
      expect(find.text('MUSIC SERVER'), findsOneWidget);
      expect(find.text('ADDING MUSIC'), findsOneWidget);
      expect(find.text('LYRICS'), findsOneWidget);
      // No download service connected: calm, with the way to find it.
      expect(find.text('Not set up'), findsOneWidget);
      expect(find.text('Find it'), findsOneWidget);
      expect(
          find.textContaining('A download service - optional'), findsOneWidget);
      await closeApp(tester, app.db);
    });

    testWidgets('shows the connected service and its address', (tester) async {
      SharedPreferences.setMockInitialValues({
        'encore.requestPortal': 'http://192.168.50.113:8700',
        'encore.requestPortalUser': 'marwa',
      });
      final app = await pumpApp(tester, size: const Size(390, 1800));
      await openRoute(tester, '/settings/server');

      expect(find.text('Connected - 192.168.50.113:8700'), findsOneWidget);
      expect(find.text('Test connection'), findsOneWidget);
      expect(find.text('Not set up'), findsNothing);
      await closeApp(tester, app.db);
    });

    testWidgets(
        'with "play any song" available the old download-service section is '
        'not shown (a friend was told "Not set up - Find it" for a service '
        'this server does not have)', (tester) async {
      final app = await pumpApp(
        tester,
        size: const Size(390, 1800),
        overrides: [
          fetchServiceProvider.overrideWith(
              (ref) async => Uri.parse('https://music.example.org/fetch')),
        ],
      );
      await openRoute(tester, '/settings/server');

      expect(find.text('PLAY ANY SONG'), findsOneWidget);
      expect(find.text('ADDING MUSIC'), findsNothing);
      expect(find.text('Not set up'), findsNothing);
      expect(find.text('Find it'), findsNothing);
      await closeApp(tester, app.db);
    });

    testWidgets('a download service that is connected keeps its section',
        (tester) async {
      SharedPreferences.setMockInitialValues({
        'encore.requestPortal': 'http://192.168.50.113:8700',
        'encore.requestPortalUser': 'marwa',
      });
      final app = await pumpApp(
        tester,
        size: const Size(390, 1800),
        overrides: [
          fetchServiceProvider.overrideWith(
              (ref) async => Uri.parse('https://music.example.org/fetch')),
        ],
      );
      await openRoute(tester, '/settings/server');

      expect(find.text('ADDING MUSIC'), findsOneWidget);
      expect(find.text('Connected - 192.168.50.113:8700'), findsOneWidget);
      await closeApp(tester, app.db);
    });

    testWidgets('says so when Request and Import were switched off',
        (tester) async {
      SharedPreferences.setMockInitialValues({'encore.requestsEnabled': false});
      final app = await pumpApp(tester, size: const Size(390, 1800));
      await openRoute(tester, '/settings/server');

      expect(find.text('Switched off'), findsOneWidget);
      expect(find.text('Switch on'), findsOneWidget);
      await closeApp(tester, app.db);
    });
  });

  group('Request chip', () {
    testWidgets('is hidden once the person said there is no download service',
        (tester) async {
      SharedPreferences.setMockInitialValues({'encore.requestsEnabled': false});
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            requestStateProvider
                .overrideWith((ref, key) => Stream<RequestRow?>.value(null)),
          ],
          child: MaterialApp(
            theme: buildEncoreTheme(EncoreColors.dark(),
                brightness: Brightness.dark),
            home: const Scaffold(
              body: RequestChip(artist: 'Alcest', album: 'Kodama'),
            ),
          ),
        ),
      );
      // The preference is read asynchronously.
      await tester.pump(const Duration(milliseconds: 50));
      await tester.pump(const Duration(milliseconds: 50));

      expect(find.text('Request'), findsNothing);
    });
  });
}

/// Answers for the home address only (as when Tailscale is off).
class _FakeSetup extends ServerSetupService {
  _FakeSetup({required super.db, required super.credentials});

  @override
  Future<Duration?> probe(
    ServerEndpoint endpoint, {
    required String username,
    required String password,
  }) async =>
      endpoint.url.host == '192.168.1.10'
          ? const Duration(milliseconds: 38)
          : null;
}
