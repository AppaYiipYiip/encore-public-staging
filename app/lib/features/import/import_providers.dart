import 'dart:async';

import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../app/notifications.dart';
import '../../app/providers.dart';
import '../../core/logger.dart';
import '../../core/result.dart';
import '../../data/alerts/alerts_service.dart';
import '../../data/fetch/fetch_client.dart';
import '../../data/fetch/import_models.dart';
import '../instant/instant_controller.dart';
import '../settings/settings_controller.dart';

/// What the "play any song" service says it can do (`GET /api/info`). Older
/// services cannot read playlists or take an import.
final fetchInfoProvider = FutureProvider<FetchServiceInfo?>((ref) async {
  final uri = await ref.watch(fetchServiceProvider.future);
  if (uri == null) return null;
  return EncoreFetchClient.probe(uri);
});

/// The import side of the service, or `null` on a server that cannot take an
/// import (then the old download-portal page is all there is).
final playlistImportBackendProvider = Provider<PlaylistImportBackend?>((ref) {
  final backend = ref.watch(instantBackendProvider).value;
  final info = ref.watch(fetchInfoProvider).value;
  if (info == null || !info.canImport || !info.canReadPlaylists) return null;
  return backend is PlaylistImportBackend
      ? backend as PlaylistImportBackend
      : null;
});

/// One import with every song and where it is, kept fresh while it runs: what
/// the imported playlist's page shows (ADR-102). Asked every few seconds until
/// the import is over; a server that does not answer at all is an error, one
/// that blinks is not.
final importSongsProvider =
    StreamProvider.autoDispose.family<ImportJob, String>((ref, id) {
  final controller = StreamController<ImportJob>();
  Timer? timer;
  var failures = 0;
  var seen = false;

  Future<void> poll() async {
    final backend = ref.read(playlistImportBackendProvider);
    final result =
        backend == null ? null : await backend.importStatus(id, songs: true);
    if (controller.isClosed) return;
    final job = result?.valueOrNull;
    if (job != null) {
      seen = true;
      failures = 0;
      controller.add(job);
      if (job.isFinished) {
        unawaited(controller.close());
        return;
      }
    } else if (!seen && ++failures >= 3) {
      controller.addError(result?.failureOrNull ??
          const UnexpectedFailure('The import is not available.'));
      unawaited(controller.close());
      return;
    }
    timer = Timer(const Duration(seconds: 6), () => unawaited(poll()));
  }

  ref.onDispose(() {
    timer?.cancel();
    unawaited(controller.close());
  });
  unawaited(poll());
  return controller.stream;
});

const String _kDismissed = 'encore.importsDismissed';

/// The imports the server is running or has just finished for this person.
@immutable
class ImportsState {
  const ImportsState({
    this.jobs = const [],
    this.loaded = false,
    this.dismissed = const {},
  });

  final List<ImportJob> jobs;

  /// The server has answered at least once.
  final bool loaded;

  /// Finished imports the person closed on Home.
  final Set<String> dismissed;

  List<ImportJob> get running => [
        for (final j in jobs)
          if (j.isRunning) j
      ];

  /// Finished imports Home still announces: the last day, not closed.
  List<ImportJob> recentlyFinished(DateTime now) => [
        for (final j in jobs)
          if (j.isFinished &&
              !dismissed.contains(j.id) &&
              j.updatedAt != null &&
              now.millisecondsSinceEpoch / 1000 - j.updatedAt! < 86400)
            j,
      ];

  ImportsState copyWith({
    List<ImportJob>? jobs,
    bool? loaded,
    Set<String>? dismissed,
  }) =>
      ImportsState(
        jobs: jobs ?? this.jobs,
        loaded: loaded ?? this.loaded,
        dismissed: dismissed ?? this.dismissed,
      );
}

/// Keeps in step with the server's import queue (ADR-100, ADR-101).
///
/// The server does the fetching; this only asks how far it is. It asks as soon
/// as the app starts (which is also what lets a restarted server carry on in
/// the person's name), every few seconds while something runs, and when the
/// app comes back to the front. When songs arrive it asks the library to sync
/// so the new playlist shows up while it fills.
class ImportsController extends Notifier<ImportsState> {
  Timer? _timer;
  AppLifecycleListener? _lifecycle;
  final Map<String, int> _syncedAt = {};
  DateTime _lastSync = DateTime.fromMillisecondsSinceEpoch(0);

  /// How often the server is asked while an import runs.
  Duration pollEvery = const Duration(seconds: 4);

  @override
  ImportsState build() {
    ref.onDispose(() {
      _timer?.cancel();
      _lifecycle?.dispose();
    });
    _lifecycle = AppLifecycleListener(onResume: () => unawaited(refresh()));
    ref.listen<PlaylistImportBackend?>(
      playlistImportBackendProvider,
      (_, next) {
        if (next != null) unawaited(refresh());
      },
      fireImmediately: true,
    );
    unawaited(_loadDismissed());
    return const ImportsState();
  }

