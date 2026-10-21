import 'dart:async';

import 'package:dio/dio.dart';
import 'package:drift/drift.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:workmanager/workmanager.dart';

import '../core/clock.dart';
import '../core/logger.dart';
import '../data/alerts/alerts_service.dart';
import '../data/auth/credential_store.dart';
import '../data/catalogue/catalogue_models.dart';
import '../data/catalogue/deezer_client.dart';
import '../data/db/app_database.dart';
import '../data/db/open_database.dart';
import '../data/sync/sync_engine.dart';
import '../data/sync/sync_state_store.dart';
import '../domain/release_alerts.dart';
import '../features/settings/settings_controller.dart';
import 'alerts_wiring.dart';
import 'notifications.dart';
import 'session.dart';

/// Unique name of the periodic job (Android WorkManager).
const String kBackgroundSyncJob = 'encore.background-sync';

/// Entry point WorkManager starts in a fresh Flutter engine when the job is
/// due - the app does not have to be running.
@pragma('vm:entry-point')
void backgroundSyncDispatcher() {
  Workmanager().executeTask((task, input) => runBackgroundSync());
}

/// One background pass: bring the library up to date and deliver queued
/// local edits (likes, playlist changes, plays) - the same work the
/// foreground scheduler does, once, then stop.
///
/// Returns `true` when the job is done (including "nothing to do": no
/// server, offline, password missing - the next period tries again) and
/// `false` only for an unexpected error, so WorkManager retries with
/// back-off.
///
/// Dependencies are injectable so the pass is testable without a device.
Future<bool> runBackgroundSync({
  AppDatabase Function()? openDatabase,
  CredentialStore? credentials,
  Clock clock = const SystemClock(),
  Dio? dio,
  AlertSink? alertSink,
  CatalogueClient? catalogue,
  Future<List<ImportSnapshot>?> Function()? importSnapshots,
}) async {
  AppDatabase? db;
  ServerSession? session;
  try {
    db = (openDatabase ?? openAppDatabase)();
    final store = credentials ?? SecureCredentialStore();
    final server = await (db.select(db.servers)
          ..orderBy([(s) => OrderingTerm.asc(s.id)])
          ..limit(1))
        .getSingleOrNull();
    if (server == null) return true;
    final password = await store.readPassword(server.id);
    if (password == null || password.isEmpty) return true;

    session = await ServerSession.create(
      db: db,
      server: server,
      password: password,
      dio: dio,
      clock: clock,
    );
    await session.endpoints.resolve();
    final outcome = await session.sync.run(reason: SyncReason.scheduled);
    final state = SyncStateStore(db, server.id);
    switch (outcome) {
      case SyncCompleted(:final stats):
        Log.info('background',
            'sync done: tracks=${stats.tracks} full=${stats.libraryPhaseRan}');
        await state.set(SyncStateStore.lastBackgroundResult, 'ok');
        // New music from artists you play, new releases, import progress
        // (ADR-051). Never lets a notification problem fail the sync job.
        try {
          final report = await AlertsService(
            db: db,
            serverId: server.id,
            clock: clock,
            sink: alertSink ?? LocalNotifications(),
            catalogue: catalogue ?? DeezerClient(),
            importSnapshots: importSnapshots ??
                () => readPortalImports(
                      credentials: store,
                      fallbackUser: server.username,
                      fallbackPassword: password,
                    ),
          ).run(settings: await readAlertSettings());
          Log.info(
              'background',
              'alerts: arrivals=${report.arrivals} releases=${report.releases} '
                  'imports=${report.imports}');
        } on Object catch (error) {
          Log.warn('background', 'alerts failed', error);
        }
      case SyncFailed(:final failure):
        // Offline, server asleep, wrong password: nothing a retry in a few
        // minutes would fix better than the next scheduled run.
        Log.info('background', 'sync did not finish: ${failure.message}');
        await state.set(SyncStateStore.lastBackgroundResult, failure.message);
      case SyncCancelled():
        break;
      case SyncBusy():
        // The open app is already syncing (or delivering): its result lands in
        // the same database, so there is nothing for this pass to do.
        Log.info('background', 'the app is already syncing; nothing to do');
    }
    await state.setInt(
      SyncStateStore.lastBackgroundRunAtMs,
      clock.now().millisecondsSinceEpoch,
    );
    return true;
  } on Object catch (error, stack) {
    Log.error('background', 'background sync crashed', error, stack);
    return false;
  } finally {
    try {
      await session?.dispose();
    } on Object {
      // The process is about to be torn down anyway.
    }
    await db?.close();
  }
}

