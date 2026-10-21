import 'dart:convert';

import 'package:drift/drift.dart' show Value;
import 'package:drift/native.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/sync/outbox.dart';
import 'package:encore/data/sync/outbox_failures.dart';
import 'package:flutter_test/flutter_test.dart';

/// Edits the server turned down are shown to the person, in plain words, with
/// Try again / Let it go (docs/23, B1). Before this a parked edit was invisible.
void main() {
  late AppDatabase db;
  late int me;
  late int other;
  late OutboxFailures failures;
  var flushed = 0;
  var refreshed = 0;

  setUp(() async {
    db = AppDatabase(NativeDatabase.memory());
    Future<int> server(String name) =>
        db.into(db.servers).insert(ServersCompanion.insert(
            name: name, username: name, endpointsJson: '[]', createdAtMs: 0));
    me = await server('me');
    other = await server('other');
    flushed = 0;
    refreshed = 0;
    failures = OutboxFailures(
      db: db,
      serverId: me,
      flush: () async => flushed++,
      refresh: () async => refreshed++,
    );
  });

  tearDown(() => db.close());

  Future<int> park(
    String kind,
    Map<String, Object?> payload, {
    int? server,
    String status = 'failed',
    String? reason = 'Not authorised',
    int createdAtMs = 1,
  }) async {
    return db.into(db.outbox).insert(OutboxCompanion.insert(
          serverId: server ?? me,
          kind: kind,
          payloadJson: jsonEncode(payload),
          createdAtMs: createdAtMs,
          status: Value(status),
          lastError: Value(reason),
          attempts: const Value(5),
          serverErrors: const Value(5),
          nextAttemptAtMs: const Value(99999),
        ));
  }

  test('lists only this account\'s parked edits, oldest first', () async {
    final a = await park(OutboxKind.star, {
      'songIds': ['t1']
    });
    await park(
        OutboxKind.star,
        {
          'songIds': ['t2']
        },
        server: other);
    await park(
        OutboxKind.star,
        {
          'songIds': ['t3']
        },
        status: 'pending');
    final b = await park(OutboxKind.playlistDelete, {'id': 'p1'});

    final list = await failures.watch().first;

    expect(list.map((e) => e.id), [a, b]);
    expect(list.first.why, 'Not authorised');
  });

  test('says what the edit was in words, not codes', () async {
    String label(String kind, Map<String, Object?> payload) =>
        OutboxFailures.describeEdit(OutboxRow(
          id: 1,
          serverId: me,
          kind: kind,
          payloadJson: jsonEncode(payload),
          createdAtMs: 0,
          attempts: 0,
          serverErrors: 0,
          nextAttemptAtMs: 0,
          status: 'failed',
        ));

    expect(label(OutboxKind.star, {}), 'Like');
    expect(label(OutboxKind.unstar, {}), 'Remove a like');
    expect(label(OutboxKind.scrobble, {}), 'A play for your history');
    expect(label(OutboxKind.playlistCreate, {'name': 'Gym'}),
        'Create the playlist "Gym"');
    expect(
        label(OutboxKind.playlistUpdate, {
          'playlistId': 'p',
          'add': ['t1']
        }),
        'Add songs to a playlist');
    expect(
        label(OutboxKind.playlistUpdate, {
          'playlistId': 'p',
          'removeIds': ['t1']
        }),
        'Remove songs from a playlist');
    expect(label(OutboxKind.playlistUpdate, {'playlistId': 'p', 'name': 'X'}),
        'Rename a playlist');
    expect(label(OutboxKind.playlistDelete, {'id': 'p'}), 'Delete a playlist');
    expect(label('something.new', {}), 'A change');
  });

  test('a damaged payload still gets a generic label', () {
    final row = OutboxRow(
      id: 1,
      serverId: me,
      kind: OutboxKind.playlistUpdate,
      payloadJson: '{not json',
      createdAtMs: 0,
      attempts: 0,
      serverErrors: 0,
      nextAttemptAtMs: 0,
      status: 'failed',
    );
    expect(OutboxFailures.describeEdit(row), 'Change a playlist');
  });

  test('try again puts it back with a clean count, in its place, and delivers',
      () async {
    final id = await park(OutboxKind.star, {
      'songIds': ['t1']
    });

    await failures.retry(id);

    final row =
        await (db.select(db.outbox)..where((o) => o.id.equals(id))).getSingle();
    expect(row.status, 'pending');
    expect(row.attempts, 0);
    expect(row.serverErrors, 0);
    expect(row.nextAttemptAtMs, 0);
    expect(row.lastError, isNull);
    expect(row.id, id, reason: 'same id, so FIFO order is unchanged');
    expect(flushed, 1);
  });

  test('try all again requeues every parked edit of this account only',
      () async {
    final a = await park(OutboxKind.star, {
      'songIds': ['t1']
    });
    final b = await park(OutboxKind.unstar, {
      'songIds': ['t2']
    });
    final foreign = await park(
        OutboxKind.star,
        {
          'songIds': ['t9']
        },
        server: other);

    await failures.retryAll();

    Future<String> status(int id) async =>
        (await (db.select(db.outbox)..where((o) => o.id.equals(id)))
                .getSingle())
            .status;
    expect(await status(a), 'pending');
    expect(await status(b), 'pending');
    expect(await status(foreign), 'failed');
    expect(flushed, 1);
  });

  test('let it go deletes it and asks for the server\'s truth', () async {
    final id = await park(OutboxKind.star, {
      'songIds': ['t1']
    });
    final pending = await park(
        OutboxKind.star,
        {
          'songIds': ['t2']
        },
        status: 'pending');

    await failures.discard(id);

    final left = await db.select(db.outbox).get();
    expect(left.map((r) => r.id), [pending],
        reason: 'only the parked one goes; a pending edit is never touched');
    expect(refreshed, 1);
  });

  test('discard cannot delete a pending edit or another account\'s', () async {
    final pending = await park(
        OutboxKind.star,
        {
          'songIds': ['t1']
        },
        status: 'pending');
    final foreign = await park(
        OutboxKind.star,
        {
          'songIds': ['t2']
        },
        server: other);

    await failures.discard(pending);
    await failures.discard(foreign);

    expect((await db.select(db.outbox).get()).length, 2);
  });
}
