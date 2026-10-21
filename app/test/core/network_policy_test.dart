import 'package:encore/core/network_policy.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('isPrivateHost', () {
    test('RFC1918, loopback, link-local', () {
      for (final h in [
        '10.0.0.5',
        '172.16.0.1',
        '172.31.255.254',
        '192.168.50.129',
        '127.0.0.1',
        '169.254.1.1',
      ]) {
        expect(isPrivateHost(h), isTrue, reason: h);
      }
    });

    test('Tailscale / CGNAT 100.64.0.0/10', () {
      expect(isPrivateHost('100.90.68.57'), isTrue);
      expect(isPrivateHost('100.64.0.1'), isTrue);
      expect(isPrivateHost('100.127.255.255'), isTrue);
      expect(isPrivateHost('100.128.0.1'), isFalse);
      expect(isPrivateHost('100.63.0.1'), isFalse);
    });

    test('boundaries of 172.16/12', () {
      expect(isPrivateHost('172.15.0.1'), isFalse);
      expect(isPrivateHost('172.32.0.1'), isFalse);
    });

    test('public addresses are not private', () {
      for (final h in ['8.8.8.8', '1.1.1.1', '93.184.216.34', '192.169.0.1']) {
        expect(isPrivateHost(h), isFalse, reason: h);
      }
    });

    test('hostnames', () {
      expect(isPrivateHost('localhost'), isTrue);
      expect(isPrivateHost('nas'), isTrue);
      expect(isPrivateHost('music.local'), isTrue);
      expect(isPrivateHost('host.tail1234.ts.net'), isTrue);
      expect(isPrivateHost('music.example.org'), isFalse);
      expect(isPrivateHost('evil-local.com'), isFalse);
    });

    test('ipv6', () {
      expect(isPrivateHost('::1'), isTrue);
      expect(isPrivateHost('fe80::1'), isTrue);
      expect(isPrivateHost('fd12:3456::1'), isTrue);
      expect(isPrivateHost('2001:db8::1'), isFalse);
    });

    test('malformed input is not private', () {
      expect(isPrivateHost(''), isFalse);
      expect(isPrivateHost('300.1.1.1'), isFalse);
      expect(isPrivateHost('1.2.3'), isFalse); // has dots, not an address
    });
  });

  group('cleartextProblem', () {
    test('http to a private host is fine', () {
      expect(cleartextProblem(Uri.parse('http://192.168.1.5:4533')), isNull);
      expect(cleartextProblem(Uri.parse('http://100.90.68.57:4533')), isNull);
    });
    test('http to a public host is refused', () {
      expect(
          cleartextProblem(Uri.parse('http://music.example.org')), isNotNull);
    });
    test('https is always fine', () {
      expect(cleartextProblem(Uri.parse('https://music.example.org')), isNull);
    });
  });
}
