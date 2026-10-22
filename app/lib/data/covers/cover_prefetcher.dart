import 'dart:async';

import '../../core/cover_sizes.dart';
import '../../core/logger.dart';

/// Whether a cover is already in the disk cache under [cacheKey].
typedef CoverIsCached = Future<bool> Function(String cacheKey);

/// Downloads the cover [coverArtId] at [size] into the disk cache (throws when the network or the server says no).
typedef CoverFetch = Future<void> Function(String coverArtId, int size);

/// Puts the covers of what a person is likely to see into the disk cache while the network is there, so that offline the app
/// shows covers and not letters (E3). It knows nothing of screens: it is given cover ids, in the order they matter, and fetches
/// what is not cached yet, two at a time, giving up when the network is plainly gone.
class CoverPrefetcher {
  CoverPrefetcher({
    required this.serverId,
    required CoverIsCached isCached,
    required CoverFetch fetch,
    this.concurrency = 2,
    this.giveUpAfter = 4,
  })  : _isCached = isCached,
        _fetch = fetch;

  final int serverId;
  final CoverIsCached _isCached;
  final CoverFetch _fetch;

  /// How many covers are downloaded at once: a background job, it never competes with the song that is playing.
  final int concurrency;

  /// This many failures in a row mean the network (or the server) is gone: the run ends instead of trying every cover.
  final int giveUpAfter;

  Future<void> _turn = Future<void>.value();

  /// Fetches what is missing among [ids] at each of [sizes] and answers how many were fetched. Runs one after the other
  /// (asking while a run is going waits for it); covers already cached cost one look-up each.
  Future<int> prefetch(
    Iterable<String> ids, {
    List<int> sizes = const [CoverSize.small, CoverSize.large],
  }) {
    final wanted = [...ids];
    final run = _turn.then((_) => _run(wanted, sizes));
    _turn = run.then<void>((_) {}, onError: (Object _) {});
    return run;
  }

  Future<int> _run(List<String> ids, List<int> sizes) async {
    final todo = <(String, int)>[];
    final seen = <String>{};
    for (final id in ids) {
      if (id.isEmpty || !seen.add(id)) continue;
      for (final size in sizes) {
        if (!await _isCached(CoverSize.key(serverId, id, size))) {
          todo.add((id, size));
        }
      }
    }
    if (todo.isEmpty) return 0;

    var next = 0;
    var fetched = 0;
    var failures = 0;
    Future<void> worker() async {
      while (failures < giveUpAfter && next < todo.length) {
        final (id, size) = todo[next++];
        try {
          await _fetch(id, size);
          fetched++;
          failures = 0;
        } on Object catch (error) {
          failures++;
          Log.debug('covers', 'cover $id ($size) was not fetched: $error');
        }
      }
    }

    await Future.wait([for (var i = 0; i < concurrency; i++) worker()]);
    if (failures >= giveUpAfter) {
      Log.debug(
          'covers', 'giving up for now after $failures failures in a row');
    }
    return fetched;
  }
}