/// Which options the user can pick for "Background sync".
const List<int> kBackgroundSyncHourChoices = [0, 3, 6, 12, 24];

String backgroundSyncLabel(int hours) =>
    hours <= 0 ? 'Off' : 'Every $hours hours';

/// Registers or cancels the periodic job (Android).
///
/// Behind an interface so settings code and tests do not need the platform
/// plugin.
abstract interface class BackgroundSyncScheduler {
  /// `hours <= 0` cancels the job.
  Future<void> apply({required int hours});

  /// Runs one pass as soon as the system allows (Diagnostics: proves the
  /// job works on this phone without waiting hours).
  Future<void> runOnceNow();
}

class WorkmanagerSyncScheduler implements BackgroundSyncScheduler {
  bool _initialised = false;

  Future<void> _ensureInitialised() async {
    if (_initialised) return;
    await Workmanager().initialize(backgroundSyncDispatcher);
    _initialised = true;
  }

  @override
  Future<void> runOnceNow() async {
    if (kIsWeb || defaultTargetPlatform != TargetPlatform.android) return;
    try {
      await _ensureInitialised();
      await Workmanager().registerOneOffTask(
        '$kBackgroundSyncJob.once',
        kBackgroundSyncJob,
        existingWorkPolicy: ExistingWorkPolicy.replace,
        constraints: Constraints(networkType: NetworkType.connected),
      );
    } on Object catch (error) {
      Log.warn('background', 'could not start a background pass', error);
    }
  }

  @override
  Future<void> apply({required int hours}) async {
    if (kIsWeb || defaultTargetPlatform != TargetPlatform.android) return;
    try {
      await _ensureInitialised();
      if (hours <= 0) {
        await Workmanager().cancelByUniqueName(kBackgroundSyncJob);
        return;
      }
      await Workmanager().registerPeriodicTask(
        kBackgroundSyncJob,
        kBackgroundSyncJob,
        frequency: Duration(hours: hours),
        // The system may run it anywhere in the last quarter of the period,
        // which lets it batch with other apps' work (battery).
        flexInterval: Duration(minutes: hours * 15),
        initialDelay: const Duration(minutes: 30),
        existingWorkPolicy: ExistingPeriodicWorkPolicy.update,
        constraints: Constraints(
          networkType: NetworkType.connected,
          requiresBatteryNotLow: true,
        ),
        backoffPolicy: BackoffPolicy.exponential,
        backoffPolicyDelay: const Duration(minutes: 10),
      );
      Log.info('background', 'periodic sync every $hours h registered');
    } on Object catch (error) {
      // Scheduling is an optimisation: the app still syncs when opened.
      Log.warn('background', 'could not schedule background sync', error);
    }
  }
}

/// The platform job scheduler (overridden in tests).
final backgroundSyncSchedulerProvider = Provider<BackgroundSyncScheduler>(
  (ref) => WorkmanagerSyncScheduler(),
);

/// Keeps the periodic job in line with the "Sync while the app is closed"
/// setting. Registration waits a few seconds after the setting is known so it
/// never competes with start-up, and a burst of changes registers once.
final backgroundSyncApplyProvider = Provider<void>((ref) {
  Timer? pending;
  void apply(int hours) {
    pending?.cancel();
    pending = Timer(const Duration(seconds: 5), () {
      unawaited(ref.read(backgroundSyncSchedulerProvider).apply(hours: hours));
    });
  }

  ref.onDispose(() => pending?.cancel());
  apply(ref.read(settingsProvider).backgroundSyncHours);
  ref.listen(
    settingsProvider.select((s) => s.backgroundSyncHours),
    (_, hours) => apply(hours),
  );
});
