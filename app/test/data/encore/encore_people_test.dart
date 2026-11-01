import 'package:dio/dio.dart';
import 'package:encore/data/encore/encore_api.dart';
import 'package:encore/data/encore/encore_people.dart';
import 'package:encore/data/people/people_client.dart';
import 'package:encore/domain/invite_link.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_encore_server.dart';

void main() {
  late FakeEncoreServer server;
  late EncorePeopleApi people;

  setUp(() {
    server = FakeEncoreServer(user: 'marwa');
    people = EncorePeopleApi(
      api: EncoreApi(
        dio: Dio()..httpClientAdapter = server.adapter,
        baseUrl: () => Uri.parse('http://192.168.50.133:4540'),
        auth: () => {'u': 'marwa', 't': 'tok', 's': 'salt'},
      ),
      address: () => Uri.parse('http://192.168.50.133:4540'),
    );
  });

  test(
      'F57: an Encore server cannot show what a person listens to to friends, so the people API says so (the switch is not offered)',
      () {
    expect(people.sharesListening, isFalse);
  });

  group('which address an invitation is made with', () {
    final home = Uri.parse('http://192.168.50.133:4540');
    final tailnet = Uri.parse('http://100.101.102.103:4540');
    final funnel = Uri.parse('https://music.example.ts.net');

    test('the address on the internet wins over the one in use at home', () {
      expect(EncorePeopleApi.invitationAddress([home, funnel], home), funnel);
      expect(EncorePeopleApi.invitationAddress([funnel, home], home), funnel);
    });

    test('a Tailscale address is not an address a friend can use', () {
      expect(EncorePeopleApi.invitationAddress([home, tailnet], home), home);
      expect(EncorePeopleApi.invitationAddress([tailnet, funnel], tailnet),
          funnel);
    });

    test('https is preferred, and with only a home address that is the one',
        () {
      final plain = Uri.parse('http://music.example.org:8080');
      expect(EncorePeopleApi.invitationAddress([plain, funnel], home), funnel);
      expect(EncorePeopleApi.invitationAddress([home], home), home);
    });

    test('whether a link works away from home', () {
      expect(EncorePeopleApi.worksAway(funnel), isTrue);
      expect(EncorePeopleApi.worksAway(home), isFalse);
      expect(EncorePeopleApi.worksAway(tailnet), isFalse);
    });
  });

  test('an owner is an owner who can invite and manage', () async {
    final me = (await people.me()).getOrThrow();

    expect(me.user, 'marwa');
    expect(
        (me.role, me.canInvite, me.canManage), (PersonRole.owner, true, true));
  });

  test('a member is a guest: no inviting, no managing', () async {
    server.myRole = 'member';

    final me = (await people.me()).getOrThrow();

    expect((me.role, me.canInvite, me.canManage),
        (PersonRole.guest, false, false));
  });

  test(
      'an invitation is a link to the server\'s own join address, with the code once',
      () async {
    final made = (await people.createInvite()).getOrThrow();

    expect(made.url, 'http://192.168.50.133:4540/encore/join/ABCD-EFGH-JK1');
    expect(made.role, PersonRole.guest);
    expect(server.inviteRows.single['role'], 'member');
    expect(
        made.expiresAt.isAfter(DateTime.fromMillisecondsSinceEpoch(0)), isTrue);
  });

  test('an owner can invite an owner, and the list shows state and who used it',
      () async {
    final first =
        (await people.createInvite(role: PersonRole.owner)).getOrThrow();
    await people.createInvite();
    server.inviteRows.last
      ..['state'] = 'used'
      ..['usedBy'] = 'sara';

    final rows = (await people.invites()).getOrThrow();

    expect(server.inviteRows.first['role'], 'owner');
    expect(rows.map((r) => (r.state, r.role, r.redeemedBy)), [
      ('open', PersonRole.owner, null),
      ('used', PersonRole.guest, 'sara'),
    ]);
    expect(rows.first.id, first.id);
  });

  test('an invitation can be taken back', () async {
    final made = (await people.createInvite()).getOrThrow();

    expect((await people.revokeInvite(made.id)).isOk, isTrue);

    expect(server.inviteRows.single['state'], 'revoked');
  });

  group('the people the owner sees', () {
    setUp(() {
      server.people.addAll([
        {
          'id': 'pn_000000000000000000000000a1',
          'username': 'marwa',
          'name': 'marwa',
          'role': 'owner',
          'locked': false,
          'devices': 2,
          'lastSeen': 1790000000000,
          'invitedBy': null,
          'createdAt': 1780000000000,
        },
        {
          'id': 'pn_000000000000000000000000b2',
          'username': 'sara',
          'name': 'Sara',
          'role': 'member',
          'locked': false,
          'devices': 1,
          'lastSeen': null,
          'invitedBy': 'marwa',
          'createdAt': 1785000000000,
        },
      ]);
    });

    test('are listed by user name, with who invited them', () async {
      final list = (await people.people()).getOrThrow();

      expect(list.map((p) => (p.user, p.role, p.invitedBy)), [
        ('marwa', PersonRole.owner, null),
        ('sara', PersonRole.guest, 'marwa'),
      ]);
    });

    test('a role is changed by name, without asking the list first', () async {
      expect((await people.setRole('sara', PersonRole.owner)).isOk, isTrue);

      expect(server.people.last['role'], 'owner');
    });

    test('a person is removed by name', () async {
      expect((await people.removePerson('sara')).isOk, isTrue);

      expect(server.people.map((p) => p['username']), ['marwa']);
    });

    test('somebody nobody has heard of is not found', () async {
      final result = await people.removePerson('nobody');

      expect(result.isErr, isTrue);
      expect(server.people, hasLength(2));
    });
  });

  test('there is no friend activity on this server yet, and nothing is shared',
      () async {
    expect((await people.friends()).getOrThrow(), isEmpty);
    expect((await people.setSharing(true)).isOk, isTrue);
    expect(
        (await people.report(const NowPlayingReport(
                title: 'Nude', artist: 'Radiohead', playing: true)))
            .isOk,
        isTrue);
    expect(server.calls.keys.where((k) => k.contains('activity')), isEmpty);
  });

  group('the link an invitation is sent as', () {
    const knownId = 'mw3am46w5weex4a4fqrc3avnua';

    test('carries the key of the server when the phone knows it', () {
      final link = EncorePeopleApi.joinLink(
          Uri.parse('https://encore-home.tail1234.ts.net'), 'ABCD-EFGH-JKLM',
          serverId: knownId);

      expect(link.toString(),
          'https://encore-home.tail1234.ts.net/encore/join/ABCD-EFGH-JKLM?id=$knownId');
    });

    test('has no query when the phone does not know a key yet', () {
      final link = EncorePeopleApi.joinLink(
          Uri.parse('http://192.168.1.50:4540'), 'ABCD-EFGH-JKLM');

      expect(link.toString(),
          'http://192.168.1.50:4540/encore/join/ABCD-EFGH-JKLM');
    });

    test('is read back by the app that receives it, key and all', () {
      final sent = EncorePeopleApi.joinLink(
          Uri.parse('https://encore-home.tail1234.ts.net'), 'ABCD-EFGH-JKLM',
          serverId: knownId);

      final received = findInviteLink('Come and listen: $sent')!;

      expect(received.serverId, knownId);
      expect(received.code, 'ABCD-EFGH-JKLM');
      expect(received.server, Uri.parse('https://encore-home.tail1234.ts.net'));
    });
  });
}
