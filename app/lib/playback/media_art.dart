import 'dart:async';
import 'dart:io';

import '../core/cover_sizes.dart';
import '../core/logger.dart';

/// Artwork for the system media session (lock screen, notification, Bluetooth,
/// Android Auto).
///
/// Whatever is published there can be read by every app that sees media
/// controls. A server cover URL carries the Subsonic username, token and salt,
/// which can be replayed against the server, so **only a local file is ever
/// returned, or nothing** (docs/23, B24; ADR-017). The credentialed URL is used
/// to fetch the file into the cache and for nothing else.
class MediaArtResolver {
  MediaArtResolver({
    required this.serverId,
    required Future<File?> Function(String cacheKey) cachedFile,
    required Future<File?> Function(String url, String cacheKey) download,
    required String? Function(String coverArtId, int size) urlFor,
    this.wait = const Duration(seconds: 3),
    this.size = CoverSize.large,
  })  : _cachedFile = cachedFile,
        _download = download,
        _urlFor = urlFor;

  final int serverId;

  /// How long a request waits for a cover that is not cached yet. The download
  /// carries on after that and fills the cache for the next request.
  final Duration wait;
  final int size;

  final Future<File?> Function(String cacheKey) _cachedFile;
  final Future<File?> Function(String url, String cacheKey) _download;
  final String? Function(String coverArtId, int size) _urlFor;

  /// A `file:` URI for [coverArtId], or `null` (no session, still downloading,
  /// offline). Never a network URL.
  Future<Uri?> resolve(String coverArtId) async {
    final key = CoverSize.key(serverId, coverArtId, size);
    final hit = await _cachedFile(key);
    if (hit != null) return Uri.file(hit.path);
    // Seen in a row but not yet in the player (or offline): the other size will do for the lock screen.
    final other = await _cachedFile(
        CoverSize.key(serverId, coverArtId, CoverSize.otherThan(size)));
    if (other != null) return Uri.file(other.path);

    final url = _urlFor(coverArtId, size);
    if (url == null) return null;

    final fetching = _download(url, key);
    // If it outlasts the wait, it still finishes and fills the cache; its
    // late failure must not become an unhandled error.
    unawaited(fetching.then<void>(
      (_) {},
      onError: (Object error) =>
          Log.debug('art', 'cover $coverArtId was not fetched: $error'),
    ));
    try {
      final file = await fetching.timeout(wait);
      return file == null ? null : Uri.file(file.path);
    } on TimeoutException {
      return null;
    } on Exception catch (error) {
      Log.debug('art', 'cover $coverArtId was not fetched: $error');
      return null;
    }
  }
}
