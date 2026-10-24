import 'package:encore/domain/invite_link.dart';
import 'package:flutter_test/flutter_test.dart';

/// The link a person is sent to join a server (docs/39 F3): the address of the
/// server and a one-time code, in an https link that also opens in a browser
/// for someone without the app. The app reads it out of whatever was pasted,
/// shared or tapped, so nobody has to find the link inside a message.
void main() {
  test('reads the server and the code out of the link', () {
    final link = findInviteLink(
        'https://music.tail5678.ts.net/people/join/IqMYRj6XmYveHr0wi_CBynQTorIqyclW');

    expect(link!.server, Uri.parse('https://music.tail5678.ts.net'));
    expect(link.code, 'IqMYRj6XmYveHr0wi_CBynQTorIqyclW');
  });

  test('finds it in the middle of a message, with what comes after', () {
    final link = findInviteLink('Come and listen with me! Join here: '
        'https://music.example.org/people/join/abc123-XYZ_9. See you there');

    expect(link!.code, 'abc123-XYZ_9');
    expect(link.server.host, 'music.example.org');
  });

  test('keeps a port and a path in front of the people service', () {
    final a = findInviteLink('http://192.168.1.10:8702/join/Code123');
    final b =
        findInviteLink('https://example.org:8443/tunnel/people/join/Code456');

    expect(a!.server, Uri.parse('http://192.168.1.10:8702'));
    expect(a.code, 'Code123');
    expect(b!.server, Uri.parse('https://example.org:8443/tunnel'));
    expect(b.code, 'Code456');
  });

  test('is not fooled by other links or by nothing', () {
    expect(findInviteLink(''), isNull);
    expect(findInviteLink('https://example.org/people/join/'), isNull);
    expect(findInviteLink('https://example.org/watch?v=123'), isNull);
    expect(findInviteLink('encore://connect?server=http%3A%2F%2Fx'), isNull,
        reason: 'a setup link is another thing');
  });

  test('a link to a server over plain http on the internet is refused', () {
    // The invitation page takes a password: never over plain http to an
    // address on the internet (the rule of the rest of the app).
    expect(
        findInviteLink('http://music.example.org/people/join/Code123'), isNull);
    expect(findInviteLink('http://192.168.1.10:8702/join/Code123'), isNotNull,
        reason: 'at home it is fine');
  });

  test('the address of the redeeming calls', () {
    final link =
        findInviteLink('https://music.example.org/people/join/Code123')!;

    expect(link.infoUrl.toString(),
        'https://music.example.org/people/join/Code123/info');
    expect(link.redeemUrl.toString(),
        'https://music.example.org/people/join/Code123/redeem');
  });

  group('pointsAt', () {
    final link =
        findInviteLink('https://music.example.org/encore/join/ABCD-EFGH-JKLM')!;

    test('the same server by host and port', () {
      expect(link.pointsAt([Uri.parse('https://music.example.org')]), isTrue);
      expect(
          link.pointsAt([Uri.parse('https://MUSIC.example.org:443/')]), isTrue,
          reason: 'case and the default port do not matter');
    });

    test('another host or another port is another server', () {
      expect(link.pointsAt([Uri.parse('https://other.example.org')]), isFalse);
      expect(link.pointsAt([Uri.parse('https://music.example.org:8443')]),
          isFalse);
      expect(link.pointsAt(const []), isFalse);
    });

    test('one of several addresses is enough', () {
      expect(
          link.pointsAt([
            Uri.parse('http://192.168.1.10:4533'),
            Uri.parse('https://music.example.org'),
          ]),
          isTrue);
    });
  });

  group('the key of the server in the link (docs/11 ADR-R40)', () {
    const knownId = 'mw3am46w5weex4a4fqrc3avnua';

    test('a link made by an Encore server carries the key and the code', () {
      final link = findInviteLink(
          'Join me: http://192.168.1.50:4540/encore/join/ABCD-EFGH-JKLM?id=$knownId and see you there')!;

      expect(link.encore, isTrue);
      expect(link.code, 'ABCD-EFGH-JKLM');
      expect(link.serverId, knownId);
      expect(link.server, Uri.parse('http://192.168.1.50:4540'));
    });

    test('an older link has no key and is still a link', () {
      final link = findInviteLink(
          'http://192.168.1.50:4540/encore/join/ABCD-EFGH-JKLM')!;

      expect(link.serverId, isNull);
    });

    test(
        'a link that names a key badly is refused, not read as a link without one',
        () {
      for (final bad in [
        '',
        'short',
        'UPPERCASEUPPERCASEUPPERCASE',
        '${knownId}x',
        knownId.substring(1)
      ]) {
        expect(
            findInviteLink(
                'http://192.168.1.50:4540/encore/join/ABCD-EFGH-JKLM?id=$bad'),
            isNull,
            reason: 'id "$bad"');
      }
    });

    test('the key makes two links different', () {
      final a = findInviteLink(
          'http://192.168.1.50:4540/encore/join/CODE1?id=$knownId')!;
      final b = findInviteLink('http://192.168.1.50:4540/encore/join/CODE1')!;

      expect(a, isNot(b));
    });

    test('only an Encore link carries a key; the other forms ignore a stray id',
        () {
      final link = findInviteLink(
          'https://music.example/people/join/Code123?id=$knownId')!;

      expect(link.serverId, isNull);
    });
  });
}
