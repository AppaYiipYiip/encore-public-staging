import 'dart:async';

import 'package:drift/native.dart';
import 'package:encore/core/clock.dart';
import 'package:encore/data/api/opensubsonic/opensubsonic_client.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/sync/db_lease.dart';
import 'package:encore/data/sync/outbox.dart';
import 'package:encore/data/sync/sync_engine.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_http.dart';
import '../../support/fake_subsonic_server.dart';

/// The open app and the background job are two engines on one database. They
/// must never both deliver the same queued edit or both rewrite the library
/// (docs/23, B2). Here "two engines" are two processors with their own owner id
/// on one database, one of them held mid-request by a gate.
void main() {
  late AppDatabase db;
  late FakeClock clock;
  late int serverId;

  setUp(() async {
    db = AppDatabase(NativeDatabase.memory());
    clock = FakeClock(DateTime.utc(2026, 10, 16, 12));
    serverId = await db.into(db.servers).insert(ServersCompanion.insert(
          name: 'T',
          username: 'u',
          endpointsJson: '[]',
          createdAtMs: 0,
        ));
  });

  tearDown(() => db.close());

  /// Waits (in real time, briefly) until [condition] holds: "engine A is now in
  /// the middle of its request". Polling instead of a fixed sleep keeps the test
  /// from depending on how fast the machine is.
  Future<void> until(bool Function() condition) async {
    final deadline = DateTime.now().add(const Duration(seconds: 5));
    while (!condition()) {
      if (DateTime.now().isAfter(deadline)) fail('condition not reached');
      await Future<void>.delayed(const Duration(milliseconds: 5));
    }
  }

  OpenSubsonicClient clientFor(FakeHttpAdapter adapter) => OpenSubsonicClient(
        dio: fakeDio(adapter),
        baseUrl: () => Uri.parse('http://fake'),
        credentials: const SubsonicCredentials(username: 'u', password: 'p'),
      );

  OutboxProcessor processor(FakeHttpAdapter adapter) => OutboxProcessor(
        db: db,
        client: clientFor(adapter),
        serverId: serverId,
        clock: clock,
        lease: DbLease(db, clock: clock),
        busyRetryDelay: const Duration(days: 1),
      );

  Future<void> queueStars(int n) async {
    for (var i = 0; i < n; i++) {
      await db.into(db.outbox).insert(OutboxCompanion.insert(
            serverId: serverId,
            kind: OutboxKind.star,
            payloadJson: '{"songIds":["t$i"]}',
            createdAtMs: i,
          ));
    }
  }

  group('outbox', () {
    test('two engines deliver each queued edit exactly once', () async {
      final gate = Completer<void>();
      final adapter = FakeHttpAdapter(routes: {
        'star': (_) async {
          await gate.future; // the first delivery is "in flight"
          return FakeResponse.json(subsonicOk({}));
        },
      });
      final app = processor(adapter);
      final job = processor(adapter);
      await queueStars(2);

      final first = app.flush(); // takes the lease, sends item 1, waits
      await until(() => adapter.count('star') == 1);
      final second = await job.flush(); // the background job wakes up

      expect(second, 0, reason: 'someone else is delivering: do nothing');
      expect(adapter.count('star'), 1,
          reason: 'the job must not send the item the app is sending');

      gate.complete();
      expect(await first, 2);
      expect(adapter.count('star'), 2, reason: 'each edit sent once');
      expect(await db.select(db.outbox).get(), isEmpty);
    });

    test('the lease is given back, so the other engine works afterwards',
        () async {
      final adapter = FakeHttpAdapter(routes: {
        'star': (_) => FakeResponse.json(subsonicOk({})),
      });
      final app = processor(adapter);
      final job = processor(adapter);

      await queueStars(1);
      expect(await app.flush(), 1);
      await queueStars(1);
      expect(await job.flush(), 1);
    });

    test('a crashed engine cannot hold the queue for ever', () async {
      final adapter = FakeHttpAdapter(routes: {
        'star': (_) => FakeResponse.json(subsonicOk({})),
      });
      final survivor = processor(adapter);
      await queueStars(1);

      // An engine took the lease and was killed before it let go.
      final crashed = DbLease(db, clock: clock);
      await crashed.tryAcquire('outbox:$serverId',
          ttl: const Duration(seconds: 60));

      expect(await survivor.flush(), 0, reason: 'still within its time');
      clock.advance(const Duration(seconds: 61));
      expect(await survivor.flush(), 1, reason: 'the lease expired');
    });
  });

  group('shutting down', () {
    // A delivery or a sync that is mid-request when the session is disposed
    // (sign-out, switching server) used to carry on and touch the database
    // after it was closed. The private-listening test hit it under load.
    test(
        'disposing waits for a delivery in flight; nothing touches a closed '
        'database afterwards', () async {
      final errors = <Object>[];
      await runZonedGuarded(() async {
        final gate = Completer<void>();
        final adapter = FakeHttpAdapter(routes: {
          'star': (_) async {
            await gate.future;
            return FakeResponse.json(subsonicOk({}));
          },
        });
        final p = processor(adapter);
        await queueStars(3);
        unawaited(p.flush()); // never awaited, like the app's own callers
        await until(() => adapter.count('star') == 1);

        final disposed = p.dispose();
        gate.complete();
        await disposed;
        await db.close(); // what a sign-out does next
        await Future<void>.delayed(const Duration(milliseconds: 50));
        expect(adapter.count('star'), 1,
            reason: 'after dispose no further item is sent');
      }, (error, stack) => errors.add(error));

      expect(errors, isEmpty);
    });

    test('disposing stops a sync that is mid-run and waits for it', () async {
      final errors = <Object>[];
      await runZonedGuarded(() async {
        final server = FakeSubsonicServer()..seed(songCount: 30, albumCount: 3);
        final gate = Completer<void>();
        final original = server.adapter.routes['getArtists']!;
        server.adapter.routes['getArtists'] = (r) async {
          await gate.future;
          return original(r);
        };
        final engine = SyncEngine(
          db: db,
          client: clientFor(server.adapter),
          serverId: serverId,
          clock: clock,
          lease: DbLease(db, clock: clock),
        );
        unawaited(engine.run(force: true));
        await until(() => server.adapter.count('getArtists') == 1);

        final disposed = engine.dispose();
        gate.complete();
        await disposed;
        await db.close();
        await Future<void>.delayed(const Duration(milliseconds: 50));
      }, (error, stack) => errors.add(error));

      expect(errors, isEmpty);
    });
  });

  group('sync', () {
    test('a second engine does not start while the first is syncing', () async {
      final server = FakeSubsonicServer()..seed(songCount: 30, albumCount: 3);
      final gate = Completer<void>();
      final original = server.adapter.routes['getArtists']!;
      server.adapter.routes['getArtists'] = (r) async {
        await gate.future;
        return original(r);
      };
      SyncEngine engine() => SyncEngine(
            db: db,
            client: clientFor(server.adapter),
            serverId: serverId,
            clock: clock,
            lease: DbLease(db, clock: clock),
          );
      final app = engine();
      final job = engine();

      final first = app.run(force: true);
      await until(() => server.adapter.count('getArtists') == 1);
      final second = await job.run(force: true);

      expect(second, isA<SyncBusy>(),
          reason: 'one engine rewriting the library at a time');
      expect(server.adapter.count('getScanStatus'), 1,
          reason: 'the busy engine made no request');

      gate.complete();
      expect(await first, isA<SyncCompleted>());
      expect(await job.run(), isA<SyncCompleted>(),
          reason: 'the lease was given back');
      await app.dispose();
      await job.dispose();
    });
  });
}
