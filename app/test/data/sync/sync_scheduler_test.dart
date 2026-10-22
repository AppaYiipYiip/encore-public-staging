import 'dart:async';

import 'package:drift/native.dart';
import 'package:encore/core/clock.dart';
import 'package:encore/data/api/opensubsonic/opensubsonic_client.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/sync/endpoint_resolver.dart';
import 'package:encore/data/sync/sync_engine.dart';
import 'package:encore/data/sync/sync_scheduler.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_http.dart';
import '../../support/fake_subsonic_server.dart';

/// Deterministic timer: callbacks run only when the test says so.
class _ManualTimers {
  final List<_ManualTimer> active = [];

  Timer create(Duration delay, void Function() cb) {
    final t = _ManualTimer(delay, cb);
    active.add(t);
    return t;
  }

  _ManualTimer? get latestLive {
    final live = active.where((t) => !t.cancelled && !t.fired).toList();
    return live.isEmpty ? null : live.last;
  }
}

class _ManualTimer implements Timer {
  _ManualTimer(this.delay, this._cb);
  final Duration delay;
  final void Function() _cb;
  bool cancelled = false;
  bool fired = false;

  void fire() {
    fired = true;
    _cb();
  }

  @override
  void cancel() => cancelled = true;
  @override
  bool get isActive => !cancelled && !fired;
  @override
  int get tick => 0;
}

