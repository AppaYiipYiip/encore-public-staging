import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:encore/data/requests/portal_discovery.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_http.dart';

/// Throws what Dart throws when nothing listens on the port.
class _RefusedAdapter implements HttpClientAdapter {
  @override
  Future<ResponseBody> fetch(RequestOptions options,
      Stream<Uint8List>? requestStream, Future<void>? cancelFuture) {
    throw DioException(
      requestOptions: options,
      type: DioExceptionType.connectionError,
      error: const SocketException('Connection refused',
          osError: OSError('Connection refused', 111)),
    );
  }

  @override
  void close({bool force = false}) {}
}

Dio _dioWith(HttpClientAdapter adapter) => Dio()..httpClientAdapter = adapter;

void main() {
  group('PortalProbe.classify', () {
    test('the portal without a session is recognised', () {
      final r = PortalProbe.classify(401, '{"error": "sign in"}');
      expect(r.verdict, ProbeVerdict.service);
      expect(r.statusCode, 401);
    });

    test('the signed-in overview is recognised too', () {
      expect(
          PortalProbe.classify(200, '{"user":"marwa","imports":[]}').isService,
          isTrue);
    });

    test('a web page is "something else", with the reason', () {
      final r = PortalProbe.classify(200, '<!doctype html><html></html>');
      expect(r.verdict, ProbeVerdict.other);
      expect(r.reason, 'page');
    });

    test('JSON that is not the portal, or the wrong status, is not accepted',
        () {
      expect(
          PortalProbe.classify(200, '{"foo":1}').verdict, ProbeVerdict.other);
      expect(PortalProbe.classify(404, '{"error":"not found"}').verdict,
          ProbeVerdict.other);
      expect(PortalProbe.classify(500, '').reason, 'status');
    });
  });

  group('PortalProbe.probe', () {
    test('asks /api/me once, with no cookie and no query', () async {
      final adapter = FakeHttpAdapter(routes: {
        '/api/me': (r) =>
            const FakeResponse.json({'error': 'sign in'}, status: 401),
      });
      final result = await PortalProbe(dio: _dioWith(adapter))
          .probe(Uri.parse('http://192.168.50.113:8700'));
      expect(result.isService, isTrue);
      expect(adapter.requests, hasLength(1));
      expect(adapter.requests.single.method, 'GET');
      expect(adapter.requests.single.uri.path, '/api/me');
      expect(adapter.requests.single.uri.query, isEmpty);
    });

    test('keeps a base path (a reverse proxy in front of the service)',
        () async {
      final adapter = FakeHttpAdapter(routes: {
        '/portal/api/me': (r) =>
            const FakeResponse.json({'error': 'sign in'}, status: 401),
      });
      final result = await PortalProbe(dio: _dioWith(adapter))
          .probe(Uri.parse('https://home.example.org/portal/'));
      expect(result.isService, isTrue);
    });

    test('a refused connection is "silent: refused"', () async {
      final result = await PortalProbe(dio: _dioWith(_RefusedAdapter()))
          .probe(Uri.parse('http://192.168.50.129:8700'));
      expect(result.verdict, ProbeVerdict.silent);
      expect(result.reason, 'refused');
    });

    test('any other connection failure is "silent: unreachable"', () async {
      final adapter = FakeHttpAdapter(routes: {
        '/api/me': (r) => const FakeResponse.connectionError(),
      });
      final result = await PortalProbe(dio: _dioWith(adapter))
          .probe(Uri.parse('http://10.0.0.9:8700'));
      expect(result.verdict, ProbeVerdict.silent);
      expect(result.reason, 'unreachable');
    });
  });

  group('PortalDiscovery.nearbyAddresses', () {
    final home = Uri.parse('http://192.168.50.129:4533');
    final away = Uri.parse('http://100.90.68.57:4533');

    test('saved first, then every server host on the usual port', () {
      final list = PortalDiscovery.nearbyAddresses(
        [home, away],
        saved: Uri.parse('http://192.168.50.113:8700'),
      );
      expect(list.map((u) => u.toString()), [
        'http://192.168.50.113:8700',
        'http://192.168.50.129:8700',
        'http://100.90.68.57:8700',
      ]);
    });

    test('no duplicates, and the saved address is not asked twice', () {
      final list = PortalDiscovery.nearbyAddresses(
        [home, Uri.parse('http://192.168.50.129:4534')],
        saved: Uri.parse('http://192.168.50.129:8700'),
      );
      expect(list.map((u) => u.toString()), ['http://192.168.50.129:8700']);
    });

    test('a public host is asked over https only', () {
      final list = PortalDiscovery.nearbyAddresses(
          [Uri.parse('https://music.example.org')]);
      expect(list.single.toString(), 'https://music.example.org:8700');
    });

    test('several ports multiply the candidates', () {
      final list = PortalDiscovery.nearbyAddresses([home], ports: [8700, 8701]);
      expect(list.map((u) => u.port), [8700, 8701]);
    });
  });

  group('PortalDiscovery.subnetHosts', () {
    test('253 other hosts of a home /24', () {
      final hosts = PortalDiscovery.subnetHosts('192.168.50.129');
      expect(hosts, hasLength(253));
      expect(hosts.first, '192.168.50.1');
      expect(hosts.last, '192.168.50.254');
      expect(hosts, isNot(contains('192.168.50.129')));
    });

    test('addresses that were already asked are skipped', () {
      final hosts = PortalDiscovery.subnetHosts('10.1.2.3',
          except: {'10.1.2.113', '10.1.2.129'});
      expect(hosts, hasLength(251));
      expect(hosts, isNot(contains('10.1.2.113')));
    });

    test('public, CGNAT, names and junk are never scanned', () {
      expect(PortalDiscovery.subnetHosts('8.8.8.8'), isEmpty);
      expect(PortalDiscovery.subnetHosts('100.90.68.57'), isEmpty);
      expect(PortalDiscovery.subnetHosts('nas.local'), isEmpty);
      expect(PortalDiscovery.subnetHosts('192.168.1'), isEmpty);
      expect(PortalDiscovery.subnetHosts('192.168.1.300'), isEmpty);
    });

    test('the 172.16/12 block counts, 172.32 does not', () {
      expect(PortalDiscovery.subnetHosts('172.20.0.5'), isNotEmpty);
      expect(PortalDiscovery.subnetHosts('172.32.0.5'), isEmpty);
    });
  });

  group('PortalDiscovery.searchNetwork', () {
    PortalProbe probeFor(Set<String> serviceHosts) {
      final adapter = FakeHttpAdapter(routes: {
        '/api/me': (r) => serviceHosts.contains(r.uri.host)
            ? const FakeResponse.json({'error': 'sign in'}, status: 401)
            : const FakeResponse.json('<html></html>'),
      });
      return PortalProbe(dio: _dioWith(adapter));
    }

    test('finds the service on another machine of the network', () async {
      final progress = <int>[];
      final discovery = PortalDiscovery(
        probe: probeFor({'192.168.50.113'}),
        tcpOpen: (host, port, timeout) async =>
            host == '192.168.50.113' || host == '192.168.50.40',
      );
      final found = await discovery.searchNetwork(
        Uri.parse('http://192.168.50.129:4533'),
        onProgress: (done, total) => progress.add(done),
      );
      expect(found.map((u) => u.toString()), ['http://192.168.50.113:8700']);
      expect(progress.last, 253);
    });

    test('never opens more than the allowed number of connections at once',
        () async {
      var inFlight = 0;
      var peak = 0;
      final discovery = PortalDiscovery(
        probe: probeFor({}),
        concurrency: 8,
        tcpOpen: (host, port, timeout) async {
          inFlight++;
          if (inFlight > peak) peak = inFlight;
          await Future<void>.delayed(Duration.zero);
          inFlight--;
          return false;
        },
      );
      await discovery.searchNetwork(Uri.parse('http://192.168.50.129:4533'));
      expect(peak, lessThanOrEqualTo(8));
      expect(peak, greaterThan(1));
    });

    test('a public address is not searched at all', () async {
      var asked = 0;
      final discovery = PortalDiscovery(
        probe: probeFor({}),
        tcpOpen: (h, p, t) async {
          asked++;
          return false;
        },
      );
      final found =
          await discovery.searchNetwork(Uri.parse('https://music.example.org'));
      expect(found, isEmpty);
      expect(asked, 0);
    });

    test('can be cancelled part-way', () async {
      var asked = 0;
      final discovery = PortalDiscovery(
        probe: probeFor({'192.168.50.113'}),
        concurrency: 4,
        tcpOpen: (h, p, t) async {
          asked++;
          return h == '192.168.50.113';
        },
      );
      final found = await discovery.searchNetwork(
        Uri.parse('http://192.168.50.129:4533'),
        isCancelled: () => asked >= 20,
      );
      expect(found, isEmpty);
      expect(asked, lessThan(40));
    });
  });

  group('mayReuseServerLogin', () {
    final endpoints = [
      Uri.parse('http://192.168.50.129:4533'),
      Uri.parse('https://music.example.org'),
    ];

    test('the music server\'s own machine, whatever the port', () {
      expect(
          mayReuseServerLogin(
              Uri.parse('http://192.168.50.129:8700'), endpoints),
          isTrue);
      expect(
          mayReuseServerLogin(
              Uri.parse('https://music.example.org:8700'), endpoints),
          isTrue);
    });

    test('another private machine of the home network or the tailnet', () {
      for (final host in [
        '192.168.50.113',
        '10.0.0.4',
        '172.16.5.5',
        '100.90.68.57',
        'nas',
        'box.local',
        'host.tail1234.ts.net'
      ]) {
        expect(
            mayReuseServerLogin(
                Uri(scheme: 'http', host: host, port: 8700), endpoints),
            isTrue,
            reason: host);
      }
    });

    test('a public host that is not the music server gets no password', () {
      expect(
          mayReuseServerLogin(
              Uri.parse('https://portal.example.net'), endpoints),
          isFalse);
      expect(mayReuseServerLogin(Uri.parse('http://8.8.8.8:8700'), endpoints),
          isFalse);
    });
  });
}
