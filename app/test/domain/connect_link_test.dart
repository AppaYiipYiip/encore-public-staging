import 'package:encore/domain/connect_link.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('a setup link', () {
    test('survives being written and read back', () {
      const link = ConnectLink(
        server: 'http://192.168.50.129:4533',
        away: 'https://music.tailnet-name.ts.net',
        name: "Marwa's music",
        user: 'sara',
      );
      expect(findConnectLink(link.toLink()), link);
    });

    test('is found inside a whole message that was copied', () {
      const link = ConnectLink(server: 'http://192.168.1.50:4533');
      final found = findConnectLink(link.toInvite());
      expect(found, link);
    });

    test('keeps working when a chat app adds punctuation after it', () {
      final found = findConnectLink(
          'Here you go: encore://connect?server=http%3A%2F%2F10.0.0.5%3A4533.');
      expect(found?.server, 'http://10.0.0.5:4533');
    });

    test('has no secret in it', () {
      final text = const ConnectLink(
        server: 'http://192.168.1.50:4533',
        user: 'sara',
      ).toLink();
      expect(text, isNot(contains('pass')));
      expect(text, isNot(contains('token')));
    });
  });

  group('what else can be pasted', () {
    test('a lone address is an address', () {
      expect(findConnectLink('192.168.1.10:4533')?.server, '192.168.1.10:4533');
      expect(findConnectLink('  http://nas.local/music  ')?.server,
          'http://nas.local/music');
      expect(findConnectLink('https://music.example.org')?.server,
          'https://music.example.org');
    });

    test('nothing usable is nothing', () {
      expect(findConnectLink(''), isNull);
      expect(findConnectLink('hello, here is the thing'), isNull);
      expect(findConnectLink('encore://connect?name=x'), isNull,
          reason: 'no server in it');
      expect(findConnectLink('encore://connect?server='), isNull);
    });

    test(
        'a long message with a link inside still finds the link, not an '
        'address in the prose', () {
      final found = findConnectLink(
          'Hi! My server is at home (192.168.1.50:4533). Use this: '
          'encore://connect?server=http%3A%2F%2F192.168.1.50%3A4533&user=sara');
      expect(found?.server, 'http://192.168.1.50:4533');
      expect(found?.user, 'sara');
    });

    test('the link the invitation page builds is understood', () {
      // The page (server/encore-people) makes it with encodeURIComponent: the
      // address, the server's name (a space is %20) and the new account's name.
      final found = findConnectLink('encore://connect?server='
          'https%3A%2F%2Fmusic.tail5678.ts.net&name=Home%20music&user=ben');

      expect(found?.server, 'https://music.tail5678.ts.net');
      expect(found?.name, 'Home music');
      expect(found?.user, 'ben');
    });
  });
}
