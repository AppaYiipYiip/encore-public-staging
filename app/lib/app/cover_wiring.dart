import 'dart:async';

import 'package:flutter_cache_manager/flutter_cache_manager.dart'
    show HttpExceptionWithStatus;
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/cover_sizes.dart';
import '../core/logger.dart';
import '../data/covers/cover_prefetcher.dart';
import '../features/common/cover_art.dart'
    show coverCacheManager, coverFileService, retireOldCoverCache;
import '../features/downloads/download_providers.dart'
    show downloadedTracksProvider;
import 'providers.dart';

/// A picture the server refuses as not valid (401) makes the app renew its cover ticket (`CoverPassHolder.refused`), so a ticket that stopped
/// being good (the server was reinstalled, its signing secret changed) heals itself instead of leaving every picture a letter for a week.
/// Watched once by the app widget.
final coverRefusalProvider = Provider<void>((ref) {
  final session = ref.watch(sessionProvider).value;
  coverFileService.onUnauthorized = session == null
      ? null
      : (url) => session.covers.refused(url.queryParameters['sig']);
  ref.onDispose(() => coverFileService.onUnauthorized = null);
});

/// The covers of the signed-in server's library, fetched into the disk cache in the background (null before sign-in).
final coverPrefetcherProvider = Provider<CoverPrefetcher?>((ref) {
  final serverId = ref.watch(activeServerIdProvider).value;
  final session = ref.watch(sessionProvider).value;
  if (serverId == null || session == null) return null;
  return CoverPrefetcher(
    serverId: serverId,
    isCached: (key) async =>
        await coverCacheManager.getFileFromCache(key) != null,
    pin: (key) => coverCacheManager.pin(key, owner: serverId),
    retain: (wanted) async {
      await coverCacheManager.retainOnly(wanted, owner: serverId);
    },
    fetch: (id, size) async {
      // On an Encore server the address is written with the cover ticket: get it first (it is kept for days, so this is one question at most).
      await session.covers.ensure();
      final url = session.coverArtUrl(id, size: size);
      // No ticket yet (the server did not answer): the next prefetch asks again.
      if (url == null) return;
      try {
        await coverCacheManager.downloadFile(
          url.toString(),
          key: CoverSize.key(serverId, id, size),
        );
      } on HttpExceptionWithStatus catch (error) {
        // The server has no picture for this one: nothing to keep, and not a sign that the network is gone.
        if (error.statusCode != 404) rethrow;
      }
    },
  );
});

/// On mobile data only this many covers, small size only: a background job must not eat a data plan (a big library is
/// finished on Wi-Fi).
const _mobileLimit = 120;

/// Keeps the covers of what a person is likely to see in the disk cache, so that offline shows covers and not letters (E3):
/// when the app starts, after every library sync and when the network comes back. Watched once by the app widget.
final coverPrefetchProvider = Provider<void>((ref) {
  unawaited(retireOldCoverCache());
  final prefetcher = ref.watch(coverPrefetcherProvider);
  final repo = ref.watch(libraryRepositoryProvider);
  if (prefetcher == null || repo == null) return;

  Future<void> run() async {
    final network = ref.read(networkKindProvider).value ?? NetworkKind.wifi;
    if (network == NetworkKind.none) return;
    final onWifi = network == NetworkKind.wifi;
    try {
      final ids =
          await repo.coverIdsToKeepOffline(limit: onWifi ? 600 : _mobileLimit);
      final sizes = onWifi
          ? const [CoverSize.small, CoverSize.large]
          : const [CoverSize.small];
      await prefetcher.prefetch(ids, sizes: sizes);
      // What the downloaded songs need is PINNED, once each and with no limit: it stays whatever else the cache holds or the system clears,
      // and is released only when no downloaded song needs it any more (P1-10).
      await prefetcher.keepPinned(await repo.coverIdsOfDownloads(),
          sizes: sizes);
    } on Object catch (error) {
      Log.debug('covers', 'the background cover fetch stopped: $error');
    }
  }

  // A download that finishes (or is removed) changes what must be pinned. A bulk download finishes a song every few seconds: wait for it to settle.
  Timer? settle;
  ref.onDispose(() => settle?.cancel());
  ref.listen(downloadedTracksProvider, (previous, next) {
    if (!next.hasValue) return;
    settle?.cancel();
    settle = Timer(const Duration(seconds: 5), () => unawaited(run()));
  });

  ref.listen(syncStatusProvider, (previous, next) {
    final after = next.value?.lastSuccessAt;
    if (after != null && after != previous?.value?.lastSuccessAt) {
      unawaited(run());
    }
  });
  ref.listen(networkKindProvider, (previous, next) {
    if (previous?.value == NetworkKind.none &&
        next.value != null &&
        next.value != NetworkKind.none) {
      unawaited(run());
    }
  });
  unawaited(run());
});
