import 'package:drift/native.dart';
import 'package:encore/app/playback_providers.dart';
import 'package:encore/app/session.dart';
import 'package:encore/core/clock.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/playback/queue_model.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fake_http.dart';
import '../support/test_app.dart';

/// Private listening leaves no trace: no "now playing" ping, no scrobble and
/// no local history (Settings > Home, library & privacy).
void main() {
  late AppDatabase db;
  late int serverId;
  late FakeHttpAdapter adapter;
  late ServerSession session;
  late FakeClock clock;
  var private = false;

  const item = QueueItem(uid: 1, id: 'al1-t1', title: 'Opening Kodama');

  setUp(() async {
    private = false;
    db = AppDatabase(NativeDatabase.memory());
    serverId = await Seed.library(db);
    adapter = FakeHttpAdapter(routes: {
      'ping': (_) => FakeResponse.json(subsonicOk({})),
      'scrobble': (_) => FakeResponse.json(subsonicOk({})),
    });
    final server = (await db.select(db.servers).get()).first;
    session = await ServerSession.create(
      verifyAddresses: false,
      db: db,
      server: server,
      password: 'x',
      dio: fakeDio(adapter),
    );
    clock = FakeClock(DateTime.utc(2026, 10, 15, 12));
  });

  tearDown(() async {
    await session.dispose();
    await db.close();
  });

  SessionPlayRecorder recorder({
    Future<String?> Function(QueueItem item)? resolveStreamed,
  }) =>
      SessionPlayRecorder(
        db: db,
        serverId: serverId,
        session: () => session,
        clock: clock,
        isPrivate: () => private,
        resolveStreamed: resolveStreamed,
      );

  Future<int> history() async => (await db.select(db.playHistory).get()).length;

  /// The session delivers queued scrobbles as soon as they are written.
  Future<void> until(bool Function() done) async {
    for (var i = 0; i < 200 && !done(); i++) {
      await Future<void>.delayed(const Duration(milliseconds: 10));
    }
  }

  test('a normal play pings now-playing and is scrobbled', () async {
    await recorder().nowPlaying(item);
    await recorder().played(item, listened: const Duration(seconds: 90));
    await until(() => adapter.count('scrobble') >= 2);

    expect(adapter.count('scrobble'), 2, reason: 'now playing + the play');
    expect(await history(), 1);
  });

  group('a whole song played from the service stream', () {
    // The song a friend asked for with "play any song": it plays from the
    // service at once and has no id on the music server yet. Heard to the end,
    // it must count in the person's history (Year in Music, Most played).
    final streamed = QueueItem.streamed(
      uid: 2,
      id: 'cat-9',
      title: 'Opening Kodama',
      uri: Uri.parse('http://svc/api/play/abc/audio'),
      artist: 'Alcest',
    );

    test('is recorded under the library id of that song', () async {
      await recorder(resolveStreamed: (_) async => 'al1-t1')
          .played(streamed, listened: const Duration(seconds: 150));
      await until(() => adapter.count('scrobble') >= 1);

      final rows = await db.select(db.playHistory).get();
      expect(rows.map((r) => r.trackId), ['al1-t1']);
      expect(adapter.count('scrobble'), 1);
    });

    test('is not recorded when the library cannot say which song it is',
        () async {
      await recorder(resolveStreamed: (_) async => null)
          .played(streamed, listened: const Duration(seconds: 150));
      await Future<void>.delayed(const Duration(milliseconds: 100));

      expect(await history(), 0,
          reason: 'an id the music server never heard of is not sent');
      expect(adapter.count('scrobble'), 0);
    });

    test('is not recorded in private listening', () async {
      private = true;
      await recorder(resolveStreamed: (_) async => 'al1-t1')
          .played(streamed, listened: const Duration(seconds: 150));
      await Future<void>.delayed(const Duration(milliseconds: 100));

      expect(await history(), 0);
    });
  });

  test('a private play sends and records nothing', () async {
    private = true;
    await recorder().nowPlaying(item);
    await recorder().played(item, listened: const Duration(seconds: 90));
    await Future<void>.delayed(const Duration(milliseconds: 100));

    expect(adapter.count('scrobble'), 0);
    expect(await history(), 0);
    expect((await db.select(db.outbox).get()), isEmpty);
  });

  test('the switch is read per play, so it can change mid-session', () async {
    final r = recorder();
    private = true;
    await r.played(item, listened: const Duration(seconds: 60));
    private = false;
    await r.played(item, listened: const Duration(seconds: 60));

    expect(await history(), 1);
  });
}
