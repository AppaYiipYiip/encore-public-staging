import 'dart:async';

import 'package:encore/data/sync/endpoint_resolver.dart';
import 'package:encore/domain/server_reachability.dart';
import 'package:flutter_test/flutter_test.dart';

ServerEndpoint _ep(String label, String url) =>
    ServerEndpoint(label: label, url: Uri.parse(url));

void main() {
  final home = _ep('Home', 'http://192.168.1.2:4533');
  final tail = _ep('Tailscale', 'http://100.90.68.57:4533');

  test('current is available immediately (first candidate)', () {
    final r = EndpointResolver(
      candidates: [home, tail],
      probe: (_) async => false,
      delay: (_) async {},
    );
    expect(r.current, home);
    expect(r.finding, ServerFinding.unknown,
        reason: 'nobody has looked yet: not "down"');
  });

  test('says when the server becomes unreachable and when it is back',
      () async {
    var up = true;
    final r = EndpointResolver(
      candidates: [home],
      probe: (_) async => up,
      delay: (_) async {},
    );
    final told = <ServerFinding>[];
    r.findings.listen(told.add);

    await r.resolve(); // reachable
    up = false;
    await r.resolve(); // not any more
    await r.resolve(); // still not: nothing new to tell
    up = true;
    await r.resolve();
    await Future<void>.delayed(Duration.zero);

    expect(told, [
      ServerFinding.answering,
      ServerFinding.silent,
      ServerFinding.answering
    ]);
  });

  test(
      'the server is found silent only after a look found nothing, not before the first look',
      () async {
    var up = false;
    final r = EndpointResolver(
      candidates: [home],
      probe: (_) async => up,
      delay: (_) async {},
    );
    expect(r.finding, ServerFinding.unknown,
        reason:
            'nobody has looked yet: a song tapped in the first second is not refused, and no row is greyed');

    await r.resolve();
    expect(r.finding, ServerFinding.silent,
        reason: 'the radio is on, nothing answers (4G without data)');

    r.invalidate();
    expect(r.finding, ServerFinding.unknown,
        reason:
            'the network changed: what was found at the old place says nothing about the new one, for EVERY reader (P1-17, docs/31 CN-4b)');

    await r.resolve();
    up = true;
    await r.resolve();
    expect(r.finding, ServerFinding.answering);

    up = false;
    await r.resolve();
    r.reportSuccess();
    expect(r.finding, ServerFinding.answering, reason: 'a request that worked');
  });

  test('a change of network is told, so every reader looks again', () async {
    final r = EndpointResolver(
      candidates: [home],
      probe: (_) async => true,
      delay: (_) async {},
    );
    await r.resolve();
    final told = <ServerFinding>[];
    r.findings.listen(told.add);

    r.invalidate();
    r.invalidate(); // nothing new the second time
    await Future<void>.delayed(Duration.zero);

    expect(told, [ServerFinding.unknown]);
  });

  test('a request that works marks the server reachable again', () async {
    final r = EndpointResolver(
      candidates: [home],
      probe: (_) async => false,
      delay: (_) async {},
    );
    final told = <ServerFinding>[];
    r.findings.listen(told.add);

    r.reportSuccess();
    await Future<void>.delayed(Duration.zero);

    expect(told, [ServerFinding.answering]);
  });

  test('at home: LAN answers first and wins', () async {
    final r = EndpointResolver(
      candidates: [home, tail],
      probe: (u) async => true,
      delay: (_) async {},
    );
    expect(await r.resolve(), home);
    expect(r.finding, ServerFinding.answering);
  });

  test('away from home: LAN fails, Tailscale wins and becomes current',
      () async {
    final r = EndpointResolver(
      candidates: [home, tail],
      probe: (u) async => u.host.startsWith('100.'),
      delay: (_) async {},
    );
    final changes = <ServerEndpoint>[];
    r.changes.listen(changes.add);

    expect(await r.resolve(), tail);
    expect(r.current, tail);
    await Future<void>.delayed(Duration.zero);
    expect(changes, [tail]);
  });

  test('a slow LAN does not delay a fast alternative beyond the stagger',
      () async {
    final lanGate = Completer<bool>();
    final started = <String>[];
    final r = EndpointResolver(
      candidates: [home, tail],
      probe: (u) {
        started.add(u.host);
        return u.host.startsWith('100.') ? Future.value(true) : lanGate.future;
      },
      delay: (_) async {}, // stagger elapses instantly in the test
    );

    final winner = await r.resolve();

    expect(winner, tail);
    expect(started, containsAll(['192.168.1.2', '100.90.68.57']));
    lanGate.complete(false); // let the pending probe finish cleanly
  });

  test('nothing reachable -> null and current is kept', () async {
    final r = EndpointResolver(
      candidates: [home, tail],
      probe: (_) async => false,
      delay: (_) async {},
    );
    expect(await r.resolve(), isNull);
    expect(r.current, home);
    expect(r.finding, ServerFinding.silent);
  });

  test('a probe that throws counts as failure', () async {
    final r = EndpointResolver(
      candidates: [home, tail],
      probe: (u) async {
        if (u == home.url) throw StateError('boom');
        return true;
      },
      delay: (_) async {},
    );
    expect(await r.resolve(), tail);
  });

  test('a hanging probe is cut off by the probe timeout', () async {
    final r = EndpointResolver(
      candidates: [home, tail],
      probe: (u) => u == home.url
          ? Completer<bool>().future // never completes
          : Future.value(true),
      probeTimeout: const Duration(milliseconds: 50),
      delay: (_) async {},
    );
    expect(await r.resolve(), tail);
  });

  test('concurrent resolve() calls share one race', () async {
    var probes = 0;
    final r = EndpointResolver(
      candidates: [home],
      probe: (_) async {
        probes++;
        return true;
      },
      delay: (_) async {},
    );
    final a = r.resolve();
    final b = r.resolve();
    expect(identical(a, b), isTrue);
    await Future.wait([a, b]);
    expect(probes, 1);
  });

  test('repeated failures re-resolve to the other endpoint', () async {
    var atHome = true;
    final r = EndpointResolver(
      candidates: [home, tail],
      probe: (u) async => atHome ? u == home.url : u == tail.url,
      delay: (_) async {},
    );
    await r.resolve();
    expect(r.current, home);

    atHome = false; // user walked out
    r.reportFailure();
    r.reportFailure(); // threshold reached -> background re-resolve
    await r.resolve(); // shares the in-flight race

    expect(r.current, tail);
  });

  test('success resets the failure counter', () async {
    var probes = 0;
    final r = EndpointResolver(
      candidates: [home],
      probe: (_) async {
        probes++;
        return true;
      },
      delay: (_) async {},
    );
    r.reportFailure();
    r.reportSuccess();
    r.reportFailure();
    await Future<void>.delayed(Duration.zero);
    expect(probes, 0, reason: 'only 1 consecutive failure at the end');
  });

  group('when an address must prove itself before anything is sent to it', () {
    EndpointResolver strict(List<ServerEndpoint> candidates,
            Future<bool> Function(Uri) probe) =>
        EndpointResolver(
          candidates: candidates,
          probe: probe,
          requireVerified: true,
          delay: (_) async {},
        );

    test('before the first race no request may go to any candidate', () {
      final r = strict([home, tail], (_) async => true);

      expect(r.currentUrl, EndpointResolver.unverifiedUrl);
      expect(r.currentUrl.host, endsWith('.invalid'),
          reason:
              'a name that can never be resolved: nothing leaves the phone');
      expect(r.isVerified, isFalse);
      expect(r.current, home,
          reason: 'the screen can still say which address it is trying');
    });

    test('once an address has proved itself, requests go to it', () async {
      final r = strict([home, tail], (base) async => base == tail.url);

      await r.resolve();

      expect(r.currentUrl, tail.url);
      expect(r.isVerified, isTrue);
    });

    test('an address that is not the server is never handed out, only asked',
        () async {
      final asked = <Uri>[];
      final r = strict([home], (base) async {
        asked.add(base);
        return false; // another server, or nobody: it did not prove anything
      });

      await r.resolve();

      expect(asked, [home.url]);
      expect(r.currentUrl, EndpointResolver.unverifiedUrl);
      expect(r.isVerified, isFalse);
    });

    test('a race that finds nothing takes back the address that worked before',
        () async {
      var theServerIsHere = true;
      final r = strict([home], (_) async => theServerIsHere);
      await r.resolve();
      expect(r.currentUrl, home.url);

      theServerIsHere =
          false; // another network: the same address is somebody else's
      await r.resolve();

      expect(r.currentUrl, EndpointResolver.unverifiedUrl,
          reason: 'the last good address is not used for anything any more');
    });

    test('a change of network stops requests until the next race has finished',
        () async {
      final r = strict([home], (_) async => true);
      await r.resolve();
      expect(r.currentUrl, home.url);

      r.invalidate();

      expect(r.currentUrl, EndpointResolver.unverifiedUrl);
      await r.resolve();
      expect(r.currentUrl, home.url);
    });

    test(
        'an address the server named is raced like any other and never trusted before it answers',
        () async {
      final away = _ep('Away', 'https://encore-home.tail1234.ts.net');
      final asked = <Uri>[];
      final r = strict([home], (base) async {
        asked.add(base);
        return base == away.url;
      });

      r.addCandidates([away, home]); // a known address is not added twice
      expect(r.candidates, [home, away]);
      expect(r.currentUrl, EndpointResolver.unverifiedUrl);
      await r.resolve();

      expect(asked.toSet(), {home.url, away.url});
      expect(r.currentUrl, away.url);
    });

    test(
        'without the requirement nothing changes: the first candidate is used at once',
        () {
      final r = EndpointResolver(
          candidates: [home], probe: (_) async => false, delay: (_) async {});

      expect(r.currentUrl, home.url);
      r.invalidate();
      expect(r.currentUrl, home.url);
    });
  });

  group('CN-11: an address that answers, but as another server (docs/31 O-6)',
      () {
    /// The probe says no to everything, and remembers which addresses said something wrong rather than nothing.
    EndpointResolver watching(List<ServerEndpoint> candidates,
        {Set<Uri> answeredWrong = const {},
        Future<bool> Function(Uri)? probe}) {
      return EndpointResolver(
        candidates: candidates,
        probe: probe ?? (_) async => false,
        requireVerified: true,
        anotherServers: () => answeredWrong,
        delay: (_) async {},
      );
    }

    test(
        'a race that finds nobody names the address that answered with another key, and tells',
        () async {
      final r = watching([home, tail], answeredWrong: {tail.url});
      final told = <Uri?>[];
      r.anotherServer.listen(told.add);
      expect(r.anotherServerAt, isNull, reason: 'nobody has looked yet');

      await r.resolve();
      await Future<void>.delayed(Duration.zero);

      expect(r.anotherServerAt, tail.url);
      expect(told, [tail.url]);
      expect(r.finding, ServerFinding.anotherServer);
    });

    test('nothing is named when the addresses simply did not answer', () async {
      final r = watching([home, tail]);

      await r.resolve();

      expect(r.anotherServerAt, isNull);
      expect(r.finding, ServerFinding.silent);
    });

    test(
        'a race that finds the server names nobody, even if another address answered wrongly',
        () async {
      final r = watching([home, tail],
          answeredWrong: {home.url}, probe: (base) async => base == tail.url);

      await r.resolve();

      expect(r.anotherServerAt, isNull,
          reason: 'the server is reachable: there is nothing to warn about');
      expect(r.finding, ServerFinding.answering);
    });

    test('it is told once, not at every look', () async {
      final r = watching([home], answeredWrong: {home.url});
      final told = <Uri?>[];
      r.anotherServer.listen(told.add);

      await r.resolve();
      await r.resolve();
      await r.resolve();
      await Future<void>.delayed(Duration.zero);

      expect(told, [home.url]);
    });

    test(
        'a change of network forgets it: what answered at the old place says nothing about the new one',
        () async {
      final r = watching([home], answeredWrong: {home.url});
      final told = <Uri?>[];
      r.anotherServer.listen(told.add);
      await r.resolve();

      r.invalidate();
      await Future<void>.delayed(Duration.zero);

      expect(r.anotherServerAt, isNull);
      expect(told, [home.url, null]);
    });
  });
}
