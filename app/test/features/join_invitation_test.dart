import 'dart:async';
import 'dart:convert';

import 'package:encore/app/providers.dart';
import 'package:encore/app/share_intake.dart';
import 'package:encore/data/auth/credential_store.dart';
import 'package:encore/data/auth/server_setup_service.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/encore/encore_device.dart';
import 'package:encore/data/people/people_join_client.dart';
import 'package:encore/domain/invite_link.dart';
import 'package:encore/features/onboarding/join_screen.dart'
    show joinRetryDelaysProvider;
import 'package:encore/features/people/people_providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../support/fake_http.dart';
import '../support/test_app.dart';

/// A friend who was sent an invitation joins from inside the app (docs/39 F3):
/// "he has to open the link in the browser, make an account, then use the link
/// he got from the web page to sign in to the app. It is a bit confusing."
/// Now: paste (or open) the invitation, choose a name and a password once, and
/// be in.
void main() {
  setUpAll(loadAppFonts);

  /// No pause between the automatic tries in tests (the real app waits a few seconds).
  var retryDelays = const <Duration>[];
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    retryDelays = const <Duration>[];
  });

  String? clipboard;
  setUp(() {
    clipboard = null;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, (call) async {
      if (call.method == 'Clipboard.getData') {
        return clipboard == null ? null : <String, dynamic>{'text': clipboard};
      }
      return null;
    });
  });
  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, null);
  });

  final link = findInviteLink('https://music.example/people/join/Code123')!;

  late FakeHttpAdapter adapter;
  var redeemed = 0;

  /// The people service and the music server of the reference setup, as they
  /// answered on 2026-10-17.
  FakeHttpAdapter server({
    FakeResponse? info,
    FakeResponse? redeem,
    bool musicLoginWorks = true,
  }) {
    redeemed = 0;
    return adapter = FakeHttpAdapter(routes: {
      '/people/join/Code123/info': (_) =>
          info ??
          const FakeResponse.json({
            'valid': true,
            'inviter': 'owner',
            'server': 'Our music',
            'address': 'https://music.example',
            'expiresAt': 1792000000,
          }),
      '/people/join/Code123/redeem': (_) {
        redeemed++;
        return redeem ??
            const FakeResponse.json(
                {'username': 'mia', 'address': 'https://music.example'},
                status: 201);
      },
      'ping': (_) => musicLoginWorks
          ? FakeResponse.json(subsonicOk({}))
          : FakeResponse.json(subsonicError(40, 'Wrong username or password')),
    });
  }

  /// The fake network answers on the next turn of the real event loop.
  Future<void> wait(WidgetTester tester) async {
    await tester
        .runAsync(() => Future<void>.delayed(const Duration(milliseconds: 40)));
    await settle(tester);
  }

  Future<AppDatabase> open(WidgetTester tester) async {
    final app = await pumpApp(tester, seeded: false, overrides: [
      joinRetryDelaysProvider.overrideWithValue(retryDelays),
      peopleJoinClientProvider
          .overrideWith((ref) => PeopleJoinClient(dio: fakeDio(adapter))),
      serverSetupServiceProvider.overrideWith((ref) => ServerSetupService(
            db: ref.watch(databaseProvider),
            credentials: ref.watch(credentialStoreProvider),
            dioFactory: () => fakeDio(adapter),
          )),
    ]);
    final element = tester.element(find.byType(Scaffold).first);
    GoRouter.of(element).go('/join', extra: link);
    await wait(tester);
    return app.db;
  }

  Future<void> fill(WidgetTester tester, String name, String password) async {
    await tester.enterText(
        find.widgetWithText(TextFormField, 'Username'), name);
    await tester.enterText(
        find.widgetWithText(TextFormField, 'Password'), password);
    await tester.pump();
  }

  testWidgets(
      'an Encore invitation keeps the device the server made for this phone, '
      'so the live channel does not sign in for a second one', (tester) async {
    final encoreLink =
        findInviteLink('http://192.168.1.50:4540/encore/join/ABCD-EFGH-JKLM')!;
    final store = InMemoryCredentialStore();
    adapter = FakeHttpAdapter(routes: {
      '/encore/api/v1/invites/check': (_) => const FakeResponse.json(
          {'invitedBy': 'owner', 'expiresAt': 1792000000000}),
      '/encore/api/v1/info': (_) =>
          const FakeResponse.json({'name': 'Home music', 'apiVersion': '1.0'}),
      '/encore/api/v1/auth/join': (_) => const FakeResponse.json({
            'deviceToken': 'ed_phone',
            'device': {'id': 'dv_7', 'name': 'Phone'},
            'person': {'id': 'pn_1', 'name': 'mia', 'role': 'member'},
          }, status: 201),
      'ping': (_) => FakeResponse.json(subsonicOk({})),
    });
    final app = await pumpApp(tester, seeded: false, overrides: [
      credentialStoreProvider.overrideWithValue(store),
      peopleJoinClientProvider
          .overrideWith((ref) => PeopleJoinClient(dio: fakeDio(adapter))),
      serverSetupServiceProvider.overrideWith((ref) => ServerSetupService(
            db: ref.watch(databaseProvider),
            credentials: ref.watch(credentialStoreProvider),
            dioFactory: () => fakeDio(adapter),
          )),
    ]);
    final element = tester.element(find.byType(Scaffold).first);
    GoRouter.of(element).go('/join', extra: encoreLink);
    await wait(tester);

    await fill(tester, 'mia', 'a long password');
    await tester.tap(find.text('Join'));
    await wait(tester);

    final servers = await app.db.select(app.db.servers).get();
    expect(servers, hasLength(1));
    final kept =
        await store.readSecret(EncoreDevice.secretKey(servers.single.id));
    expect(kept, isNotNull);
    expect(jsonDecode(kept!), {'token': 'ed_phone', 'id': 'dv_7'});
    await closeApp(tester, app.db);
  });

  testWidgets(
      'a network that is not ready yet is tried again by itself, and the '
      'person never sees the failure', (tester) async {
    retryDelays = const [Duration.zero, Duration.zero, Duration.zero];
    var asked = 0;
    adapter = FakeHttpAdapter(routes: {
      '/people/join/Code123/info': (_) {
        asked++;
        return asked <= 2
            ? const FakeResponse.connectionError()
            : const FakeResponse.json({
                'valid': true,
                'inviter': 'owner',
                'server': 'Our music',
                'address': 'https://music.example',
                'expiresAt': 1792000000,
              });
      },
    });
    final db = await open(tester);
    await wait(tester);
    await wait(tester);

    expect(asked, 3);
    expect(find.text('Join Our music'), findsOneWidget);
    expect(find.text('This invitation did not open'), findsNothing);
    await closeApp(tester, db);
  });

  testWidgets('a server that stays out of reach ends on the retry screen',
      (tester) async {
    retryDelays = const [Duration.zero, Duration.zero];
    var asked = 0;
    adapter = FakeHttpAdapter(routes: {
      '/people/join/Code123/info': (_) {
        asked++;
        return const FakeResponse.connectionError();
      },
    });
    final db = await open(tester);
    await wait(tester);
    await wait(tester);

    expect(asked, 3, reason: 'the first try and the two that follow');
    expect(find.text('Try again'), findsOneWidget);
    await closeApp(tester, db);
  });

  testWidgets('an invitation that is refused is not tried again',
      (tester) async {
    retryDelays = const [Duration.zero, Duration.zero];
    var asked = 0;
    adapter = FakeHttpAdapter(routes: {
      '/people/join/Code123/info': (_) {
        asked++;
        return const FakeResponse.json({'error': 'gone'}, status: 404);
      },
    });
    final db = await open(tester);

    expect(asked, 1);
    expect(find.text('This invitation did not open'), findsOneWidget);
    await closeApp(tester, db);
  });

  testWidgets('says who invited the person and asks for two things only',
      (tester) async {
    server();
    final db = await open(tester);

    expect(find.text('Join Our music'), findsOneWidget);
    expect(find.textContaining('owner invited you'), findsOneWidget);
    expect(find.text('Username'), findsOneWidget);
    expect(find.text('Password'), findsOneWidget);
    expect(find.text('Server address'), findsNothing,
        reason: 'the invitation knows where the server is');
    expect(find.text('Join'), findsOneWidget);
    await closeApp(tester, db);
  });

  testWidgets('a capital letter is made small as it is typed', (tester) async {
    server();
    final db = await open(tester);

    await tester.enterText(
        find.widgetWithText(TextFormField, 'Username'), 'Mia');

    expect(find.text('mia'), findsOneWidget);
    await closeApp(tester, db);
  });

  testWidgets('a password that is too short is said before anything is sent',
      (tester) async {
    server();
    final db = await open(tester);

    await fill(tester, 'mia', 'short');
    await tester.tap(find.text('Join'));
    await settle(tester);

    expect(find.text('Choose a password of at least 8 characters.'),
        findsOneWidget);
    expect(redeemed, 0, reason: 'the invitation is not used up');
    await closeApp(tester, db);
  });

  testWidgets('joining makes the account and signs the person in, once',
      (tester) async {
    server();
    final db = await open(tester);

    await fill(tester, 'mia', 'a long password');
    await tester.tap(find.text('Join'));
    await tester.runAsync(() => Future<void>.delayed(
        const Duration(milliseconds: 50))); // the fake network answers
    await settle(tester);

    expect(redeemed, 1);
    final made = adapter.requests.firstWhere((r) => r.method == 'POST');
    expect(jsonDecode(made.body),
        {'username': 'mia', 'password': 'a long password'});
    expect(await db.select(db.servers).get(), hasLength(1),
        reason: 'signed in: the server is saved');
    expect(find.text('Join Our music'), findsNothing,
        reason: 'and the person is past the sign-in screens');
    expect(adapter.requests.any((r) => r.apiMethod == 'ping'), isTrue,
        reason: 'the music server accepted the new login');
    await closeApp(tester, db);
  });

  testWidgets(
      'a name that is taken is said in the server\'s words, and the '
      'person tries another', (tester) async {
    server(
        redeem: const FakeResponse.json(
            {'error': 'Somebody on this server already has that name.'},
            status: 400));
    final db = await open(tester);

    await fill(tester, 'mia', 'a long password');
    await tester.tap(find.text('Join'));
    await tester
        .runAsync(() => Future<void>.delayed(const Duration(milliseconds: 50)));
    await settle(tester);

    expect(find.text('Somebody on this server already has that name.'),
        findsOneWidget);
    expect(find.text('Join'), findsOneWidget, reason: 'can be pressed again');
    expect(find.text('mia'), findsOneWidget, reason: 'what was typed is kept');
    await closeApp(tester, db);
  });

  testWidgets(
      'an invitation that is used up says so and offers the usual '
      'sign-in', (tester) async {
    server(info: const FakeResponse.json({'valid': false}, status: 404));
    final db = await open(tester);

    expect(find.textContaining('not valid any more'), findsOneWidget);
    expect(find.text('Join'), findsNothing);
    expect(find.text('I already have an account'), findsOneWidget);
    await closeApp(tester, db);
  });

  testWidgets('without a network it says so and can try again', (tester) async {
    server(info: const FakeResponse.connectionError());
    final db = await open(tester);

    expect(find.textContaining("Can't reach music.example"), findsOneWidget);
    expect(find.text('Try again'), findsOneWidget);
    await closeApp(tester, db);
  });

  testWidgets('pasting the message on the first screen opens the invitation',
      (tester) async {
    server();
    final app = await pumpApp(tester, seeded: false, overrides: [
      peopleJoinClientProvider
          .overrideWith((ref) => PeopleJoinClient(dio: fakeDio(adapter))),
    ]);
    clipboard = 'Come and listen with me! '
        'https://music.example/people/join/Code123 See you there';

    await tester.tap(find.text('Got a setup link? Paste it'));
    await wait(tester);

    expect(find.text('Join Our music'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets('a link opened or shared from a message opens the invitation',
      (tester) async {
    server();
    final app = await pumpApp(tester, seeded: false, overrides: [
      peopleJoinClientProvider
          .overrideWith((ref) => PeopleJoinClient(dio: fakeDio(adapter))),
      sharedTextProvider.overrideWith((ref) => Stream.value(SharedText(
          'Come and listen with me! https://music.example/people/join/Code123'))),
    ]);
    await wait(tester);

    expect(find.text('Join Our music'), findsOneWidget,
        reason: 'no pasting, no browser: the app opened on the invitation');
    await closeApp(tester, app.db);
  });

  testWidgets('the same link opened a second time opens it a second time',
      (tester) async {
    // Seen on a real phone (2026-10-17): the invitation opened from a message,
    // the person went back, tapped the link again and nothing happened.
    server();
    final shared = StreamController<SharedText>.broadcast();
    addTearDown(shared.close);
    final app = await pumpApp(tester, seeded: false, overrides: [
      peopleJoinClientProvider
          .overrideWith((ref) => PeopleJoinClient(dio: fakeDio(adapter))),
      sharedTextProvider.overrideWith((ref) => shared.stream),
    ]);
    const text = 'https://music.example/people/join/Code123';

    shared.add(SharedText(text));
    await wait(tester);
    expect(find.text('Join Our music'), findsOneWidget);
    await tester.tap(find.text('I already have an account'));
    await wait(tester);
    expect(find.text('Join Our music'), findsNothing);

    shared.add(SharedText(text));
    await wait(tester);

    expect(find.text('Join Our music'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'an invitation to the server the phone already has an account on is '
      'told so, and nothing is imported', (tester) async {
    server();
    final app = await pumpApp(tester, overrides: [
      peopleJoinClientProvider
          .overrideWith((ref) => PeopleJoinClient(dio: fakeDio(adapter))),
      // The seeded phone is signed in on http://192.168.1.10:4533.
      sharedTextProvider.overrideWith((ref) => Stream.value(
          SharedText('http://192.168.1.10:4533/people/join/Code123'))),
    ]);
    await wait(tester);

    expect(find.textContaining('That is an invitation to join this server'),
        findsOneWidget);
    expect(find.text('Join Our music'), findsNothing);
    expect(find.text('Import music'), findsNothing);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'an invitation to ANOTHER server opens on a phone that already has an '
      'account elsewhere (found tapping a link on a phone signed in on '
      'another server)', (tester) async {
    server();
    final app = await pumpApp(tester, overrides: [
      peopleJoinClientProvider
          .overrideWith((ref) => PeopleJoinClient(dio: fakeDio(adapter))),
      sharedTextProvider.overrideWith((ref) => Stream.value(
          SharedText('https://music.example/people/join/Code123'))),
    ]);
    await wait(tester);

    expect(find.text('Join Our music'), findsOneWidget,
        reason: 'the account here is on a different server: join this one too');
    expect(find.textContaining('That is an invitation to join this server'),
        findsNothing,
        reason: 'not told "you have an account here": there is none here');
    await closeApp(tester, app.db);
  });
}
