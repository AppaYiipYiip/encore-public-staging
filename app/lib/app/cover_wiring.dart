import 'dart:async';

import 'package:flutter_cache_manager/flutter_cache_manager.dart'
    show HttpExceptionWithStatus;
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/cover_sizes.dart';
import '../core/logger.dart';
import '../data/covers/cover_prefetcher.dart';
import '../features/common/cover_art.dart'
    show coverCacheManager, coverFileService, retireOldCoverCache;
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

/// What the background fetch may ask for on this link: on mobile data the small size only and few covers, so a background job does not eat a
/// data plan (a big library is finished on Wi-Fi). The same budget Data saver gives every picture (P4-24).
CoverBudget coverBudgetForNetwork(NetworkKind network) =>
    network == NetworkKind.wifi ? CoverBudget.full : CoverBudget.mobile;

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
    final budget = coverBudgetForNetwork(network);
    try {
      final ids =
          await repo.coverIdsToKeepOffline(limit: budget.backgroundLimit);
      await prefetcher.prefetch(ids, sizes: budget.sizes);
    } on Object catch (error) {
      Log.debug('covers', 'the background cover fetch stopped: $error');
    }
  }

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
