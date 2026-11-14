import 'dart:async';

import 'package:drift/drift.dart' show BooleanExpressionOperators;
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../core/stream_utils.dart';
import '../../core/throttled_trigger.dart';
import '../../data/db/app_database.dart';
import '../../data/downloads/background_downloader_transport.dart';
import '../../data/downloads/disk_space.dart';
import '../../data/downloads/download_manager.dart';
import '../../data/downloads/download_transport.dart';
import '../../data/encore/signed_addresses.dart' show withQuality;
import '../../data/repos/downloads_repository.dart';
import '../../data/repos/release_store.dart';
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

/// The releases the sync says are saved (`cat:<id>`): what keeps "In your library" true after a restart, a reinstall and on a second phone.
final savedReleasesProvider = StreamProvider.autoDispose<Set<String>>((ref) {
  final server = ref.watch(activeServerProvider).value;
  if (server == null) return Stream.value(const <String>{});
  return ReleaseStore(ref.watch(databaseProvider), server.id).watchSaved();
});

/// What this phone saved and downloaded here, as it wrote it down (songs, title, artist, whether to keep them on the phone).
final phoneReleasesProvider =
    StreamProvider.autoDispose<Map<String, PhoneRelease>>((ref) {
  final server = ref.watch(activeServerProvider).value;
  if (server == null) return Stream.value(const <String, PhoneRelease>{});
  return ReleaseStore(ref.watch(databaseProvider), server.id).watchPhone();
});

/// A pin with a human title (for the storage screen).
class PinEntry {
  const PinEntry({
    required this.pin,
    required this.title,
    required this.kind,
    this.coverArt,
    this.artist,
    this.playlist,
    this.releaseId,
    this.releaseRefIds = const [],
  });

  final PinRow pin;
  final String title;
  final String kind;

  /// Set when this entry is a catalogue release the person downloaded (D-35): ONE entry for all its songs. [pin] is the first of their pins,
  /// [releaseRefIds] the songs the phone wrote down, [releaseId] is `cat:<catalogue album id>`.
  final String? releaseId;
  final List<String> releaseRefIds;

  /// The cover to draw (an album's, a playlist's own, an artist's picture), when there is one.
  final String? coverArt;

