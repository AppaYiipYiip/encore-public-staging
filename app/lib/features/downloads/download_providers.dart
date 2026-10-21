import 'dart:async';

import 'package:drift/drift.dart' show BooleanExpressionOperators;
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../core/stream_utils.dart';
import '../../data/db/app_database.dart';
import '../../data/downloads/background_downloader_transport.dart';
import '../../data/downloads/disk_space.dart';
import '../../data/downloads/download_manager.dart';
import '../../data/downloads/download_transport.dart';
import '../../data/repos/downloads_repository.dart';
import '../../domain/audio_quality.dart';
import '../../domain/storage_guard.dart';
import '../providers.dart';
import '../settings/settings_controller.dart';

/// Read/write access to what the user pinned for offline listening.
final downloadsRepositoryProvider = Provider<DownloadsRepository?>((ref) {
  final serverId = ref.watch(activeServerIdProvider).value;
  if (serverId == null) return null;
  return DownloadsRepository(
    ref.watch(databaseProvider),
    serverId,
    clock: ref.watch(clockProvider),
  );
});

/// Live state of one download toggle, keyed by `(type, id)`.
final pinStateProvider = StreamProvider.autoDispose
    .family<PinState, (PinTargetType, String)>((ref, target) {
  final repo = ref.watch(downloadsRepositoryProvider);
  if (repo == null) return Stream.value(PinState.none);
  // A big queue updates hundreds of rows per minute: 4 Hz is plenty.
  return repo
      .watchPinState(target.$1, target.$2)
      .throttleLatest(const Duration(milliseconds: 250));
});

final storageSummaryProvider =
    StreamProvider.autoDispose<StorageSummary>((ref) {
  final repo = ref.watch(downloadsRepositoryProvider);
  if (repo == null) return Stream.value(const StorageSummary());
  return repo.watchStorage().throttleLatest(const Duration(milliseconds: 500));
});

/// Downloaded tracks (Library > Downloaded).
final downloadedTracksProvider =
    StreamProvider.autoDispose<List<TrackRow>>((ref) {
  final repo = ref.watch(downloadsRepositoryProvider);
  if (repo == null) return const Stream<List<TrackRow>>.empty();
  return repo
      .watchDownloadedTracks()
      .throttleLatest(const Duration(milliseconds: 500));
});

/// A pin with a human title (for the storage screen).
class PinEntry {
  const PinEntry({
    required this.pin,
    required this.title,
    required this.kind,
  });

  final PinRow pin;
  final String title;
  final String kind;
}

final pinsProvider = StreamProvider.autoDispose<List<PinRow>>((ref) {
  final repo = ref.watch(downloadsRepositoryProvider);
  if (repo == null) return const Stream<List<PinRow>>.empty();
  return repo.watchPins();
});

final pinEntriesProvider =
    FutureProvider.autoDispose<List<PinEntry>>((ref) async {
  final pins = await ref.watch(pinsProvider.future);
  final db = ref.watch(databaseProvider);
  final entries = <PinEntry>[];
  for (final pin in pins) {
    String? title;
    String kind;
    switch (pin.targetType) {
      case 'playlist':
        kind = 'Playlist';
        title = (await (db.select(db.playlists)
                  ..where((p) =>
                      p.serverId.equals(pin.serverId) &
                      p.id.equals(pin.targetId)))
                .getSingleOrNull())
            ?.name;
      case 'album':
        kind = 'Album';
        title = (await (db.select(db.albums)
                  ..where((a) =>
                      a.serverId.equals(pin.serverId) &
                      a.id.equals(pin.targetId)))
                .getSingleOrNull())
            ?.name;
      case 'artist':
        kind = 'Artist';
        title = (await (db.select(db.artists)
                  ..where((a) =>
                      a.serverId.equals(pin.serverId) &
                      a.id.equals(pin.targetId)))
                .getSingleOrNull())
            ?.name;
      case 'liked':
        kind = 'Collection';
        title = 'Liked Songs';
      default:
        kind = 'Song';
        title = (await (db.select(db.tracks)
                  ..where((t) =>
                      t.serverId.equals(pin.serverId) &
                      t.id.equals(pin.targetId)))
                .getSingleOrNull())
            ?.title;
    }
    entries.add(PinEntry(
      pin: pin,
      title: title ?? 'Unavailable item',
      kind: kind,
    ));
  }
  return entries;
});

// ---------------------------------------------------------------- manager

/// The platform transfer layer (overridden in tests).
final downloadTransportProvider = Provider<DownloadTransport>((ref) {
  final transport = BackgroundDownloaderTransport();
  ref.onDispose(() => unawaited(transport.dispose()));
  return transport;
});

/// Lossy containers: re-encoding to an equal/higher rate is pointless.
const _lossy = {'mp3', 'opus', 'ogg', 'aac', 'm4a'};

/// Free space of the volume downloads use (overridden in tests).
final diskSpaceProvider = Provider<DiskSpace?>((ref) => PlatformDiskSpace());

/// Why downloads are paused, if they are (storage cap or a nearly full phone).
final downloadVerdictProvider = StreamProvider<StorageVerdict>((ref) async* {
  final manager = await ref.watch(downloadManagerProvider.future);
  if (manager == null) {
    yield StorageVerdict.ok;
    return;
  }
  yield manager.verdict;
  yield* manager.verdicts;
});