  Future<void> _loadDismissed() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final ids = prefs.getStringList(_kDismissed) ?? const [];
      if (ids.isEmpty) return;
      state = state.copyWith(dismissed: {...state.dismissed, ...ids});
    } on Object catch (error) {
      Log.debug('import', 'could not read the closed imports: $error');
    }
  }

  /// Asks the server how its imports are.
  Future<void> refresh() async {
    final backend = ref.read(playlistImportBackendProvider);
    if (backend == null) return;
    final result = await backend.imports();
    final jobs = result.valueOrNull;
    if (jobs == null) {
      // Not reachable right now: keep what is shown, try again soon if
      // something was running.
      Log.debug('import', 'imports not read: ${result.failureOrNull?.message}');
      if (state.running.isNotEmpty) _schedule(const Duration(seconds: 10));
      return;
    }
    _apply(jobs);
  }

  void _apply(List<ImportJob> jobs) {
    final before = {for (final j in state.jobs) j.id: j};
    state = state.copyWith(jobs: jobs, loaded: true);
    var wantSync = false;
    for (final job in jobs) {
      final was = before[job.id];
      final synced = _syncedAt[job.id];
      if (job.playlistReady || job.isLiked && job.added > 0) {
        if (synced == null ||
            job.added - synced >= 10 ||
            job.isFinished && synced != job.added) {
          wantSync = true;
          _syncedAt[job.id] = job.added;
        }
      }
      if (was != null && was.isRunning && job.isFinished) {
        wantSync = true;
        unawaited(_announce(job));
      }
    }
    if (wantSync) _syncLibrary();
    _poll();
  }

  /// The library picks up the new playlist (or the new likes).
  void _syncLibrary() {
    final now = DateTime.now();
    if (now.difference(_lastSync) < const Duration(seconds: 20)) return;
    _lastSync = now;
    ref.read(sessionProvider).value?.scheduler.requestSync();
  }

  Future<void> _announce(ImportJob job) async {
    if (!ref.read(settingsProvider).alertsImports) return;
    final body = job.message ??
        '${job.added} of ${job.total} songs are in your library now.';
    try {
      await ref.read(localNotificationsProvider).show(AlertNotification(
            id: 7301,
            title: job.isLiked
                ? 'Your liked songs are imported'
                : '"${job.name}" is ready',
            body: body,
            route: '/settings/import',
          ));
    } on Object catch (error) {
      Log.debug('import', 'could not announce the end of an import: $error');
    }
  }

  void _poll() {
    _timer?.cancel();
    _timer = null;
    if (state.running.isNotEmpty) _schedule(pollEvery);
  }

  void _schedule(Duration delay) {
    _timer?.cancel();
    _timer = Timer(delay, () => unawaited(refresh()));
  }

  /// Hands a read list to the server. The new import shows up at once.
  Future<Result<ImportJob>> start({
    required String name,
    required String source,
    required List<ImportedTrack> tracks,
    bool liked = false,
  }) async {
    final backend = ref.read(playlistImportBackendProvider);
    if (backend == null) {
      return const Result.err(
          UnexpectedFailure('This server cannot import playlists.'));
    }
    final result = await backend.startImport(
        name: name, source: source, tracks: tracks, liked: liked);
    final job = result.valueOrNull;
    if (job != null) {
      state = state.copyWith(
        jobs: [
          job,
          for (final j in state.jobs)
            if (j.id != job.id) j
        ],
        loaded: true,
      );
      _poll();
    }
    return result;
  }

  /// Stops an import; the songs that arrived stay.
  Future<void> cancel(String id) async {
    final backend = ref.read(playlistImportBackendProvider);
    if (backend == null) return;
    final job = (await backend.cancelImport(id)).valueOrNull;
    if (job == null) return;
    _apply([for (final j in state.jobs) j.id == id ? job : j]);
  }

  /// Drops songs from an import (their numbers in its list): the ones not fetched yet never will be.
  Future<bool> skip(String id, List<int> indexes) async {
    final backend = ref.read(playlistImportBackendProvider);
    if (backend == null) return false;
    final job = (await backend.skipSongs(id, indexes)).valueOrNull;
    if (job == null) return false;
    _apply([for (final j in state.jobs) j.id == id ? job : j]);
    return true;
  }

  /// One import with the list of songs it could not add.
  Future<ImportJob?> details(String id) async =>
      (await ref.read(playlistImportBackendProvider)?.importStatus(id))
          ?.valueOrNull;

  /// "Got it": a finished import stops being announced on Home.
  Future<void> dismiss(String id) async {
    final next = {...state.dismissed, id};
    state = state.copyWith(dismissed: next);
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setStringList(_kDismissed, next.toList());
    } on Object catch (error) {
      Log.debug('import', 'could not remember a closed import: $error');
    }
  }
}

final importsProvider =
    NotifierProvider<ImportsController, ImportsState>(ImportsController.new);
