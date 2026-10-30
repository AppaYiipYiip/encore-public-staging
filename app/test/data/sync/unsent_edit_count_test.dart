import 'dart:convert';

import 'package:drift/drift.dart' show Value;
import 'package:drift/native.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/sync/outbox.dart';
import 'package:encore/data/sync/pending_intent.dart';
import 'package:flutter_test/flutter_test.dart';

/// The sign-out warning "N changes have not reached your server yet and are lost" counts what a PERSON did and the server has not got
/// (docs/34 G-5, AUDIT F26). A play mark the server refuses is not an edit: it must not frighten anybody.
void main() {
  late AppDatabase db;
  late int me;
  late int other;

  Future<void> add(int server, String kind,
          {String status = 'pending', Object payload = const {}}) =>
      db.into(db.outbox).insert(OutboxCompanion.insert(
            serverId: server,
            kind: kind,
            payloadJson: jsonEncode(payload),
            createdAtMs: 0,
            status: Value(status),
          ));

  setUp(() async {
    db = AppDatabase(NativeDatabase.memory());
    Future<int> server(String name) =>
        db.into(db.servers).insert(ServersCompanion.insert(
            name: name, username: name, endpointsJson: '[]', createdAtMs: 0));
    me = await server('me');
    other = await server('other');
  });

  tearDown(() => db.close());

  test('a like and a playlist edit that wait are counted', () async {
    await add(me, OutboxKind.star);
    await add(me, OutboxKind.playlistUpdate);

    expect(await unsentEditCount(db, me), 2);
  });

  test('a play mark, waiting or turned down, is not an edit and is not counted',
      () async {
    await add(me, OutboxKind.star);
    await add(me, OutboxKind.scrobble);
    await add(me, OutboxKind.scrobble, status: 'failed');

    expect(await unsentEditCount(db, me), 1);
  });

  test('an edit the server turned down is still counted: signing out loses it',
      () async {
    await add(me, OutboxKind.star, status: 'failed');

    expect(await unsentEditCount(db, me), 1);
  });

  test('only this account is counted', () async {
    await add(me, OutboxKind.star);
    await add(other, OutboxKind.star);
    await add(other, OutboxKind.star);

    expect(await unsentEditCount(db, me), 1);
  });
}
