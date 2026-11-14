import 'dart:async';
import 'dart:convert';

import 'package:drift/native.dart';
import 'package:encore/core/clock.dart';
import 'package:encore/data/api/opensubsonic/opensubsonic_client.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/sync/outbox.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_http.dart';

void main() {
  late AppDatabase db;
  late FakeHttpAdapter adapter;
  late FakeClock clock;
  late OpenSubsonicClient client;
  late OutboxProcessor outbox;
  late MutationService mutations;
  late int serverId;
  var queuedSignals = 0;

  setUp(() async {
    db = AppDatabase(NativeDatabase.memory());
    serverId = await db.into(db.servers).insert(ServersCompanion.insert(
          name: 'T',
          username: 'u',
          endpointsJson: '[]',
          createdAtMs: 0,
        ));
    await db.into(db.tracks).insert(TracksCompanion.insert(
          serverId: serverId,
          id: 't1',
          title: 'Song',
        ));
    adapter = FakeHttpAdapter(routes: {
      'star': (_) => FakeResponse.json(subsonicOk({})),
      'unstar': (_) => FakeResponse.json(subsonicOk({})),
      'scrobble': (_) => FakeResponse.json(subsonicOk({})),
    });
    clock = FakeClock(DateTime.utc(2026, 10, 14, 12));
    client = OpenSubsonicClient(
      dio: fakeDio(adapter),
      baseUrl: () => Uri.parse('http://fake'),
      credentials: const SubsonicCredentials(username: 'u', password: 'p'),
    );
    outbox = OutboxProcessor(
        db: db, client: client, serverId: serverId, clock: clock);
    queuedSignals = 0;
    mutations = MutationService(
      db: db,
      serverId: serverId,
      clock: clock,
      onQueued: () => queuedSignals++,
    );
  });

  tearDown(() => db.close());

  Future<TrackRow> track() =>
      (db.select(db.tracks)..where((t) => t.id.equals('t1'))).getSingle();
  Future<List<OutboxRow>> queue() => db.select(db.outbox).get();

  test('liking is applied locally at once and queued', () async {
    await mutations.setTrackStarred('t1', true);

    expect((await track()).starredAtMs, isNotNull);
    final q = await queue();
    expect(q.single.kind, OutboxKind.star);
    expect(jsonDecode(q.single.payloadJson), {
      'songIds': ['t1']
    });
    expect(queuedSignals, 1);
  });

  test('flush delivers, then empties the queue', () async {
    await mutations.setTrackStarred('t1', true);

    final delivered = await outbox.flush();

    expect(delivered, 1);
    expect(adapter.count('star'), 1);
    expect(adapter.requests.single.params['id'], ['t1']);
    expect(await queue(), isEmpty);
  });

  test('like then unlike before delivery cancels out (no requests)', () async {
    await mutations.setTrackStarred('t1', true);
    await mutations.setTrackStarred('t1', false);

    expect(await queue(), isEmpty);
    expect((await track()).starredAtMs, isNull);
    expect(await outbox.flush(), 0);
    expect(adapter.requests, isEmpty);
  });

  test('offline: item stays queued with backoff, order is preserved', () async {
    adapter.routes['star'] = (_) => const FakeResponse.connectionError();
    await mutations.setTrackStarred('t1', true);
    await mutations.recordPlay(trackId: 't1', listenedMs: 60000);

    expect(await outbox.flush(), 0);

    final q = await queue();
    expect(q, hasLength(2));
    expect(q.first.attempts, 1);
    expect(q.first.nextAttemptAtMs,
        greaterThan(clock.now().millisecondsSinceEpoch));
    expect(adapter.count('scrobble'), 0,
        reason: 'must not overtake the failed item');
  });

  test('retries after the backoff elapses and delivers in order', () async {
    var online = false;
    adapter.routes['star'] = (r) => online
        ? FakeResponse.json(subsonicOk({}))
        : const FakeResponse.connectionError();
    await mutations.setTrackStarred('t1', true);
    await mutations.recordPlay(trackId: 't1', listenedMs: 60000);
    await outbox.flush();

    online = true;
    expect(await outbox.flush(), 0, reason: 'still inside the backoff window');
    clock.advance(const Duration(hours: 1));

    expect(await outbox.flush(), 2);
    expect(await queue(), isEmpty);
    expect(adapter.requests.map((r) => r.apiMethod).toList(),
        ['star', 'star', 'scrobble']);
  });

  // AUDIT B-58: after a failed delivery nothing woke the outbox but the next queued edit or the next sync run, so an edit made while only the
  // server was away reached it 549 s after it answered again.
  test(
      'a server that answers again gets what waited out a network failure at once, not at the end of the backoff',
      () async {
    var online = false;
    adapter.routes['star'] = (r) => online
        ? FakeResponse.json(subsonicOk({}))
        : const FakeResponse.connectionError();
    await mutations.setTrackStarred('t1', true);
    expect(await outbox.flush(), 0);
    online = true;
    expect(await outbox.flush(), 0, reason: 'the backoff has not run out');

    expect(await outbox.retryNow(), 1,
        reason: 'the server is back: the wait is over');

    expect(await queue(), isEmpty);
  });

  test(
      'a server that ANSWERS with an error is not tried sooner because the line came back (its own backoff and bound stay)',
      () async {
    adapter.routes['star'] = (_) =>
        FakeResponse.json(subsonicError(0, 'Internal error'), status: 500);
    await mutations.setTrackStarred('t1', true);
    expect(await outbox.flush(), 0);
    final waiting = (await queue()).single;
    expect(waiting.serverErrors, 1);

    expect(await outbox.retryNow(), 0);

    final after = (await queue()).single;
    expect(after.attempts, waiting.attempts,
        reason: 'no second try: a flapping line must not burn the bound');
    expect(after.nextAttemptAtMs, waiting.nextAttemptAtMs);
  });

  test('a failed delivery schedules its own retry for the end of the backoff',
      () async {
    final wakes = <(Duration, void Function())>[];
    final woken = OutboxProcessor(
      db: db,
      client: client,
      serverId: serverId,
      clock: clock,
      timerFactory: (delay, run) {
        wakes.add((delay, run));
        return Timer(const Duration(days: 1), () {});
      },
    );
    var online = false;
    adapter.routes['star'] = (r) => online
        ? FakeResponse.json(subsonicOk({}))
        : const FakeResponse.connectionError();
    await mutations.setTrackStarred('t1', true);

    expect(await woken.flush(), 0);

    expect(wakes, hasLength(1), reason: 'one wake, at the end of the backoff');
    final due = (await queue()).single.nextAttemptAtMs;
    expect(wakes.single.$1.inMilliseconds,
        due - clock.now().millisecondsSinceEpoch);

    online = true;
    clock.advance(wakes.single.$1);
    wakes.single.$2();
    await pumpEventQueue();

    expect(await queue(), isEmpty, reason: 'the wake delivered it');
    await woken.dispose();
  });

  test('a permanently rejected item is parked and does not block the rest',
      () async {
    adapter.routes['star'] =
        (_) => FakeResponse.json(subsonicError(70, 'Song not found'));
    await mutations.setTrackStarred('t1', true);
    await mutations.recordPlay(trackId: 't1', listenedMs: 60000);

    final delivered = await outbox.flush();

    expect(delivered, 1, reason: 'the scrobble behind it still goes out');
    final q = await queue();
    expect(q.single.status, 'failed');
    expect(q.single.lastError, contains('not found'));
  });

  test('scrobble carries the original play time (offline replay)', () async {
    await mutations.recordPlay(trackId: 't1', listenedMs: 90000);
    clock.advance(const Duration(hours: 5)); // delivered much later
    await outbox.flush();

    final r = adapter.requests.single;
    expect(r.param('id'), 't1');
    expect(r.param('time'),
        DateTime.utc(2026, 10, 14, 12).millisecondsSinceEpoch.toString());
    expect(r.param('submission'), 'true');
  });

  test('records local play history', () async {
    await mutations.recordPlay(
        trackId: 't1', listenedMs: 1234, scrobble: false);

    final history = await db.select(db.playHistory).get();
    expect(history.single.listenedMs, 1234);
    expect(await queue(), isEmpty);
  });

  test('concurrent flushes share one pass', () async {
    await mutations.setTrackStarred('t1', true);
    final a = outbox.flush();
    final b = outbox.flush();
    expect(identical(a, b), isTrue);
    await Future.wait([a, b]);
    expect(adapter.count('star'), 1);
  });

  group('a damaged queued change', () {
    // The payload is JSON written by an older build or damaged on disk. A cast
    // that threw out of the flush failed every sync at its first step, for
    // ever, because the flush runs before anything else (docs/23, B3).
    final damaged = <String, (String, String)>{
      'a field of the wrong type': ('rating', '{"id": 7, "rating": "five"}'),
      'a missing field': ('playlist.update', '{"add": ["t1"]}'),
      'a list that is not a list': ('star', '{"songIds": "t1"}'),
      'a kind this build does not know': ('from.the.future', '{}'),
      'text that is not JSON': ('star', '{oops'),
    };

    damaged.forEach((name, row) {
      test('$name is parked and does not stop the queue', () async {
        await db.into(db.outbox).insert(OutboxCompanion.insert(
              serverId: serverId,
              kind: row.$1,
              payloadJson: row.$2,
              createdAtMs: 1,
            ));
        await mutations.recordPlay(trackId: 't1', listenedMs: 60000);

        final delivered = await outbox.flush();

        expect(delivered, 1, reason: 'the scrobble behind it still goes out');
        final q = await queue();
        expect(q.single.status, 'failed');
        expect(q.single.lastError, isNotEmpty);
        expect(q.single.lastError, isNot(contains("type '")),
            reason: 'no Dart type error text for a person to read');
      });
    });
  });

  group('a rejection from the server (HTTP 200 with a Subsonic error code)',
      () {
    // A Subsonic error arrives as HTTP 200 with a code in the body, so there is
    // no HTTP status to tell "temporary" from "never going to work". The queue
    // is strict FIFO, so a rejection mistaken for a passing glitch froze every
    // later like, scrobble and playlist edit for ever (docs/23, B1).
    for (final code in const [10, 20, 30, 43, 50, 60]) {
      test('code $code is parked at once and does not block the rest',
          () async {
        adapter.routes['star'] =
            (_) => FakeResponse.json(subsonicError(code, 'rejected'));
        await mutations.setTrackStarred('t1', true);
        await mutations.recordPlay(trackId: 't1', listenedMs: 60000);

        final delivered = await outbox.flush();

        expect(delivered, 1, reason: 'the scrobble behind it still goes out');
        final q = await queue();
        expect(q.single.status, 'failed');
        expect(q.single.lastError, contains('rejected'));
      });
    }

    test('the generic code 0 is retried a few times, then parked', () async {
      final patient = OutboxProcessor(
        db: db,
        client: client,
        serverId: serverId,
        clock: clock,
        maxServerAttempts: 3,
      );
      adapter.routes['star'] =
          (_) => FakeResponse.json(subsonicError(0, 'A generic error'));
      await mutations.setTrackStarred('t1', true);
      await mutations.recordPlay(trackId: 't1', listenedMs: 60000);

      // Attempts 1 and 2: back off, the scrobble waits behind it (order kept).
      for (var i = 0; i < 2; i++) {
        expect(await patient.flush(), 0);
        expect((await queue()).first.status, 'pending');
        clock.advance(const Duration(hours: 1));
      }
      expect(adapter.count('scrobble'), 0);

      // Attempt 3 gives up on the star and lets the scrobble through.
      expect(await patient.flush(), 1);
      final q = await queue();
      expect(q.single.status, 'failed');
      expect(q.single.lastError, contains('generic'));
    });

    test('an HTTP 5xx is retried a bounded number of times as well', () async {
      final patient = OutboxProcessor(
        db: db,
        client: client,
        serverId: serverId,
        clock: clock,
        maxServerAttempts: 2,
      );
      adapter.routes['star'] =
          (_) => FakeResponse.json(const {'error': 'unavailable'}, status: 503);
      await mutations.setTrackStarred('t1', true);

      expect(await patient.flush(), 0);
      clock.advance(const Duration(hours: 1));
      expect(await patient.flush(), 0);

      expect((await queue()).single.status, 'failed');
    });

    test('being offline never uses up the attempts', () async {
      final patient = OutboxProcessor(
        db: db,
        client: client,
        serverId: serverId,
        clock: clock,
        maxServerAttempts: 3,
      );
      var online = false;
      adapter.routes['star'] = (_) => online
          ? FakeResponse.json(subsonicOk({}))
          : const FakeResponse.connectionError();
      await mutations.setTrackStarred('t1', true);

      // A week without signal, a try every day: far more than any budget.
      for (var i = 0; i < 40; i++) {
        expect(await patient.flush(), 0);
        clock.advance(const Duration(days: 1));
      }
      expect((await queue()).single.status, 'pending',
          reason:
              'being offline is not the fault of the item: wait, never fail');

      online = true;
      expect(await patient.flush(), 1);
      expect(await queue(), isEmpty);
    });
  });
}
