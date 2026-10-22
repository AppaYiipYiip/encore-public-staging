import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/cover_sizes.dart';
import '../core/logger.dart';
import '../data/covers/cover_prefetcher.dart';
import '../features/common/cover_art.dart' show coverCacheManager;
import 'providers.dart';

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
      await coverCacheManager.downloadFile(
        session.coverArtUrl(id, size: size).toString(),
        key: CoverSize.key(serverId, id, size),
      );
    },
  );
});

/// On mobile data only this many covers, small size only: a background job must not eat a data plan (a big library is
/// finished on Wi-Fi).
const _mobileLimit = 120;

/// Keeps the covers of what a person is likely to see in the disk cache, so that offline shows covers and not letters (E3):
/// when the app starts, after every library sync and when the network comes back. Watched once by the app widget.
final coverPrefetchProvider = Provider<void>((ref) {
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
      await prefetcher.prefetch(
        ids,
        sizes: onWifi
            ? const [CoverSize.small, CoverSize.large]
            : const [CoverSize.small],
      );
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
