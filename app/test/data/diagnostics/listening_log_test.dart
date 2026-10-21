import 'package:drift/native.dart';
import 'package:encore/core/clock.dart';
import 'package:encore/core/power.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/diagnostics/listening_log.dart';
import 'package:encore/data/sync/sync_state_store.dart';
import 'package:flutter_test/flutter_test.dart';

class _Probe implements PowerProbe {
  PowerReading? reading = const PowerReading(level: 80, charging: false);

  @override
  Future<PowerReading?> read() async => reading;
}

void main() {
  late AppDatabase db;
  late FakeClock clock;
  late _Probe probe;
  late ListeningLog log;

  setUp(() async {
    db = AppDatabase(NativeDatabase.memory());
    final serverId = await db.into(db.servers).insert(ServersCompanion.insert(
          name: 'Home',
          username: 'marwa',
          endpointsJson: '[]',
          createdAtMs: 0,
        ));
    clock = FakeClock(DateTime.utc(2026, 10, 15, 9));
    probe = _Probe();
    log = ListeningLog(
      store: SyncStateStore(db, serverId),
      probe: probe,
      clock: clock,
    );
  });

  tearDown(() => db.close());

  Future<void> listen(Duration length, {int from = 80, int to = 74}) async {
    probe.reading = PowerReading(level: from, charging: false);
    await log.started();
    clock.advance(length);
    probe.reading = PowerReading(level: to, charging: false);
    await log.stopped();
  }

  test('a stretch of listening is recorded with the battery at both ends',
      () async {
    await listen(const Duration(hours: 2), from: 80, to: 68);

    final s = (await log.sessions()).single;
    expect(s.startLevel, 80);
    expect(s.endLevel, 68);
    expect(s.drop, 12);
    expect(s.length, const Duration(hours: 2));
    expect(s.percentPerHour, closeTo(6.0, 1e-9));
  });

  test('less than a minute is a skip, not listening', () async {
    await listen(const Duration(seconds: 30));

    expect(await log.sessions(), isEmpty);
  });

  test('a short pause does not split a session', () async {
    await listen(const Duration(minutes: 30), from: 90, to: 87);
    clock.advance(const Duration(minutes: 2));
    probe.reading = const PowerReading(level: 87, charging: false);
    await log.started();
    clock.advance(const Duration(minutes: 30));
    probe.reading = const PowerReading(level: 84, charging: false);
    await log.stopped();

    final all = await log.sessions();
    expect(all.length, 1);
    expect(all.single.startLevel, 90);
    expect(all.single.endLevel, 84);
    expect(all.single.length, const Duration(minutes: 62));
  });

  test('a long pause starts a new session', () async {
    await listen(const Duration(minutes: 30), from: 90, to: 88);
    clock.advance(const Duration(minutes: 20));
    await listen(const Duration(minutes: 30), from: 88, to: 85);

    expect((await log.sessions()).length, 2);
  });

  test('charging makes the drop meaningless, so there is no rate', () async {
    probe.reading = const PowerReading(level: 50, charging: true);
    await log.started();
    clock.advance(const Duration(hours: 1));
    probe.reading = const PowerReading(level: 60, charging: true);
    await log.stopped();

    final s = (await log.sessions()).single;
    expect(s.charged, isTrue);
    expect(s.percentPerHour, isNull);
  });

  test('too short a session gives no rate (1 % steps mean nothing)', () async {
    await listen(const Duration(minutes: 10), from: 80, to: 79);

    expect((await log.sessions()).single.percentPerHour, isNull);
  });

  test('the average counts only trustworthy sessions', () async {
    await listen(const Duration(hours: 1), from: 90, to: 84); // 6 %/h
    clock.advance(const Duration(hours: 1));
    await listen(const Duration(hours: 3), from: 84, to: 72); // 4 %/h
    clock.advance(const Duration(hours: 1));
    await listen(const Duration(minutes: 5), from: 72, to: 72); // too short

    final average = ListeningLog.average(await log.sessions())!;
    expect(average.sessions, 2);
    expect(average.percentPerHour, closeTo(18 / 4, 1e-9));
  });

  test('without a battery reading nothing is recorded', () async {
    probe.reading = null;
    await log.started();
    clock.advance(const Duration(hours: 1));
    await log.stopped();

    expect(await log.sessions(), isEmpty);
  });

  test('only the newest sessions are kept', () async {
    for (var i = 0; i < 5; i++) {
      await listen(const Duration(minutes: 30), from: 90, to: 88);
      clock.advance(const Duration(hours: 1));
    }
    final small = ListeningLog(
      store: SyncStateStore(db, (await db.select(db.servers).get()).first.id),
      probe: probe,
      clock: clock,
      keep: 3,
    );
    await listen(const Duration(minutes: 30), from: 90, to: 88);
    probe.reading = const PowerReading(level: 80, charging: false);
    await small.started();
    clock.advance(const Duration(minutes: 30));
    await small.stopped();

    expect((await small.sessions()).length, 3);
  });
}
