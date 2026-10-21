import 'package:encore/core/server_url.dart';
import 'package:encore/data/auth/server_setup_service.dart';
import 'package:encore/data/sync/endpoint_resolver.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('canonicalBaseUrl', () {
    test('has no query or fragment marks at all', () {
      final url = canonicalBaseUrl(Uri.parse('http://192.168.50.129:4533?#'));
      expect(url.toString(), 'http://192.168.50.129:4533');
    });

    test('drops trailing slashes but keeps a sub-path', () {
      expect(
          canonicalBaseUrl(Uri.parse('https://nas.example.org/navidrome///'))
              .toString(),
          'https://nas.example.org/navidrome');
    });

    test('keeps credentials-free host and explicit port', () {
      expect(canonicalBaseUrl(Uri.parse('http://music.lan:8080/')).toString(),
          'http://music.lan:8080');
    });

    test('string concatenation with a REST path stays a real path', () {
      final base = canonicalBaseUrl(Uri.parse('http://host:4533?#'));
      final url = Uri.parse('$base/rest/stream?id=1');
      expect(url.path, '/rest/stream');
      expect(url.queryParameters['id'], '1');
      expect(url.fragment, isEmpty);
    });
  });

  group('what the user types', () {
    test('normalizeUrl produces a clean base', () {
      expect(ServerSetupService.normalizeUrl('192.168.1.5:4533')!.toString(),
          'http://192.168.1.5:4533');
      expect(
          ServerSetupService.normalizeUrl(' http://nas.local/navidrome/ ')!
              .toString(),
          'http://nas.local/navidrome');
    });

    test('a stored endpoint from an older build is repaired on load', () {
      final e = ServerEndpoint.fromJson(
          {'label': 'Home', 'url': 'http://192.168.50.129:4533?#'});
      expect(e.url.toString(), 'http://192.168.50.129:4533');
    });
  });

  group('the name given to the first address', () {
    // A friend signed in with the public address and the Your server page called
    // it "Home" (2026-10-17): it is not home, it is the door from anywhere.
    test('a home-network address is Home', () {
      expect(
          ServerSetupService.firstAddressLabel(
              Uri.parse('http://192.168.1.10:4533')),
          'Home');
      expect(
          ServerSetupService.firstAddressLabel(Uri.parse('http://nas.local')),
          'Home');
    });

    test('an https address is "Server", not "Home"', () {
      expect(
          ServerSetupService.firstAddressLabel(
              Uri.parse('https://music.tail5678.ts.net')),
          'Server');
    });
  });
}