  /// The artist of an album or a song.
  final String? artist;
  final PlaylistRow? playlist;
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
  // A release the person downloaded is ONE entry, not N loose songs (D-35): the songs the phone wrote down for it are taken out of the loose
  // track pins and shown once, with the release's own title and artist (so it also reads offline).
  final phone = await ref.watch(phoneReleasesProvider.future);
  // A song can belong to more than one release (a single and the album that holds it): it is listed for each of them, so none of the
  // releases the person downloaded loses its entry.
  final released = <String, List<({String id, PhoneRelease release})>>{};
  for (final e in phone.entries) {
    if (!e.value.download) continue;
    for (final refId in e.value.refIds) {
      (released[refId] ??= []).add((id: e.key, release: e.value));
    }
  }
  final grouped = <String>{};
  final entries = <PinEntry>[];
  for (final pin in pins) {
    final of = pin.targetType == 'track' ? released[pin.targetId] : null;
    if (of != null) {
      for (final r in of) {
        if (grouped.add(r.id)) {
          entries.add(PinEntry(
            pin: pin,
            title: r.release.title ?? 'Album',
            kind: 'Album',
            artist: r.release.artist,
            releaseId: r.id,
            releaseRefIds: r.release.refIds,
          ));
        }
      }
      continue;
    }
    switch (pin.targetType) {
      case 'playlist':
        final row = await (db.select(db.playlists)
              ..where((p) =>
                  p.serverId.equals(pin.serverId) & p.id.equals(pin.targetId)))
            .getSingleOrNull();
        entries.add(PinEntry(
          pin: pin,
          title: row?.name ?? 'Unavailable item',
          kind: 'Playlist',
          coverArt: row?.coverArt,
          playlist: row,
        ));
      case 'album':
        final row = await (db.select(db.albums)
              ..where((a) =>
                  a.serverId.equals(pin.serverId) & a.id.equals(pin.targetId)))
            .getSingleOrNull();
        entries.add(PinEntry(
          pin: pin,
          title: row?.name ?? 'Unavailable item',
          kind: 'Album',
          coverArt: row?.coverArt,
          artist: row?.artist,
        ));
      case 'artist':
        final row = await (db.select(db.artists)
              ..where((a) =>
                  a.serverId.equals(pin.serverId) & a.id.equals(pin.targetId)))
            .getSingleOrNull();
        entries.add(PinEntry(
          pin: pin,
          title: row?.name ?? 'Unavailable item',
          kind: 'Artist',
          coverArt: row?.coverArt,
        ));
      case 'liked':
        entries
            .add(PinEntry(pin: pin, title: 'Liked Songs', kind: 'Collection'));
      default:
        final row = await (db.select(db.tracks)
              ..where((t) =>
                  t.serverId.equals(pin.serverId) & t.id.equals(pin.targetId)))
            .getSingleOrNull();
        entries.add(PinEntry(
          pin: pin,
          title: row?.title ?? 'Unavailable item',
          kind: 'Song',
          coverArt: row?.coverArt,
          artist: row?.artist,
        ));
    }
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

/// What the download manager is told about the person's settings and the link, each time it schedules work (one place, so it is testable):
/// "Download over Wi-Fi only" and whether the phone is on Wi-Fi decide whether anything may start; the Data saver value (the one derived
/// value, in force only on mobile data with the switch on, P4-24) makes new transfers go out at the capped quality.
DownloadPolicy downloadPolicyFor({
  required AppSettings settings,
  required NetworkKind network,
  required bool dataSaverInForce,
}) =>
    DownloadPolicy(
      wifiOnly: settings.wifiOnlyDownloads,
      onWifi: network == NetworkKind.wifi,
      limitBytes: settings.downloadLimitBytes,
      dataSaver: dataSaverInForce,
    );

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
    policy: () => downloadPolicyFor(
      settings: ref.read(settingsProvider),
      network: ref.read(networkKindProvider).value ?? NetworkKind.wifi,
      dataSaverInForce: ref.read(dataSaverInForceProvider),
    ),
    diskSpace: ref.watch(diskSpaceProvider),
    urlBuilder: (id,
        {quality = AudioQuality.original, sourceSuffix, sourceBitRate}) async {
      final session = await ref.read(sessionProvider.future);
      if (session == null) throw StateError('Not signed in to a server');
      final refId = id;
      if (session.encoreMode) {
        // The file to download is the server's kept copy of the song, named by the music server's id.
        final row = await (db.select(db.tracks)
              ..where((t) => t.serverId.equals(serverId) & t.id.equals(id)))
            .getSingleOrNull();
        final fileId = row?.fileId;
        if (fileId == null) {
          // Waiting, not failing: the server is getting it (a saved release, D-21); the next pass asks again.
          throw const SongNotKeptYet();
        }
        id = fileId;
      }
      final cap = quality.bitRate;
      final alreadySmall = cap != null &&
          sourceBitRate != null &&
          sourceBitRate <= cap &&
          _lossy.contains(sourceSuffix?.toLowerCase());
      if (session.encoreMode) {
        // The server's signed address of the song (its kept file, as it is or at the quality asked for): no login of the music server.
        final signed = await session.streams.forRef(refId);
        if (quality.isOriginal || alreadySmall) return signed;
        return withQuality(
          signed,
          format: quality.format,
          maxBitRate: cap,
          estimateContentLength: true,
        );
      }
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
  // Data saver coming into force or going out of it changes the quality new transfers are made at, and lets an upgrade start or hold.
  ref.listen(dataSaverInForceProvider, (_, __) => manager.requestReconcile());
  // Turning "Wi-Fi only" off lets what waited for Wi-Fi start now (and on, hold back what has not started).
  ref.listen(
    settingsProvider.select((s) => s.wifiOnlyDownloads),
    (_, __) => manager.requestReconcile(),
  );
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
  // The cheap check brought in changes (the server finished keeping songs, with their files): what waited for them starts now, not at the next
  // full pass, ten minutes later (audit B-108).
  final session = await ref.read(sessionProvider.future);
  // At most every 10 s: a pass reads every pinned song, and a server that keeps 14 songs a minute says so every 4 s.
  final lookAgain = ThrottledTrigger(
      const Duration(seconds: 10), () => manager.requestReconcile());
  final probeUpdated =
      session?.scheduler.probeUpdated.listen((_) => lookAgain());
  ref.onDispose(() {
    lookAgain.dispose();
    unawaited(probeUpdated?.cancel());
  });
  ref.onDispose(() => unawaited(manager.dispose()));
  return manager;
});

/// Why downloads are not moving, in words for the person, or `null` when they can: "Wi-Fi only" is on and the phone is on mobile data, or
/// there is no connection at all.
final downloadsWaitProvider = Provider<String?>((ref) {
  final wifiOnly =
      ref.watch(settingsProvider.select((s) => s.wifiOnlyDownloads));
  final network = ref.watch(networkKindProvider).value ?? NetworkKind.wifi;
  if (network == NetworkKind.none) return 'Waiting for a connection';
  if (wifiOnly && network != NetworkKind.wifi) return 'Waiting for Wi-Fi';
  return null;
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