/// The reconciler that makes files match pins. Built once per server and
/// started immediately; reacts to pins, sync completions and network changes.
final downloadManagerProvider = FutureProvider<DownloadManager?>((ref) async {
  final serverId = await ref.watch(activeServerIdProvider.future);
  if (serverId == null) return null;
  // Not needed for the first screen: let start-up finish first.
  await Future<void>.delayed(const Duration(seconds: 2));

  final db = ref.watch(databaseProvider);
  final clock = ref.watch(clockProvider);
  final repo = DownloadsRepository(db, serverId, clock: clock);

  final manager = DownloadManager(
    db: db,
    serverId: serverId,
    repository: repo,
    transport: ref.watch(downloadTransportProvider),
    clock: clock,
    policy: () {
      final settings = ref.read(settingsProvider);
      final network = ref.read(networkKindProvider).value ?? NetworkKind.wifi;
      return DownloadPolicy(
        wifiOnly: settings.wifiOnlyDownloads,
        onWifi: network == NetworkKind.wifi,
        limitBytes: settings.downloadLimitBytes,
      );
    },
    diskSpace: ref.watch(diskSpaceProvider),
    urlBuilder: (id,
        {quality = AudioQuality.original, sourceSuffix, sourceBitRate}) async {
      final session = await ref.read(sessionProvider.future);
      if (session == null) throw StateError('Not signed in to a server');
      final cap = quality.bitRate;
      final alreadySmall = cap != null &&
          sourceBitRate != null &&
          sourceBitRate <= cap &&
          _lossy.contains(sourceSuffix?.toLowerCase());
      if (quality.isOriginal || alreadySmall) {
        return session.client.downloadUrl(id);
      }
      return session.client.streamUrl(
        id,
        format: quality.format,
        maxBitRate: cap,
        estimateContentLength: true,
      );
    },
  );
  await manager.start();

  ref.listen(networkKindProvider, (_, __) => manager.requestReconcile());
  // A raised cap lets a paused queue continue at once.
  ref.listen(
    settingsProvider.select((s) => s.downloadLimitBytes),
    (_, __) => manager.requestReconcile(),
  );
  ref.listen(syncStatusProvider, (previous, next) {
    final before = previous?.value?.lastSuccessAt;
    final after = next.value?.lastSuccessAt;
    if (after != null && after != before) manager.requestReconcile();
  });
  ref.onDispose(() => unawaited(manager.dispose()));
  return manager;
});

// ---------------------------------------------------------------- actions

/// UI-facing commands.
abstract interface class DownloadActions {
  Future<void> pin(PinTargetType type, String targetId,
      {AudioQuality? quality});

  /// Removes the pin *and* the files now (the user expects the space back).
  Future<void> unpin(PinTargetType type, String targetId);

  /// Retry failed downloads now instead of waiting for the back-off.
  Future<void> retry();

  /// Removes every pin and every downloaded file now (signing out).
  Future<void> removeAll();
}

class ManagerDownloadActions implements DownloadActions {
  ManagerDownloadActions({
    required DownloadsRepository? repository,
    required Future<DownloadManager?> Function() manager,
    required AudioQuality Function() defaultQuality,
    Future<void> Function(String playlistId)? ensurePlaylist,
  })  : _repo = repository,
        _manager = manager,
        _defaultQuality = defaultQuality,
        _ensurePlaylist = ensurePlaylist;

  /// Fetches a playlist's entries if background sync skipped them.
  final Future<void> Function(String playlistId)? _ensurePlaylist;

  final DownloadsRepository? _repo;
  final Future<DownloadManager?> Function() _manager;
  final AudioQuality Function() _defaultQuality;

  @override
  Future<void> pin(PinTargetType type, String targetId,
      {AudioQuality? quality}) async {
    await _repo?.pin(type, targetId, quality: quality ?? _defaultQuality());
    if (type == PinTargetType.playlist) {
      // Large smart playlists have no entries until asked for.
      try {
        await _ensurePlaylist?.call(targetId);
      } on Object {
        // The reconcile below simply sees an empty playlist; the next sync
        // retries.
      }
    }
    (await _manager())?.requestReconcile();
  }

  @override
  Future<void> unpin(PinTargetType type, String targetId) async {
    await _repo?.unpin(type, targetId);
    final manager = await _manager();
    await manager?.reconcile(immediateRemoval: true);
  }

  @override
  Future<void> retry() async => (await _manager())?.retryFailed();

  @override
  Future<void> removeAll() async {
    await _repo?.unpinAll();
    final manager = await _manager();
    await manager?.reconcile(immediateRemoval: true);
  }
}

final downloadActionsProvider = Provider<DownloadActions>((ref) {
  return ManagerDownloadActions(
    repository: ref.watch(downloadsRepositoryProvider),
    manager: () => ref.read(downloadManagerProvider.future),
    defaultQuality: () => ref.read(settingsProvider).downloadQuality,
    ensurePlaylist: (id) => ref.read(ensurePlaylistProvider(id).future),
  );
});
