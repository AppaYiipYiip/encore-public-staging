import 'dart:io';

import 'package:drift/drift.dart' show driftRuntimeOptions;
import 'package:drift/native.dart';
import 'package:encore/core/clock.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/sync/db_lease.dart';
import 'package:flutter_test/flutter_test.dart';

/// The lease is what keeps the open app and the background job from sending the
/// same queued edit twice or removing each other's rows (docs/23, B2).
void main() {
  driftRuntimeOptions.dontWarnAboutMultipleDatabases = true;

  group('on one database', () {
    late AppDatabase db;
    late FakeClock clock;
    late DbLease a;
    late DbLease b;

    setUp(() {
      db = AppDatabase(NativeDatabase.memory());
      clock = FakeClock(DateTime.utc(2026, 10, 16, 12));
      a = DbLease(db, clock: clock);
      b = DbLease(db, clock: clock);
    });

    tearDown(() => db.close());

    test('every engine instance has its own random owner', () {
      expect(a.owner, isNot(b.owner));
      expect(a.owner, hasLength(16));
    });

    test('a free lease is taken; a held one is refused', () async {
      expect(await a.tryAcquire('sync:1'), isTrue);
      expect(await b.tryAcquire('sync:1'), isFalse);
    });

    test('different names are independent', () async {
      expect(await a.tryAcquire('sync:1'), isTrue);
      expect(await b.tryAcquire('outbox:1'), isTrue);
      expect(await b.tryAcquire('sync:2'), isTrue);
    });

    test('the holder can extend its own lease', () async {
      expect(await a.tryAcquire('sync:1', ttl: const Duration(seconds: 30)),
          isTrue);
      clock.advance(const Duration(seconds: 20));
      expect(await a.tryAcquire('sync:1', ttl: const Duration(seconds: 30)),
          isTrue);
      clock.advance(const Duration(seconds: 20)); // 40 s: past the first TTL
      expect(await b.tryAcquire('sync:1'), isFalse,
          reason: 'it was extended, so it has not expired');
    });

    test('an expired lease can be taken over (a killed process lets go)',
        () async {
      expect(await a.tryAcquire('sync:1', ttl: const Duration(seconds: 30)),
          isTrue);
      clock.advance(const Duration(seconds: 31));

      expect(await b.tryAcquire('sync:1'), isTrue);
      expect(await a.tryAcquire('sync:1'), isFalse,
          reason: 'the first owner has lost it and must find out');
    });

    test('release frees it for others', () async {
      await a.tryAcquire('sync:1');
      await a.release('sync:1');

      expect(await b.tryAcquire('sync:1'), isTrue);
    });

    test('only the holder can release', () async {
      await a.tryAcquire('sync:1');

      await b.release('sync:1'); // not the holder: no effect

      expect(await b.tryAcquire('sync:1'), isFalse);
    });
  });

  group('on a database file shared by two connections', () {
    late Directory dir;
    late File file;
    late AppDatabase first;
    late AppDatabase second;

    setUp(() async {
      dir = await Directory.systemTemp.createTemp('encore_lease_');
      file = File('${dir.path}${Platform.pathSeparator}shared.sqlite');
      first = AppDatabase(NativeDatabase(file));
      // Opens, migrates and creates the schema through the first connection.
      await first.customSelect('SELECT 1').get();
      second = AppDatabase(NativeDatabase(file));
    });

    tearDown(() async {
      await first.close();
      await second.close();
      await dir.delete(recursive: true);
    });

    test('exactly one of many simultaneous claims wins', () async {
      final engines = [
        for (var i = 0; i < 6; i++) DbLease(i.isEven ? first : second),
      ];

      final results = await Future.wait([
        for (final e in engines) e.tryAcquire('sync:1'),
      ]);

      expect(results.where((won) => won), hasLength(1),
          reason: 'two engines on two connections must never both hold it');
    });

    test('a lease taken on one connection is seen on the other', () async {
      final app = DbLease(first);
      final job = DbLease(second);

      expect(await app.tryAcquire('outbox:1'), isTrue);
      expect(await job.tryAcquire('outbox:1'), isFalse);

      await app.release('outbox:1');
      expect(await job.tryAcquire('outbox:1'), isTrue);
    });
  });
}
