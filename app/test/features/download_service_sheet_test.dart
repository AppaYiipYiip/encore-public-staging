import 'dart:async';

import 'package:encore/app/providers.dart';
import 'package:encore/core/result.dart';
import 'package:encore/data/auth/credential_store.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/requests/portal_client.dart';
import 'package:encore/data/requests/portal_discovery.dart';
import 'package:encore/features/requests/download_service_sheet.dart';
import 'package:encore/features/requests/request_providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../support/test_app.dart';

/// Discovery with canned answers: no sockets, no clock.
class _FakeDiscovery extends PortalDiscovery {
  _FakeDiscovery({this.nearby = const [], this.network = const []})
      : super(probe: PortalProbe());

  final List<Uri> nearby;
  final List<Uri> network;
  final List<Iterable<Uri>> asked = [];
  int searches = 0;

  @override
  Future<List<Uri>> findNearby(Iterable<Uri> candidates) async {
    asked.add(candidates.toList());
    return nearby;
  }

  @override
  Future<List<Uri>> searchNetwork(
    Uri around, {
    int port = PortalDiscovery.defaultPort,
    Set<String> alreadyAsked = const {},
    void Function(int done, int total)? onProgress,
    bool Function()? isCancelled,
  }) async {
    searches++;
    onProgress?.call(253, 253);
    return network;
  }
}

class _FakeProbe extends PortalProbe {
  _FakeProbe(this.answer);

  final ProbeResult answer;
  final List<Uri> asked = [];

  @override
  Future<ProbeResult> probe(Uri base) async {
    asked.add(base);
    return answer;
  }
}

class _FakeBackend implements RequestBackend {
  _FakeBackend(this.result);

  final Result<String> result;

  @override
  Future<Result<String>> check() async => result;

  @override
  Future<Result<RequestReceipt>> request({
    required String artist,
    String? album,
  }) async =>
      const Ok(RequestReceipt(kind: 'album', name: 'x'));

  @override
  Future<Result<PortalOverview>> overview() async => const Ok(PortalOverview());
}

