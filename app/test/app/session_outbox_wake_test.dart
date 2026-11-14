import 'dart:async';

import 'package:drift/native.dart';
import 'package:encore/app/session.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fake_http.dart';

/// AUDIT B-58, end to end: an edit made while the server is away reaches it when the server answers again, not when its backoff (20 s,
/// doubling) or the next sync run happens to come. The real session wires the endpoint resolver's "reachable again" to the outbox; nothing here
/// advances a clock.
void main() {
  test(
      'an edit that waited out a failed delivery is delivered the moment the server answers again',
      () async {
    final db = AppDatabase(NativeDatabase.memory());
    final serverId = await db.into(db.servers).insert(ServersCompanion.insert(
          name: 'Test',
          username: 'tester',
          endpointsJson: '[{"label":"Home","url":"http://home.test:4540"}]',
          createdAtMs: 0,
        ));
    await db.into(db.tracks).insert(
        TracksCompanion.insert(serverId: serverId, id: 't1', title: 'Song'));
    var up = true;
    FakeResponse answer(Map<String, Object?> body) => up
        ? FakeResponse.json(subsonicOk(body))
        : const FakeResponse.connectionError();
    final adapter = FakeHttpAdapter(routes: {
      'ping': (_) => answer({}),
      'star': (_) => answer({}),
      'unstar': (_) => answer({}),
    })
      ..fallback = (_) => const FakeResponse.connectionError();
    final server = (await db.select(db.servers).get()).single;
    final session = await ServerSession.create(
      verifyAddresses: false,
      db: db,
      server: server,
      password: 'x',
      dio: fakeDio(adapter),
    );
    addTearDown(() async {
      await session.dispose();
      await db.close();
    });
    unawaited(session.start());
    await session.endpoints.resolve();

    up = false; // the server goes away (the phone stays on its network)
    await session.endpoints.resolve();
    await session.mutations.setTrackStarred('t1', true);
    expect(await session.outbox.flush(), 0);
    final waiting = (await db.select(db.outbox).get()).single;
    expect(waiting.nextAttemptAtMs,
        greaterThan(DateTime.now().millisecondsSinceEpoch),
        reason: 'it is waiting out a backoff of tens of seconds');
    final starsBefore = adapter.count('star');

    up = true; // the server answers again: the first answer says so
    session.endpoints.reportSuccess();
    for (var i = 0; i < 100; i++) {
      if ((await db.select(db.outbox).get()).isEmpty) break;
      await Future<void>.delayed(const Duration(milliseconds: 20));
    }

    expect(await db.select(db.outbox).get(), isEmpty,
        reason: 'delivered within a moment, not at the end of the backoff');
    expect(adapter.count('star'), starsBefore + 1);
  });
}
