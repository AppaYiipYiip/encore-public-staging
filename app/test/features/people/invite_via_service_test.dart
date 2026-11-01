import 'dart:async';

import 'package:encore/app/share_out.dart';
import 'package:encore/core/result.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/people/people_client.dart';
import 'package:encore/design/tokens.dart';
import 'package:encore/features/common/link_code.dart';
import 'package:encore/features/people/people_providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../support/fake_people_api.dart';
import '../../support/test_app.dart';

/// "Invite someone" on the server page, for the people allowed to (docs/35,
/// docs/31, ADR-092): one link, the friend chooses their own name and password
/// on a page, and the account is made for them. The sender's own message says
/// the rest, so the app hands over the link and nothing else.
class _Out implements ShareOut {
  _Out(this.sent);
  final List<String> sent;

  @override
  Future<bool> text(String text) async {
    sent.add(text);
    return true;
  }
}

void main() {
  setUpAll(loadAppFonts);
  setUp(() => SharedPreferences.setMockInitialValues({}));

  String? clipboard;
  setUp(() {
    clipboard = null;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, (call) async {
      if (call.method == 'Clipboard.setData') {
        clipboard = (call.arguments as Map)['text'] as String?;
      }
      return null;
    });
  });
  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, null);
  });

  const owner = PeopleMe(
      user: 'owner', isAdmin: true, sharing: false, role: PersonRole.owner);
  const inviter = PeopleMe(
      user: 'kim', isAdmin: false, sharing: false, role: PersonRole.inviter);
  const guest = PeopleMe(
      user: 'ben', isAdmin: false, sharing: false, role: PersonRole.guest);

  const link = 'https://music.example.ts.net/people/join/abc';

  Future<AppDatabase> openServerPage(WidgetTester tester, FakePeopleApi api,
      {bool encore = false}) async {
    final app = await pumpApp(tester, size: const Size(390, 1800), overrides: [
      peopleApiProvider.overrideWith((ref) async => api),
      if (encore) encorePeopleApiProvider.overrideWith((ref) async => api),
    ]);
    final element = tester.element(find.byType(Scaffold).first);
    unawaited(GoRouter.of(element).push<void>('/settings/server'));
    await settle(tester);
    return app.db;
  }

  Future<AppDatabase> openInvite(WidgetTester tester, FakePeopleApi api,
      {bool encore = false}) async {
    final db = await openServerPage(tester, api, encore: encore);
    await tester.scrollUntilVisible(find.text('Invite someone'), 200,
        scrollable: find.byType(Scrollable).first);
    await settle(tester);
    await tester.tap(find.text('Invite someone'));
    await settle(tester);
    return db;
  }

  testWidgets('makes a one-use link and copies the link, nothing but the link',
      (tester) async {
    final api = FakePeopleApi(me_: owner);
    final db = await openInvite(tester, api);

    expect(find.text('Create invitation link'), findsOneWidget);
    expect(find.textContaining('create one for them first'), findsNothing,
        reason: 'no accounts to make by hand any more');
    final dialog = find.byType(AlertDialog);
    expect(
        find.descendant(
            of: dialog, matching: find.textContaining('works once')),
        findsOneWidget);
    expect(
        find.descendant(
            of: dialog,
            matching:
                find.textContaining('choose their own name and password')),
        findsOneWidget,
        reason: 'they pick their own, the owner does not hand one out');

    await tester.tap(find.text('Create invitation link'));
    await settle(tester);

    expect(api.createCalls, 1);
    expect(find.text(link), findsOneWidget,
        reason: 'the link on its own, not a message around it');
    expect(find.textContaining('Join my music server'), findsNothing);

    await tester.tap(find.text('Copy link'));
    await settle(tester);
    expect(clipboard, link,
        reason: 'what the owner pastes into their own message');
    expect(find.text('Link copied.'), findsOneWidget);
    await closeApp(tester, db);
  });

  testWidgets(
      'a link with a home-network address says, in plain words and not in red, who it will not open for and how to fix that (F39)',
      (tester) async {
    final api = FakePeopleApi(me_: owner)
      ..createAnswer = Result.ok(CreatedInvite(
        id: '1',
        url: 'http://192.168.50.133:4540/encore/join/ABCD-EFGH-JK1',
        expiresAt: DateTime(2026, 10, 24),
      ));
    final db = await openInvite(tester, api);

    await tester.tap(find.text('Create invitation link'));
    await settle(tester);

    final note = find.byKey(const Key('invite-home-only'));
    expect(note, findsOneWidget);
    Finder inNote(String part) =>
        find.descendant(of: note, matching: find.textContaining(part));
    // In order: what is wrong, what fixes it, how.
    expect(inNote('only works on your home Wi-Fi'), findsOneWidget);
    expect(inNote('away from home'), findsOneWidget);
    expect(inNote('internet address'), findsOneWidget);
    expect(inNote('Tailscale'), findsOneWidget,
        reason: 'the name the person will meet, with what it is');
    expect(inNote('free'), findsOneWidget);
    expect(inNote('encore funnel on'), findsNothing,
        reason: 'a plain music server has no such command');
    expect(inNote('Add an address'), findsOneWidget,
        reason: 'on a plain server the person adds the address by hand');
    // Not an error: nothing is wrong with the link, it is a thing to know before it is sent.
    final danger = tester.element(note).colors.danger;
    for (final t in tester.widgetList<Text>(
        find.descendant(of: note, matching: find.byType(Text)))) {
      expect(t.style?.color, isNot(danger), reason: '"${t.data}" is red');
    }
    await closeApp(tester, db);
  });

  testWidgets(
      'on an Encore server the note says what really happens: the phone learns the new address by itself, there is nothing to add (F39)',
      (tester) async {
    final api = FakePeopleApi(me_: owner)
      ..createAnswer = Result.ok(CreatedInvite(
        id: '1',
        url: 'http://192.168.50.133:4540/encore/join/ABCD-EFGH-JK1',
        expiresAt: DateTime(2026, 10, 24),
      ));
    final db = await openInvite(tester, api, encore: true);

    await tester.tap(find.text('Create invitation link'));
    await settle(tester);

    final note = find.byKey(const Key('invite-home-only'));
    expect(note, findsOneWidget);
    Finder inNote(String part) =>
        find.descendant(of: note, matching: find.textContaining(part));
    expect(inNote('encore funnel on'), findsOneWidget,
        reason: 'the one command, on the computer that runs the server');
    expect(inNote('learns the new address by itself'), findsOneWidget,
        reason: 'the server tells a signed-in phone its addresses (ADR-R40); '
            'the link is made from them');
    expect(inNote('Add an address'), findsNothing,
        reason: 'nothing to type: that step is the fallback of a plain server');
    await closeApp(tester, db);
  });

  testWidgets('a link with an address on the internet carries no warning',
      (tester) async {
    final api = FakePeopleApi(me_: owner);
    final db = await openInvite(tester, api);

    await tester.tap(find.text('Create invitation link'));
    await settle(tester);

    expect(find.text(link), findsOneWidget);
    expect(find.byKey(const Key('invite-home-only')), findsNothing);
    await closeApp(tester, db);
  });

  testWidgets(
      'shows a code to scan: the link itself, for somebody sitting next to you',
      (tester) async {
    // "if a person is next to me and i want to add them in the server..." The
    // new person's own camera reads it and offers to open it in Encore.
    final api = FakePeopleApi(me_: owner);
    final db = await openInvite(tester, api);

    expect(find.byType(LinkCode), findsNothing, reason: 'no link yet');
    await tester.tap(find.text('Create invitation link'));
    await settle(tester);

    expect(tester.widget<LinkCode>(find.byType(LinkCode)).data, link);
    expect(
        find.descendant(
            of: find.byType(LinkCode), matching: find.byType(CustomPaint)),
        findsWidgets,
        reason: 'a code is drawn');
    expect(find.textContaining('scan'), findsOneWidget);
    await closeApp(tester, db);
  });

  testWidgets('shares the link through the share sheet of the phone',
      (tester) async {
    final shared = <String>[];
    final api = FakePeopleApi(me_: owner);
    final app = await pumpApp(tester, size: const Size(390, 1800), overrides: [
      peopleApiProvider.overrideWith((ref) async => api),
      shareOutProvider.overrideWithValue(_Out(shared)),
    ]);
    final element = tester.element(find.byType(Scaffold).first);
    unawaited(GoRouter.of(element).push<void>('/settings/server'));
    await settle(tester);
    await tester.scrollUntilVisible(find.text('Invite someone'), 200,
        scrollable: find.byType(Scrollable).first);
    await settle(tester);
    await tester.tap(find.text('Invite someone'));
    await settle(tester);
    await tester.tap(find.text('Create invitation link'));
    await settle(tester);

    await tester.tap(find.text('Share'));
    await settle(tester);

    expect(shared, hasLength(1));
    expect(shared.single, contains(link));
    expect(shared.single, startsWith('Join me on Encore'));
    await closeApp(tester, app.db);
  });

  testWidgets('says in plain words why a link could not be made',
      (tester) async {
    final api = FakePeopleApi(me_: owner)
      ..createAnswer = const Result<CreatedInvite>.err(ServerFailure(
          "Switch on remote access first: an invitation needs the server's "
          'public address.',
          statusCode: 409));
    final db = await openInvite(tester, api);

    await tester.tap(find.text('Create invitation link'));
    await settle(tester);

    expect(
        find.textContaining('Switch on remote access first'), findsOneWidget);
    expect(find.text('Copy link'), findsNothing);
    await closeApp(tester, db);
  });

  testWidgets('lists the invitations and takes an open one back',
      (tester) async {
    final api = FakePeopleApi(me_: owner)
      ..inviteList = Result.ok([
        InviteRow(
          id: '2',
          state: 'used',
          createdAt: DateTime(2026, 10, 10),
          expiresAt: DateTime(2026, 10, 17),
          redeemedBy: 'ben',
          redeemedAt: DateTime(2026, 10, 11),
        ),
        InviteRow(
          id: '3',
          state: 'open',
          createdAt: DateTime(2026, 10, 16),
          expiresAt: DateTime(2026, 10, 23),
        ),
        InviteRow(
          id: '4',
          state: 'expired',
          createdAt: DateTime(2026, 9, 1),
          expiresAt: DateTime(2026, 9, 8),
        ),
      ]);
    final db = await openInvite(tester, api);

    expect(find.text('Used by ben'), findsOneWidget);
    expect(find.textContaining('Open until 23 Oct'), findsOneWidget);
    expect(find.text('Expired'), findsOneWidget);
    expect(find.text('Revoke'), findsOneWidget,
        reason: 'only an open invitation can be taken back');

    await tester.tap(find.text('Revoke'));
    await settle(tester);

    expect(api.revoked, ['3']);
    await closeApp(tester, db);
  });

  group('what the person becomes', () {
    testWidgets('an owner invites a guest unless they say otherwise',
        (tester) async {
      final api = FakePeopleApi(me_: owner);
      final db = await openInvite(tester, api);

      expect(find.text('A guest'), findsOneWidget);
      expect(find.text('Someone who can invite'), findsOneWidget);
      expect(find.textContaining('They cannot invite anyone'), findsOneWidget);

      await tester.tap(find.text('Create invitation link'));
      await settle(tester);

      expect(api.lastInviteRole, PersonRole.guest);
      await closeApp(tester, db);
    });

    testWidgets('an owner can bring in somebody who invites their own friends',
        (tester) async {
      final api = FakePeopleApi(me_: owner);
      final db = await openInvite(tester, api);

      await tester.tap(find.text('Someone who can invite'));
      await settle(tester);
      expect(find.textContaining('bring their own friends in'), findsOneWidget);

      await tester.tap(find.text('Create invitation link'));
      await settle(tester);

      expect(api.lastInviteRole, PersonRole.inviter);
      await closeApp(tester, db);
    });

    testWidgets('somebody who can invite is not offered the choice',
        (tester) async {
      final api = FakePeopleApi(me_: inviter);
      final db = await openInvite(tester, api);

      expect(find.text('Someone who can invite'), findsNothing);
      await tester.tap(find.text('Create invitation link'));
      await settle(tester);

      expect(api.lastInviteRole, PersonRole.guest,
          reason: 'only an owner decides who may invite');
      expect(find.text(link), findsOneWidget);
      await closeApp(tester, db);
    });

    testWidgets('an owner sees who made each invitation, and what it gives',
        (tester) async {
      final api = FakePeopleApi(me_: owner)
        ..inviteList = Result.ok([
          InviteRow(
            id: '2',
            state: 'used',
            createdAt: DateTime(2026, 10, 10),
            expiresAt: DateTime(2026, 10, 17),
            inviter: 'kim',
            role: PersonRole.inviter,
            redeemedBy: 'ben',
            redeemedAt: DateTime(2026, 10, 11),
          ),
        ]);
      final db = await openInvite(tester, api);

      expect(find.text('Used by ben · can invite · by kim'), findsOneWidget);
      await closeApp(tester, db);
    });

    testWidgets('somebody who can invite sees only their own, unsigned',
        (tester) async {
      final api = FakePeopleApi(me_: inviter)
        ..inviteList = Result.ok([
          InviteRow(
            id: '2',
            state: 'open',
            createdAt: DateTime(2026, 10, 16),
            expiresAt: DateTime(2026, 10, 23),
            inviter: 'kim',
          ),
        ]);
      final db = await openInvite(tester, api);

      expect(find.text('Open until 23 Oct'), findsOneWidget);
      await closeApp(tester, db);
    });
  });

  group('who is shown what on the server page', () {
    Future<void> shows(
      WidgetTester tester,
      PeopleMe who, {
      required bool invite,
      required bool people,
    }) async {
      final db = await openServerPage(tester, FakePeopleApi(me_: who));
      await tester.scrollUntilVisible(find.text('ADDING MUSIC'), 200,
          scrollable: find.byType(Scrollable).first);
      await settle(tester);
      expect(
          find.text('Invite someone'), invite ? findsOneWidget : findsNothing,
          reason: '${who.role.label}: invite');
      expect(find.text('People'), people ? findsOneWidget : findsNothing,
          reason: '${who.role.label}: people');
      await closeApp(tester, db);
    }

    testWidgets('an owner: invite and people', (tester) async {
      await shows(tester, owner, invite: true, people: true);
    });

    testWidgets('somebody who can invite: invite, not people', (tester) async {
      await shows(tester, inviter, invite: true, people: false);
    });

    testWidgets('a guest: neither', (tester) async {
      await shows(tester, guest, invite: false, people: false);
    });

    testWidgets('an owner reaches the list of people from there',
        (tester) async {
      final api = FakePeopleApi(me_: owner)
        ..directory = [
          const PersonOnServer(
              user: 'owner', role: PersonRole.owner, isFounding: true),
          const PersonOnServer(
              user: 'ben', role: PersonRole.guest, isFounding: false),
        ];
      final db = await openServerPage(tester, api);
      await tester.scrollUntilVisible(find.text('People'), 200,
          scrollable: find.byType(Scrollable).first);
      await settle(tester);
      await tester.tap(find.text('People'));
      await settle(tester);

      expect(find.text('ben'), findsOneWidget);
      expect(find.text('owner (you)'), findsOneWidget);
      await closeApp(tester, db);
    });
  });
}
