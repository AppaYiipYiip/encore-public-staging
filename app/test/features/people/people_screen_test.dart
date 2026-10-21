import 'dart:async';

import 'package:encore/core/result.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/people/people_client.dart';
import 'package:encore/features/people/people_providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import '../../support/fake_people_api.dart';
import '../../support/test_app.dart';

/// The owner's list of the people on the server (ADR-092): "a list of people
/// who are guests, and we can remove them, edit them...". Each test is a
/// sentence the owner would say, and asserts what is on the screen.
void main() {
  setUpAll(loadAppFonts);

  const me = PeopleMe(
      user: 'owner',
      isAdmin: true,
      role: PersonRole.owner,
      canInvite: true,
      canManage: true,
      sharing: false);

  FakePeopleApi server({PeopleMe who = me}) => FakePeopleApi(me_: who)
    ..directory = [
      const PersonOnServer(
          user: 'owner', role: PersonRole.owner, isFounding: true),
      PersonOnServer(
        user: 'kim',
        role: PersonRole.inviter,
        isFounding: false,
        invitedBy: 'owner',
        joinedAt: DateTime(2026, 10, 10),
      ),
      PersonOnServer(
        user: 'ben',
        role: PersonRole.guest,
        isFounding: false,
        invitedBy: 'kim',
        joinedAt: DateTime(2026, 10, 12),
      ),
      const PersonOnServer(
          user: 'sara', role: PersonRole.guest, isFounding: false),
    ];

  Future<AppDatabase> open(WidgetTester tester, FakePeopleApi api) async {
    final app = await pumpApp(tester, size: const Size(390, 1800), overrides: [
      peopleApiProvider.overrideWith((ref) async => api),
    ]);
    final element = tester.element(find.byType(Scaffold).first);
    unawaited(GoRouter.of(element).push<void>('/settings/people'));
    await settle(tester);
    return app.db;
  }

  Future<void> choose(WidgetTester tester, String person, String item) async {
    await tester.tap(find.byTooltip('Change $person'));
    await settle(tester);
    await tester.tap(find.ancestor(
      of: find.text(item),
      matching: find.bySubtype<PopupMenuItem<Object>>(),
    ));
    await settle(tester);
  }

  testWidgets('lists everybody with what they are and who brought them',
      (tester) async {
    final db = await open(tester, server());

    expect(find.text('People'), findsWidgets);
    expect(find.text('owner (you)'), findsOneWidget);
    expect(find.text('Owner · set on the server'), findsOneWidget);
    expect(find.text('Can invite · invited by owner'), findsOneWidget);
    expect(find.text('Guest · invited by kim'), findsOneWidget);
    expect(find.text('Guest'), findsOneWidget,
        reason: 'an account made by hand has nobody who invited it');
    await closeApp(tester, db);
  });

  testWidgets('says in a line what the three roles are', (tester) async {
    final db = await open(tester, server());

    expect(find.textContaining('Owners run the server'), findsOneWidget);
    expect(find.textContaining('Guests listen'), findsOneWidget);
    await closeApp(tester, db);
  });

  testWidgets('a founding owner and yourself have no menu', (tester) async {
    final db = await open(tester, server());

    expect(find.byTooltip('Change owner'), findsNothing);
    expect(find.byTooltip('Change kim'), findsOneWidget);
    expect(find.byTooltip('Change ben'), findsOneWidget);
    await closeApp(tester, db);
  });

  testWidgets(
      'a founding owner is not changed, yourself neither, another '
      'owner is', (tester) async {
    // kim is an owner an owner made; "owner" is named by the server itself.
    final api = FakePeopleApi(
        me_: const PeopleMe(
            user: 'kim',
            isAdmin: false,
            role: PersonRole.owner,
            canInvite: true,
            canManage: true,
            sharing: false))
      ..directory = [
        const PersonOnServer(
            user: 'owner', role: PersonRole.owner, isFounding: true),
        const PersonOnServer(
            user: 'kim', role: PersonRole.owner, isFounding: false),
        const PersonOnServer(
            user: 'ana', role: PersonRole.owner, isFounding: false),
      ];
    final db = await open(tester, api);

    expect(find.text('kim (you)'), findsOneWidget);
    expect(find.byTooltip('Change owner'), findsNothing,
        reason: 'the server names them; the app cannot undo that');
    expect(find.byTooltip('Change kim'), findsNothing,
        reason: 'nobody takes their own ownership away by accident');
    expect(find.byTooltip('Change ana'), findsOneWidget);
    await closeApp(tester, db);
  });

  testWidgets('lets a trusted friend invite, and shows it at once',
      (tester) async {
    final api = server();
    final db = await open(tester, api);

    await choose(tester, 'ben', 'Can invite');

    expect(api.roleChanges, [('ben', PersonRole.inviter)]);
    expect(find.text('Can invite · invited by kim'), findsOneWidget);
    expect(find.text('Guest · invited by kim'), findsNothing);
    await closeApp(tester, db);
  });

  testWidgets('takes the right to invite back', (tester) async {
    final api = server();
    final db = await open(tester, api);

    await choose(tester, 'kim', 'Guest');

    expect(api.roleChanges, [('kim', PersonRole.guest)]);
    await closeApp(tester, db);
  });

  testWidgets('making somebody an owner asks first, and says what it means',
      (tester) async {
    final api = server();
    final db = await open(tester, api);

    await choose(tester, 'sara', 'Owner');

    expect(find.text('Make sara an owner?'), findsOneWidget);
    expect(find.textContaining('invite people, change who may invite'),
        findsOneWidget);
    expect(api.roleChanges, isEmpty,
        reason: 'nothing happens until it is confirmed');

    await tester.tap(find.text('Cancel'));
    await settle(tester);
    expect(api.roleChanges, isEmpty);

    await choose(tester, 'sara', 'Owner');
    await tester.tap(find.text('Make owner'));
    await settle(tester);
    expect(api.roleChanges, [('sara', PersonRole.owner)]);
    await closeApp(tester, db);
  });

  testWidgets('removing somebody says what is lost and what is not',
      (tester) async {
    final api = server();
    final db = await open(tester, api);

    await choose(tester, 'ben', 'Remove from server');

    expect(find.text('Remove ben?'), findsOneWidget);
    expect(find.textContaining('playlists and likes'), findsOneWidget);
    expect(find.textContaining('music files stay'), findsOneWidget);
    expect(api.removed, isEmpty);

    await tester.tap(find.text('Remove'));
    await settle(tester);

    expect(api.removed, ['ben']);
    expect(find.text('ben'), findsNothing,
        reason: 'the row is gone, not merely greyed');
    expect(find.text('ben was removed from the server.'), findsOneWidget);
    await closeApp(tester, db);
  });

  testWidgets('backing out of a removal removes nobody', (tester) async {
    final api = server();
    final db = await open(tester, api);

    await choose(tester, 'ben', 'Remove from server');
    await tester.tap(find.text('Cancel'));
    await settle(tester);

    expect(api.removed, isEmpty);
    expect(find.text('Guest · invited by kim'), findsOneWidget);
    await closeApp(tester, db);
  });

  testWidgets(
      'a refusal from the server is shown in its own words and '
      'changes nothing', (tester) async {
    final api = server()
      ..roleAnswer = const Result<void>.err(ServerFailure(
          'A founding owner cannot be changed here.',
          statusCode: 403));
    final db = await open(tester, api);

    await choose(tester, 'ben', 'Can invite');

    expect(
        find.text('A founding owner cannot be changed here.'), findsOneWidget);
    expect(find.text('Guest · invited by kim'), findsOneWidget,
        reason: 'what is shown is what the server holds');
    await closeApp(tester, db);
  });

  testWidgets('somebody who is not an owner is told, and sees no list',
      (tester) async {
    final api = server(
        who: const PeopleMe(
            user: 'kim',
            isAdmin: false,
            role: PersonRole.inviter,
            canInvite: true,
            canManage: false,
            sharing: false));
    final db = await open(tester, api);

    expect(find.textContaining('Only an owner'), findsOneWidget);
    expect(find.text('ben'), findsNothing);
    await closeApp(tester, db);
  });

  testWidgets('has a way to invite right there', (tester) async {
    final db = await open(tester, server());

    expect(find.text('Invite someone'), findsOneWidget);
    await closeApp(tester, db);
  });
}