void main() {
  late AppDatabase db;
  late Future<void> Function() fireLatest;
  late FakeSubsonicServer server;
  late SyncEngine engine;
  late EndpointResolver endpoints;
  late _ManualTimers timers;
  late SyncScheduler scheduler;
  late FakeClock clock;

  setUp(() async {
    db = AppDatabase(NativeDatabase.memory());
    final serverId = await db.into(db.servers).insert(ServersCompanion.insert(
          name: 'T',
          username: 'u',
          endpointsJson: '[]',
          createdAtMs: 0,
        ));
    server = FakeSubsonicServer()..seed(songCount: 10, albumCount: 2);
    clock = FakeClock(DateTime.utc(2026, 10, 14, 12));
    final client = OpenSubsonicClient(
      dio: fakeDio(server.adapter),
      baseUrl: () => Uri.parse('http://fake:4533'),
      credentials: const SubsonicCredentials(username: 'u', password: 'p'),
    );
    engine =
        SyncEngine(db: db, client: client, serverId: serverId, clock: clock);
    endpoints = EndpointResolver(
      candidates: [
        ServerEndpoint(label: 'Home', url: Uri.parse('http://fake:4533')),
      ],
      probe: (_) async => true,
      delay: (_) async {},
    );
    timers = _ManualTimers();
    scheduler = SyncScheduler(
      engine: engine,
      endpoints: endpoints,
      clock: clock,
      timerFactory: timers.create,
    );
    // Fires the newest pending timer, then waits until the scheduler settles
    // (the sync itself is real async work against the in-memory database).
    fireLatest = () async {
      final live = timers.active.where((t) => !t.cancelled && !t.fired);
      expect(live, isNotEmpty, reason: 'no pending timer to fire');
      live.last.fire();
      final deadline = DateTime.now().add(const Duration(seconds: 5));
      do {
        await Future<void>.delayed(const Duration(milliseconds: 5));
      } while (scheduler.status.isSyncing && DateTime.now().isBefore(deadline));
    };
  });

  tearDown(() async {
    await scheduler.dispose();
    await engine.dispose();
    await db.close();
  });

  test('start() syncs after the start delay, not before', () async {
    scheduler.start();
    expect(server.adapter.requests, isEmpty);
    expect(timers.latestLive!.delay, const Duration(seconds: 2));

    await fireLatest();

    expect(server.adapter.count('getScanStatus'), 1);
    expect(scheduler.status.initialSyncDone, isTrue);
    expect(scheduler.status.lastFailure, isNull);
    expect(scheduler.status.isSyncing, isFalse);
  });

  test('after success the next foreground check is queued (10 min)', () async {
    scheduler.start();
    await fireLatest();

    expect(timers.latestLive!.delay, const Duration(minutes: 10));
  });

  test('resume within the gap does nothing; after the gap it syncs', () async {
    scheduler.start();
    await fireLatest();
    server.adapter.requests.clear();

    scheduler.onBackground();
    clock.advance(const Duration(minutes: 1));
    scheduler.onForeground();
    expect(timers.latestLive, isNull, reason: 'too soon after last attempt');

    scheduler.onBackground();
    clock.advance(const Duration(minutes: 10));
    scheduler.onForeground();
    await fireLatest();
    expect(server.adapter.count('getScanStatus'), 1);
  });

  test('regaining connectivity triggers a debounced sync', () async {
    scheduler.onConnectivityChanged(online: false);
    scheduler.onConnectivityChanged(online: true);

    expect(timers.latestLive!.delay, const Duration(seconds: 2));
    await fireLatest();
    expect(server.adapter.count('getScanStatus'), 1);
  });

  test('network failure -> retry with exponential backoff, capped', () async {
    server.adapter.routes['getScanStatus'] =
        (_) => const FakeResponse.connectionError();
    scheduler.start();
    await fireLatest();

    expect(scheduler.status.lastFailure, isNotNull);
    expect(scheduler.status.initialSyncDone, isFalse);
    expect(timers.latestLive!.delay, const Duration(seconds: 30));

    await fireLatest();
    expect(timers.latestLive!.delay, const Duration(seconds: 60));
    await fireLatest();
    expect(timers.latestLive!.delay, const Duration(seconds: 120));

    for (var i = 0; i < 10; i++) {
      await fireLatest();
    }
    expect(timers.latestLive!.delay, const Duration(minutes: 15));
  });

  test('auth failure is not retried automatically', () async {
    server.adapter.routes['getScanStatus'] =
        (_) => FakeResponse.json(subsonicError(40, 'Wrong password'));
    scheduler.start();
    await fireLatest();

    expect(scheduler.status.lastFailure, isNotNull);
    expect(timers.latestLive, isNull);
  });

  test('a rejection that a quick retry cannot fix keeps the normal rhythm',
      () async {
    // Code 50 (not authorised) on the library dump: not a network problem, not
    // a credentials problem, not retryable. The scheduler used to schedule
    // nothing after it, so periodic syncing stopped until the app was resumed
    // after five minutes (docs/23, B4).
    final healthy = server.adapter.routes['getArtists']!;
    server.adapter.routes['getArtists'] =
        (_) => FakeResponse.json(subsonicError(50, 'Not authorised'));
    scheduler.start();
    await fireLatest();

    expect(scheduler.status.lastFailure, isNotNull);
    expect(timers.latestLive, isNotNull,
        reason: 'the next foreground check must still be queued');
    expect(timers.latestLive!.delay, const Duration(minutes: 10),
        reason: 'the normal interval, not a fast retry that cannot succeed');

    // And it heals by itself once the server stops rejecting.
    server.adapter.routes['getArtists'] = healthy;
    await fireLatest();
    expect(scheduler.status.lastFailure, isNull);
    expect(scheduler.status.initialSyncDone, isTrue);
  });

  test('background cancels pending work (no timers while screen is off)',
      () async {
    scheduler.start();
    await fireLatest();
    expect(timers.latestLive, isNotNull);

    scheduler.onBackground();

    expect(timers.latestLive, isNull);
  });

  test('following the server is an explicit request that reaches the engine',
      () async {
    // The shrink guard holds a far smaller answer back until the person says
    // "follow the server" (docs/23, B6). That choice must travel from the
    // button through the scheduler to the engine.
    server.seed(songCount: 120, albumCount: 3);
    scheduler.start();
    await fireLatest();
    Future<int> live() async =>
        (await (db.select(db.tracks)..where((t) => t.deletedAtMs.isNull()))
                .get())
            .length;
    expect(await live(), 120);

    server.songs = [];
    scheduler.requestSync(force: true);
    await fireLatest();
    expect(await live(), 120, reason: 'an empty answer alone is not believed');

    scheduler.requestSync(force: true, acceptShrink: true);
    await fireLatest();
    expect(await live(), 0, reason: 'the person chose to follow the server');
  });

  test('manual request runs immediately and can force a full dump', () async {
    scheduler.start();
    await fireLatest();
    server.adapter.requests.clear();

    scheduler.requestSync(force: true);
    expect(timers.latestLive!.delay, Duration.zero);
    await fireLatest();

    expect(server.adapter.count('search3'), greaterThan(0));
  });

  // R-16 / ADR-071 layer L1: while the app is open it checks for changes made on
  // other devices every few seconds, cheaply, and stops when it goes away.
  group('live probe', () {
    late _ManualTimers probeTimers;
    late SyncScheduler live;

    setUp(() {
      probeTimers = _ManualTimers();
      live = SyncScheduler(
        engine: engine,
        endpoints: endpoints,
        clock: clock,
        timerFactory: timers.create,
        probeTimerFactory: probeTimers.create,
        liveProbe: true,
      );
    });

    tearDown(() => live.dispose());

    Future<void> settleLive() async {
      final deadline = DateTime.now().add(const Duration(seconds: 5));
      do {
        await Future<void>.delayed(const Duration(milliseconds: 5));
      } while ((live.isProbing || live.status.isSyncing) &&
          DateTime.now().isBefore(deadline));
    }

    Future<void> fireFull() async {
      final pending = timers.active.where((t) => !t.cancelled && !t.fired);
      expect(pending, isNotEmpty, reason: 'no full-pass timer to fire');
      pending.last.fire();
      await settleLive();
    }

    Future<void> fireProbe() async {
      final pending = probeTimers.active.where((t) => !t.cancelled && !t.fired);
      expect(pending, isNotEmpty, reason: 'no probe timer to fire');
      pending.last.fire();
      await settleLive();
    }

    Future<void> firstSyncDone() async {
      live.start();
      await fireFull();
      expect(live.status.initialSyncDone, isTrue);
      server.adapter.requests.clear();
    }

    Duration? nextProbe() => probeTimers.latestLive?.delay;

    List<String> methods() =>
        server.adapter.requests.map((r) => r.apiMethod).toList();

    test('no probing before the first sync has finished', () async {
      live.start();
      expect(nextProbe(), isNull);
      live.poke();
      expect(nextProbe(), isNull);
    });

    test('it probes every 3 s once the first sync is done', () async {
      await firstSyncDone();
      expect(nextProbe(), const Duration(seconds: 3));

      await fireProbe();

      expect(methods(), ['getScanStatus', 'getPlaylists'],
          reason: 'two small requests, never the library dump');
      expect(nextProbe(), const Duration(seconds: 3));
    });

    test(
        'the cadence leaves room for the work after a probe inside the 5 s '
        'budget (R-16, B40)', () async {
      // Measured 2026-10-16: a change shows after (the wait for the next probe
      // + about 2 s to fetch, write and draw on the cheap-phone emulator).
      // With the old 5 s wait the worst case was 7.4 s against a 5 s budget.
      const budget = Duration(seconds: 5);
      const fetchWriteDraw = Duration(seconds: 2);
      await firstSyncDone();
      expect(nextProbe()! + fetchWriteDraw, lessThanOrEqualTo(budget));
    });

    test('on mobile data it probes every 30 s', () async {
      live.setMetered(true);
      await firstSyncDone();

      expect(nextProbe(), const Duration(seconds: 30));
    });

    test(
        'after two quiet minutes it slows to 20 s, and a poke snaps back to 3 s',
        () async {
      await firstSyncDone();
      for (var i = 0; i < 39; i++) {
        await fireProbe();
      }
      expect(nextProbe(), const Duration(seconds: 3),
          reason: 'still quick before the 40th unchanged probe');
      await fireProbe();
      expect(nextProbe(), const Duration(seconds: 20));

      clock.advance(const Duration(seconds: 3));
      live.poke();
      expect(nextProbe(), Duration.zero, reason: 'probe now');
      await fireProbe();
      expect(nextProbe(), const Duration(seconds: 3),
          reason: 'back to the short cadence after a touch');
    });

    test('a poke probes now, but not more often than every 2 s', () async {
      await firstSyncDone();
      await fireProbe(); // a probe just ran

      live.poke();

      expect(nextProbe(), const Duration(seconds: 3),
          reason: 'too soon after the last probe: keep the normal timer');
      clock.advance(const Duration(seconds: 3));
      live.poke();
      expect(nextProbe(), Duration.zero);
    });

    test('it stays quiet in the background and probes at once on resume',
        () async {
      await firstSyncDone();

      live.onBackground();
      expect(nextProbe(), isNull, reason: 'no probing with the screen off');

      live.onForeground();
      expect(nextProbe(), Duration.zero);
    });

    test('it does not probe while offline', () async {
      await firstSyncDone();
      live.onConnectivityChanged(online: false);

      await fireProbe();

      expect(server.adapter.requests, isEmpty);
      expect(nextProbe(), isNotNull, reason: 'it keeps checking the clock');
    });

    test('a probe that finds an edit updates the playlist and stays quick',
        () async {
      server.playlists = [
        FakeSubsonicServer.playlist('p1', 'Mine',
            songIds: ['s1'], library: server.songs),
      ];
      await firstSyncDone();
      server.playlists = [
        FakeSubsonicServer.playlist('p1', 'Mine',
            songIds: ['s1', 's2'],
            changed: '2026-10-16T12:00:00Z',
            library: server.songs),
      ];

      await fireProbe();

      final entries = await db.select(db.playlistEntries).get();
      expect(entries.map((e) => e.trackId).toSet(), {'s1', 's2'});
      expect(nextProbe(), const Duration(seconds: 3));
    });

    test('a probe that finds a changed library asks for a normal pass',
        () async {
      await firstSyncDone();
      server.lastScan = '2026-10-16T13:00:00.000000000Z';
      clock.advance(
          const Duration(hours: 2)); // past the gap between library passes

      await fireProbe();
      expect(server.adapter.count('search3'), 0,
          reason: 'the probe never dumps');

      await fireFull();
      expect(server.adapter.count('search3'), greaterThan(0),
          reason: 'the normal pass re-read the library');
      expect(nextProbe(), const Duration(seconds: 3),
          reason: 'probing resumes after the pass');
    });

    test('connectivity regained in the background waits for the resume',
        () async {
      // B18: a flapping radio with the screen off used to start full syncs.
      await firstSyncDone();
      live.onBackground();
      live.onConnectivityChanged(online: false);
      live.onConnectivityChanged(online: true);
      expect(timers.latestLive, isNull,
          reason: 'nothing runs while the app is in the background');

      live.onForeground();

      expect(timers.latestLive, isNotNull,
          reason: 'the sync that was skipped runs now');
    });
  });
}
