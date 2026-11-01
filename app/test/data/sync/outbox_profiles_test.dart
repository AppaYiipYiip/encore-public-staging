import 'package:drift/native.dart';
import 'package:encore/core/clock.dart';
import 'package:encore/data/api/opensubsonic/opensubsonic_client.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/sync/outbox.dart';
import 'package:encore/data/sync/pending_intent.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_http.dart';

/// `docs/34` CF-38: a shared device, two profiles, one outbox. The profiles are rows of one database; each profile's waiting edits are rows
/// keyed by its server, and only the active profile has a session, and so a delivery. The rule (G-5): deliver for the profile that is active.
void main() {
  late AppDatabase db;
  late FakeClock clock;
  late int anna;
  late int ben;
  late FakeHttpAdapter annaAdapter;
  late FakeHttpAdapter benAdapter;
  late OutboxProcessor annaOutbox;
  late OutboxProcessor benOutbox;
  late MutationService annaEdits;
  late MutationService benEdits;

  FakeHttpAdapter server() => FakeHttpAdapter(routes: {
        'star': (_) => FakeResponse.json(subsonicOk({})),
        'unstar': (_) => FakeResponse.json(subsonicOk({})),
      });

  Future<int> profile(String name) async {
    final id = await db.into(db.servers).insert(ServersCompanion.insert(
          name: name,
          username: name,
          endpointsJson: '[]',
          createdAtMs: 0,
        ));
    for (final n in [1, 2]) {
      await db.into(db.tracks).insert(TracksCompanion.insert(
            serverId: id,
            id: '$name$n',
            title: 'Song $n of $name',
          ));
    }
    return id;
  }

  OutboxProcessor processorOf(int serverId, FakeHttpAdapter adapter) =>
      OutboxProcessor(
        db: db,
        client: OpenSubsonicClient(
          dio: fakeDio(adapter),
          baseUrl: () => Uri.parse('http://fake'),
          credentials: const SubsonicCredentials(username: 'u', password: 'p'),
        ),
        serverId: serverId,
        clock: clock,
      );

  MutationService editsOf(int serverId) => MutationService(
      db: db, serverId: serverId, clock: clock, onQueued: () {});

  setUp(() async {
    db = AppDatabase(NativeDatabase.memory());
    clock = FakeClock(DateTime.utc(2026, 11, 1, 12));
    anna = await profile('anna');
    ben = await profile('ben');
    annaAdapter = server();
    benAdapter = server();
    annaOutbox = processorOf(anna, annaAdapter);
    benOutbox = processorOf(ben, benAdapter);
    annaEdits = editsOf(anna);
    benEdits = editsOf(ben);
  });

  tearDown(() => db.close());

  Future<List<OutboxRow>> queue() => db.select(db.outbox).get();

  test(
      "CF-38: a profile delivers its own waiting edits and leaves the other profile's alone",
      () async {
    await annaEdits.setTrackStarred('anna1', true);
    await benEdits.setTrackStarred('ben1', true);

    expect(await annaOutbox.flush(), 1);

    expect(annaAdapter.requests.single.params['id'], ['anna1']);
    expect(benAdapter.requests, isEmpty);
    final left = await queue();
    expect(left.map((r) => r.serverId), [ben]);
    expect(left.single.status, 'pending');
    expect(left.single.attempts, 0);
  });

  test(
      'CF-38: a profile that was switched away from delivers nothing, and its edits wait without using up an attempt',
      () async {
    await annaEdits.setTrackStarred('anna1', true);
    // What switching profile does: the session of the profile that was active goes away, and its processor with it.
    await annaOutbox.dispose();

    expect(await annaOutbox.flush(), 0);

    expect(annaAdapter.requests, isEmpty);
    final row = (await queue()).single;
    expect(row.serverId, anna);
    expect(row.status, 'pending');
    expect(row.attempts, 0);
  });

  test(
      'CF-38: when that profile is active again its waiting edits are delivered, in their order, and the other profile is not disturbed',
      () async {
    await annaEdits.setTrackStarred('anna1', true);
    await annaEdits.setTrackStarred('anna2', true);
    await annaOutbox.dispose();
    await benEdits.setTrackStarred('ben1', true);
    expect(await benOutbox.flush(), 1, reason: 'ben is the active profile now');
    expect(annaAdapter.requests, isEmpty);

    final again = processorOf(anna, annaAdapter); // a new session for anna
    expect(await again.flush(), 2);

    final sent = [
      for (final r in annaAdapter.requests) ...?r.params['id'],
    ];
    expect(sent, ['anna1', 'anna2']);
    expect(await queue(), isEmpty);
  });

  test(
      'CF-38: the count of unsent edits, which the sign-out warning shows, is per profile',
      () async {
    await annaEdits.setTrackStarred('anna1', true);
    await annaEdits.setTrackStarred('anna2', true);
    await benEdits.setTrackStarred('ben1', true);

    expect(await unsentEditCount(db, anna), 2);
    expect(await unsentEditCount(db, ben), 1);
  });

  test(
      "CF-38: signing out of one profile takes only its own waiting edits with it",
      () async {
    await annaEdits.setTrackStarred('anna1', true);
    await benEdits.setTrackStarred('ben1', true);

    await (db.delete(db.servers)..where((s) => s.id.equals(anna))).go();

    final left = await queue();
    expect(left.map((r) => r.serverId), [ben]);
  });
}
