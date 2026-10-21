import 'dart:async';

import 'package:encore/data/sync/endpoint_resolver.dart';
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
    expect(r.isReachable, isFalse);
  });

  test('says when the server becomes unreachable and when it is back',
      () async {
    var up = true;
    final r = EndpointResolver(
      candidates: [home],
      probe: (_) async => up,
      delay: (_) async {},
    );
    final told = <bool>[];
    r.reachability.listen(told.add);

    await r.resolve(); // reachable
    up = false;
    await r.resolve(); // not any more
    await r.resolve(); // still not: nothing new to tell
    up = true;
    await r.resolve();
    await Future<void>.delayed(Duration.zero);

    expect(told, [true, false, true]);
  });

  test('a request that works marks the server reachable again', () async {
    final r = EndpointResolver(
      candidates: [home],
      probe: (_) async => false,
      delay: (_) async {},
    );
    final told = <bool>[];
    r.reachability.listen(told.add);

    r.reportSuccess();
    await Future<void>.delayed(Duration.zero);

    expect(told, [true]);
  });

  test('at home: LAN answers first and wins', () async {
    final r = EndpointResolver(
      candidates: [home, tail],
      probe: (u) async => true,
      delay: (_) async {},
    );
    expect(await r.resolve(), home);
    expect(r.isReachable, isTrue);
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
    expect(r.isReachable, isFalse);
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
}
