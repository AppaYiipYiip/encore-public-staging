import 'dart:io';

import 'package:drift/native.dart';
import 'package:encore/app/background_sync.dart';
import 'package:encore/core/clock.dart';
import 'package:encore/data/auth/credential_store.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/sync/sync_state_store.dart';
import 'package:encore/features/settings/settings_controller.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../support/fake_http.dart';
import '../support/fake_subsonic_server.dart';

class _RecordingScheduler implements BackgroundSyncScheduler {
  final List<int> applied = [];

  @override
  Future<void> apply({required int hours}) async => applied.add(hours);

  int runs = 0;

  @override
  Future<void> runOnceNow() async => runs++;
}

void main() {
  group('runBackgroundSync', () {
    late Directory dir;
    late File file;
    late FakeSubsonicServer server;
    late InMemoryCredentialStore credentials;
    late FakeClock clock;

    AppDatabase open() => AppDatabase(NativeDatabase(file));

    setUp(() {
      dir = Directory.systemTemp.createTempSync('encore_bg_');
      file = File('${dir.path}/encore.sqlite');
      server = FakeSubsonicServer()..seed(songCount: 12, albumCount: 2);
      credentials = InMemoryCredentialStore();
      clock = FakeClock(DateTime.utc(2026, 10, 15, 3));
    });

    tearDown(() {
      try {
        if (dir.existsSync()) dir.deleteSync(recursive: true);
      } on FileSystemException {
        // Windows keeps the sqlite file locked a moment longer; the temp
        // directory is cleaned by the OS later.
      }
    });

    Future<int> addServer(
        {String endpoints =
            '[{"label":"Home","url":"http://fake:4533"}]'}) async {
      final db = open();
      final id = await db.into(db.servers).insert(ServersCompanion.insert(
            name: 'Home',
            username: 'u',
            endpointsJson: endpoints,
            createdAtMs: 0,
          ));
      await db.close();
      return id;
    }

    Future<bool> run() => runBackgroundSync(
          openDatabase: open,
          credentials: credentials,
          clock: clock,
          dio: fakeDio(server.adapter),
        );

    test('nothing configured: done, no network', () async {
      expect(await run(), isTrue);
      expect(server.adapter.requests, isEmpty);
    });

    test('a server without a stored password is left alone', () async {
      await addServer();
      expect(await run(), isTrue);
      expect(server.adapter.requests, isEmpty);
    });

    test('syncs the library and closes the database', () async {
      final id = await addServer();
      await credentials.writePassword(id, 'secret');

      expect(await run(), isTrue);

      final db = open();
      expect(await db.select(db.tracks).get(), hasLength(12));
      final state = SyncStateStore(db, id);
      expect(await state.get(SyncStateStore.lastBackgroundResult), 'ok');
      expect(await state.getInt(SyncStateStore.lastBackgroundRunAtMs),
          clock.now().millisecondsSinceEpoch);
      await db.close();
    });

    test('delivers edits that were queued while the app was closed', () async {
      final id = await addServer();
      await credentials.writePassword(id, 'secret');
      server.adapter.routes['star'] = (_) => FakeResponse.json(subsonicOk({}));
      final seed = open();
      await seed.into(seed.outbox).insert(OutboxCompanion.insert(
            serverId: id,
            kind: 'star',
            payloadJson: '{"songIds":["s1"]}',
            createdAtMs: 0,
          ));
      await seed.close();

      expect(await run(), isTrue);

      expect(server.adapter.count('star'), 1);
      final db = open();
      expect(await db.select(db.outbox).get(), isEmpty);
      await db.close();
    });

    test('an unreachable server is not an error (the next period retries)',
        () async {
      final id = await addServer();
      await credentials.writePassword(id, 'secret');
      for (final method in ['ping', 'getScanStatus', 'getArtists']) {
        server.adapter.routes[method] =
            (_) => const FakeResponse.connectionError();
      }

      expect(await run(), isTrue);

      final db = open();
      expect(await db.select(db.tracks).get(), isEmpty);
      await db.close();
    });

    test('an unexpected failure asks WorkManager to retry', () async {
      final ok = await runBackgroundSync(
        openDatabase: () => throw StateError('disk full'),
        credentials: credentials,
        clock: clock,
        dio: fakeDio(server.adapter),
      );
      expect(ok, isFalse);
    });
  });

  group('background sync setting', () {
    setUp(() => SharedPreferences.setMockInitialValues({}));

    testWidgets('registers after start-up and follows changes, once per burst',
        (tester) async {
      final scheduler = _RecordingScheduler();
      final container = ProviderContainer(overrides: [
        backgroundSyncSchedulerProvider.overrideWithValue(scheduler),
      ]);
      addTearDown(container.dispose);

      container.read(backgroundSyncApplyProvider);
      await tester.pump(const Duration(seconds: 6));
      expect(scheduler.applied, [6], reason: 'default: every 6 hours');

      final settings = container.read(settingsProvider.notifier);
      settings.setBackgroundSyncHours(12);
      settings.setBackgroundSyncHours(24);
      await tester.pump(const Duration(seconds: 6));
      expect(scheduler.applied, [6, 24]);

      settings.setBackgroundSyncHours(0);
      await tester.pump(const Duration(seconds: 6));
      expect(scheduler.applied, [6, 24, 0]);
    });
  });

  test('labels and choices', () {
    expect(backgroundSyncLabel(0), 'Off');
    expect(backgroundSyncLabel(6), 'Every 6 hours');
    expect(kBackgroundSyncHourChoices, contains(0));
  });
}
