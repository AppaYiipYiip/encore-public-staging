import 'dart:async';
import 'dart:ui' show Color, Size;

import 'package:cached_network_image/cached_network_image.dart';
import 'package:drift/drift.dart' show BooleanExpressionOperators, Value;
import 'package:flutter/painting.dart' show ResizeImage;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:palette_generator/palette_generator.dart';

import '../../app/providers.dart';
import '../../core/logger.dart';
import '../../data/db/app_database.dart';
import '../../domain/artwork_color.dart';
import 'cover_art.dart';

/// Reads the representative swatch of the cover at [url] (replaced in
/// tests). [cacheKey] is the key the cover widgets use, so an already shown
/// cover is read from the disk cache instead of being downloaded again.
typedef SwatchExtractor = Future<Color?> Function(String url, String cacheKey);

final swatchExtractorProvider =
    Provider<SwatchExtractor>((ref) => extractSwatch);

/// Decodes the cover at 96 px and runs the palette quantiser (an isolate in
/// `palette_generator`), so extraction never blocks a frame.
Future<Color?> extractSwatch(String url, String cacheKey) async {
  try {
    final image = CachedNetworkImageProvider(
      url,
      cacheKey: cacheKey,
      cacheManager: coverCacheManager,
    );
    final palette = await PaletteGenerator.fromImageProvider(
      ResizeImage(image, width: 96, height: 96),
      size: const Size(96, 96),
      maximumColorCount: 12,
      timeout: const Duration(seconds: 6),
    );
    return chooseSwatch(
      vibrant: palette.vibrantColor?.color,
      dominant: palette.dominantColor?.color,
      darkVibrant: palette.darkVibrantColor?.color,
      muted: palette.mutedColor?.color,
    );
  } on Object catch (error) {
    Log.debug('artwork', 'palette extraction failed: $error');
    return null;
  }
}

/// What identifies an item's artwork: the album row (where the colour is
/// remembered) and/or the cover id (a song's `mf-...` or an album's `al-...`).
typedef ArtworkKey = ({String? albumId, String? coverArtId});

/// The representative colour of an item's artwork, or `null` when it cannot
/// be known (offline with the cover never cached, no cover). Callers turn it
/// into a background with `backdropFor` and fall back to a title-derived tint
/// so a screen is never colourless.
///
/// The swatch is stored on the album row, so each cover is analysed once per
/// install and the colour is available offline afterwards.
final artworkSwatchProvider =
    FutureProvider.autoDispose.family<Color?, ArtworkKey>((ref, key) async {
  final serverId = await ref.watch(activeServerIdProvider.future);
  if (serverId == null) return null;
  final db = ref.watch(databaseProvider);

  AlbumRow? album;
  final albumId = key.albumId;
  if (albumId != null) {
    album = await (db.select(db.albums)
          ..where((a) => a.serverId.equals(serverId) & a.id.equals(albumId))
          ..limit(1))
        .getSingleOrNull();
  }
  final stored = album?.dominantColor;
  if (stored != null) return Color(stored);

  final coverId = key.coverArtId ?? album?.coverArt;
  if (coverId == null || coverId.isEmpty) return null;
  // Works before the network session exists: the resolver then hands out a
  // placeholder URL with the real cache key, so a cached cover still decodes
  // (offline start) and an uncached one just fails fast.
  final resolver = ref.watch(coverArtResolverProvider);
  if (resolver == null) return null;

  final resolved = resolver.resolve(coverId, 160);
  final swatch = await ref.read(swatchExtractorProvider)(
      resolved.url.toString(), resolved.cacheKey);
  if (swatch == null) return null;

  final owner = album;
  if (owner != null) {
    unawaited((db.update(db.albums)
          ..where((a) => a.serverId.equals(serverId) & a.id.equals(owner.id)))
        .write(AlbumsCompanion(dominantColor: Value(swatch.toARGB32()))));
  }
  return swatch;
});