void main() {
  setUpAll(loadAppFonts);

  late CredentialStore store;
  late List<({Uri base, String user, String password})> logins;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    logins = [];
  });

  /// Opens Import music (no service connected) and taps "Connect".
  Future<({AppDatabase db})> open(
    WidgetTester tester, {
    required _FakeDiscovery discovery,
    PortalProbe? probe,
    Map<String, Result<String>> checks = const {},
    Result<String> defaultCheck = const Ok('marwa'),
  }) async {
    final app = await pumpApp(
      tester,
      size: const Size(390, 1600),
      overrides: [
        portalDiscoveryProvider.overrideWithValue(discovery),
        if (probe != null) portalProbeProvider.overrideWithValue(probe),
        portalClientFactoryProvider.overrideWithValue(({
          required Uri baseUrl,
          required String username,
          required String password,
        }) {
          logins.add((base: baseUrl, user: username, password: password));
          return _FakeBackend(checks[password] ?? defaultCheck);
        }),
        importBackendProvider.overrideWith((ref) async => null),
        portalOverviewProvider.overrideWith((ref) => Stream.value(null)),
      ],
    );
    final element = tester.element(find.byType(Scaffold).first);
    store = ProviderScope.containerOf(element).read(credentialStoreProvider);
    await store.writePassword(app.serverId, 'server-secret');
    unawaited(GoRouter.of(element).push<void>('/settings/import'));
    await settle(tester);
    await tester.tap(find.text('Connect'));
    await settle(tester);
    return (db: app.db);
  }

  testWidgets(
      'finds the service next to the server and signs in with the '
      'server login - no typing', (tester) async {
    final discovery =
        _FakeDiscovery(nearby: [Uri.parse('http://192.168.1.113:8700')]);
    final app = await open(tester, discovery: discovery);

    expect(find.text('Connect your download service'), findsOneWidget);
    expect(find.text('Found your download service'), findsOneWidget);
    expect(find.text('192.168.1.113:8700'), findsOneWidget);
    // It asked the music server's own address first.
    expect(
        discovery.asked.single.single.toString(), 'http://192.168.1.10:8700');

    await tester.tap(find.widgetWithText(FilledButton, 'Connect'));
    await settle(tester);

    expect(logins, hasLength(1));
    expect(logins.single.user, 'marwa');
    expect(logins.single.password, 'server-secret');
    expect(logins.single.base.toString(), 'http://192.168.1.113:8700');
    // Connected: the sheet is gone and the Import page lost its banner.
    expect(find.text('Connect your download service'), findsNothing);
    final prefs = await SharedPreferences.getInstance();
    expect(
        prefs.getString('encore.requestPortal'), 'http://192.168.1.113:8700');
    // No second password was stored: the server login keeps being used.
    expect(await store.readSecret(kPortalPasswordKey), isNull);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'nothing next to the server: says what was asked and offers '
      'the network search and typing', (tester) async {
    final discovery = _FakeDiscovery();
    final app = await open(tester, discovery: discovery);

    expect(find.textContaining('Nothing is answering at 192.168.1.10:8700'),
        findsOneWidget);
    expect(find.text('Search my network'), findsOneWidget);
    expect(find.text('Type the address'), findsOneWidget);
    expect(find.text("I don't have one"), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets('the network search finds it on another machine', (tester) async {
    final discovery =
        _FakeDiscovery(network: [Uri.parse('http://192.168.1.113:8700')]);
    final app = await open(tester, discovery: discovery);

    await tester.tap(find.text('Search my network'));
    await settle(tester);

    expect(discovery.searches, 1);
    expect(find.text('Found your download service'), findsOneWidget);
    expect(find.text('192.168.1.113:8700'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets('a service that refuses the server login asks for its own',
      (tester) async {
    final discovery =
        _FakeDiscovery(nearby: [Uri.parse('http://192.168.1.113:8700')]);
    final app = await open(
      tester,
      discovery: discovery,
      checks: {
        'server-secret': const Err(AuthFailure('no')),
        'its-own': const Ok('marwa'),
      },
    );

    await tester.tap(find.widgetWithText(FilledButton, 'Connect'));
    await settle(tester);

    expect(find.textContaining('does not accept your music server login'),
        findsOneWidget);
    await tester.enterText(
        find.widgetWithText(TextField, 'Password'), 'its-own');
    await tester.tap(find.widgetWithText(FilledButton, 'Sign in'));
    await settle(tester);

    expect(logins.map((l) => l.password), ['server-secret', 'its-own']);
    expect(await store.readSecret(kPortalPasswordKey), 'its-own');
    expect(find.text('Connect your download service'), findsNothing);
    await closeApp(tester, app.db);
  });

  testWidgets('a typed address that answers with a web page is named as such',
      (tester) async {
    final discovery = _FakeDiscovery();
    final probe = _FakeProbe(
        const ProbeResult(ProbeVerdict.other, statusCode: 200, reason: 'page'));
    final app = await open(tester, discovery: discovery, probe: probe);

    await tester.tap(find.text('Type the address'));
    await settle(tester);
    await tester.enterText(
        find.widgetWithText(TextField, 'Address'), '192.168.1.40');
    await tester.tap(find.text('Check and connect'));
    await settle(tester);

    expect(probe.asked.single.toString(), 'http://192.168.1.40:8700');
    expect(find.textContaining('answers, but it is not a download service'),
        findsOneWidget);
    expect(logins, isEmpty);
    await closeApp(tester, app.db);
  });

  testWidgets('"I don\'t have one" switches Request and Import off',
      (tester) async {
    final app = await open(tester, discovery: _FakeDiscovery());

    await tester.tap(find.text("I don't have one"));
    await settle(tester);

    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getBool('encore.requestsEnabled'), isFalse);
    expect(find.text('Adding music is switched off'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  group('parseServiceAddress', () {
    test('a bare host gets the usual port', () {
      expect(parseServiceAddress('192.168.50.113').toString(),
          'http://192.168.50.113:8700');
      expect(parseServiceAddress(' nas.local ').toString(),
          'http://nas.local:8700');
    });

    test('an explicit port and scheme are kept', () {
      expect(parseServiceAddress('192.168.50.113:8700').toString(),
          'http://192.168.50.113:8700');
      expect(parseServiceAddress('http://nas:9000/').toString(),
          'http://nas:9000');
      expect(parseServiceAddress('https://music.example.org')!.port, 443);
      expect(parseServiceAddress('https://music.example.org').toString(),
          'https://music.example.org');
      expect(parseServiceAddress('http://nas.local')!.port, 80);
    });

    test('junk is rejected', () {
      expect(parseServiceAddress(''), isNull);
      expect(parseServiceAddress('ftp://nas'), isNull);
      expect(parseServiceAddress('http://'), isNull);
    });
  });

  group('describeProbe', () {
    final uri = Uri.parse('http://192.168.1.10:8700');
    test('names the address and the reason', () {
      expect(
          describeProbe(
              uri, const ProbeResult(ProbeVerdict.silent, reason: 'refused')),
          'Nothing is listening at 192.168.1.10:8700.');
      expect(
          describeProbe(
              uri, const ProbeResult(ProbeVerdict.silent, reason: 'timeout')),
          contains('did not answer in time'));
      expect(
          describeProbe(
              uri, const ProbeResult(ProbeVerdict.other, reason: 'page')),
          contains('returned a web page'));
    });
  });
}
