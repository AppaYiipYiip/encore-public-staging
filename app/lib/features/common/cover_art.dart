import 'dart:io';

import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:flutter_cache_manager/flutter_cache_manager.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path_provider/path_provider.dart';

import '../../app/providers.dart';
import '../../core/logger.dart';
import '../../data/covers/cover_file_service.dart';
import '../../design/tokens.dart';
import '../../domain/mosaic_layout.dart';
import '../requests/request_providers.dart';

/// Disk cache for artwork. The default manager keeps only 200 objects, which
/// makes covers vanish offline in a 500-album library, so this one is sized
/// for a real library and keeps files for a year (cover ids embed a content
/// hash, so changed art gets a new key).
///
/// Its name says which kind of cover it holds: `encoreCovers` held the music server's blank record for every album without art (see
/// [CoverFileService]); that cache is thrown away ([retireOldCoverCache]) and this one never stores it.
final CacheManager coverCacheManager = CacheManager(
  Config(
    'encoreCovers2',
    stalePeriod: const Duration(days: 365),
    maxNrOfCacheObjects: 8000,
    fileService: coverFileService,
  ),
);

/// The file service of [coverCacheManager]; the signed-in session hooks its refused-ticket renewal into it (`coverRefusalProvider`).
final CoverFileService coverFileService = CoverFileService();

bool _oldCoverCacheRetired = false;

/// Deletes the cover cache this app used before pictures with no art were refused; once per run (it costs nothing when it is gone).
Future<void> retireOldCoverCache() async {
  if (_oldCoverCacheRetired) return;
  _oldCoverCacheRetired = true;
  try {
    final base = await getTemporaryDirectory();
    final old = Directory('${base.path}/encoreCovers');
    if (old.existsSync()) await old.delete(recursive: true);
  } on Object catch (error) {
    Log.debug('covers', 'the old cover cache was not deleted: $error');
  }
}

/// Artwork that always shows *something* sensible (R-09):
/// the item's own picture -> a golden-ratio mosaic of related covers -> a
/// deterministic gradient with a monogram.
///
/// Fills its parent; wrap in `SizedBox`/`AspectRatio` to size it.
class CoverArt extends ConsumerWidget {
  const CoverArt({
    super.key,
    this.coverArtId,
    this.imageUrl,
    this.mosaicIds = const [],
    this.fallbackLabel,
    this.fallbackArtist,
    this.radius = Radii.art,
    this.circular = false,
    this.fit = BoxFit.cover,
    this.monogram = true,
  });

  final String? coverArtId;

  /// A direct artwork URL (catalogue results); used when there is no server
  /// cover id.
  final String? imageUrl;

  /// Related cover ids used for the collage when [coverArtId] is missing or
  /// fails to load (e.g. a playlist's albums).
  final List<String> mosaicIds;

  /// Text the gradient/monogram fallback is derived from (title).
  final String? fallbackLabel;

  /// With [fallbackLabel] (an album title), lets the catalogue supply a cover
  /// when the server has none.
  final String? fallbackArtist;
  final double radius;
  final bool circular;
  final BoxFit fit;

  /// Show initials on the gradient fallback (off inside mosaic tiles).
  final bool monogram;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final resolver = ref.watch(coverArtResolverProvider);
    final dpr = MediaQuery.devicePixelRatioOf(context);

    final Widget content = LayoutBuilder(
      builder: (context, constraints) {
        final logical = constraints.biggest.shortestSide.isFinite
            ? constraints.biggest.shortestSide
            : 160.0;
        final px = (logical * dpr).ceil();

        Widget fallback() {
          if (mosaicIds.isNotEmpty) {
            return CoverMosaic(coverIds: mosaicIds, label: fallbackLabel);
          }
          final gradient =
              GradientFallback(label: fallbackLabel, monogram: monogram);
          final artist = fallbackArtist;
          final title = fallbackLabel;
          if (artist == null || title == null || artist.isEmpty) {
            return gradient;
          }
          return _CatalogueCover(
            artist: artist,
            title: title,
            fit: fit,
            px: px,
            placeholder: gradient,
          );
        }

        final direct = imageUrl;
        if ((coverArtId == null || coverArtId!.isEmpty) &&
            direct != null &&
            direct.isNotEmpty) {
          return CachedNetworkImage(
            imageUrl: direct,
            cacheKey: 'url:$direct',
            cacheManager: coverCacheManager,
            fit: fit,
            memCacheWidth: CoverArtResolver.bucket(px),
            fadeInDuration: const Duration(milliseconds: 150),
            fadeOutDuration: Duration.zero,
            placeholder: (_, __) =>
                ColoredBox(color: context.colors.surfaceHigh),
            errorWidget: (_, __, ___) => fallback(),
          );
        }

        final id = coverArtId;
        if (id == null || id.isEmpty || resolver == null) return fallback();

        final r = resolver.resolve(id, px);
        return CachedNetworkImage(
          // The cache key stays the same when the cover ticket arrives or is renewed (a refused one is replaced); the key of the widget is the
          // address, which changes with the ticket, and says "ask again": a picture that was refused must not stay a letter for good.
          key: ValueKey(r.url.toString()),
          imageUrl: r.url.toString(),
          cacheKey: r.cacheKey,
          cacheManager: coverCacheManager,
          fit: fit,
          memCacheWidth: CoverArtResolver.bucket(px),
          fadeInDuration: const Duration(milliseconds: 150),
          fadeOutDuration: Duration.zero,
          placeholder: (_, __) => ColoredBox(color: context.colors.surfaceHigh),
          // Offline, a cover seen at the other size (a row, then the player) still shows: only then the gradient.
          errorWidget: (_, __, ___) => _CachedOtherSize(
            cacheKey: resolver.alternateKey(id, px),
            fit: fit,
            px: px,
            fallback: fallback,
          ),
        );
      },
    );

    if (circular) return ClipOval(child: content);
    if (radius <= 0) return content;
    return ClipRRect(
        borderRadius: BorderRadius.circular(radius), child: content);
  }
}

/// The cover at the size that is cached, scaled, when the size asked for could not be loaded (offline, E3). Nothing cached
/// either: [fallback], the gradient.
class _CachedOtherSize extends StatefulWidget {
  const _CachedOtherSize({
    required this.cacheKey,
    required this.fit,
    required this.px,
    required this.fallback,
  });

  final String cacheKey;
  final BoxFit fit;
  final int px;
  final Widget Function() fallback;

  @override
  State<_CachedOtherSize> createState() => _CachedOtherSizeState();
}

class _CachedOtherSizeState extends State<_CachedOtherSize> {
  late Future<FileInfo?> _file =
      coverCacheManager.getFileFromCache(widget.cacheKey);

  @override
  void didUpdateWidget(_CachedOtherSize old) {
    super.didUpdateWidget(old);
    if (old.cacheKey != widget.cacheKey) {
      _file = coverCacheManager.getFileFromCache(widget.cacheKey);
    }
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<FileInfo?>(
      future: _file,
      builder: (context, snapshot) {
        final file = snapshot.data?.file;
        if (file == null) return widget.fallback();
        return Image.file(
          file,
          fit: widget.fit,
          cacheWidth: CoverArtResolver.bucket(widget.px),
          gaplessPlayback: true,
          errorBuilder: (_, __, ___) => widget.fallback(),
        );
      },
    );
  }
}

/// Shows the catalogue's cover for an album the server has none for.
class _CatalogueCover extends ConsumerWidget {
  const _CatalogueCover({
    required this.artist,
    required this.title,
    required this.fit,
    required this.px,
    required this.placeholder,
  });

  final String artist;
  final String title;
  final BoxFit fit;
  final int px;
  final Widget placeholder;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final url = ref.watch(coverFallbackProvider((artist, title))).value;
    if (url == null) return placeholder;
    return CachedNetworkImage(
      imageUrl: url,
      cacheKey: 'url:$url',
      cacheManager: coverCacheManager,
      fit: fit,
      memCacheWidth: CoverArtResolver.bucket(px),
      fadeInDuration: const Duration(milliseconds: 150),
      fadeOutDuration: Duration.zero,
      placeholder: (_, __) => placeholder,
      errorWidget: (_, __, ___) => placeholder,
    );
  }
}

/// Golden-ratio collage of several covers (ADR-024).
class CoverMosaic extends ConsumerWidget {
  const CoverMosaic({super.key, required this.coverIds, this.label});

  final List<String> coverIds;
  final String? label;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ids = MosaicLayout.pickCovers(coverIds);
    if (ids.isEmpty) return GradientFallback(label: label);
    final tiles = MosaicLayout.compute(ids.length);
    final bg = context.colors.surfaceHigh;

    return LayoutBuilder(
      builder: (context, c) {
        final w = c.maxWidth.isFinite ? c.maxWidth : 160.0;
        final h = c.maxHeight.isFinite ? c.maxHeight : w;
        return Stack(
          fit: StackFit.expand,
          children: [
            ColoredBox(color: bg),
            for (var i = 0; i < tiles.length; i++)
              Positioned(
                left: tiles[i].left * w,
                top: tiles[i].top * h,
                width: tiles[i].width * w,
                height: tiles[i].height * h,
                child: CoverArt(
                  coverArtId: ids[i],
                  radius: 0,
                  // A failing tile shows a gradient seeded by its own id (so
                  // tiles differ), never a nested mosaic.
                  fallbackLabel: ids[i],
                  monogram: false,
                ),
              ),
          ],
        );
      },
    );
  }
}

/// Deterministic gradient + monogram, derived from [label] so the same item
/// always looks the same.
class GradientFallback extends StatelessWidget {
  const GradientFallback({super.key, this.label, this.monogram = true});

  final String? label;
  final bool monogram;

  static const _hues = [158.0, 200.0, 262.0, 320.0, 12.0, 38.0, 96.0, 226.0];

  @override
  Widget build(BuildContext context) {
    final text = (label ?? '').trim();
    final seed =
        text.isEmpty ? 0 : text.codeUnits.fold<int>(7, (a, b) => a * 31 + b);
    final hue = _hues[seed.abs() % _hues.length];
    final a = HSLColor.fromAHSL(1, hue, 0.50, 0.34).toColor();
    final b = HSLColor.fromAHSL(1, (hue + 28) % 360, 0.55, 0.20).toColor();
    final letters = monogram ? _monogram(text) : '';

    return DecoratedBox(
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [a, b],
        ),
      ),
      child: LayoutBuilder(builder: (context, c) {
        final side =
            c.biggest.shortestSide.isFinite ? c.biggest.shortestSide : 100;
        return Center(
          child: letters.isEmpty
              ? (monogram
                  ? Icon(Icons.music_note_rounded,
                      size: side * 0.42,
                      color: Colors.white.withValues(alpha: 0.85))
                  : const SizedBox.shrink())
              : Text(
                  letters,
                  maxLines: 1,
                  style: TextStyle(
                    fontFamily: 'Figtree',
                    fontWeight: FontWeight.w800,
                    fontSize: side * 0.38,
                    color: Colors.white.withValues(alpha: 0.9),
                  ),
                ),
        );
      }),
    );
  }

  static String _monogram(String text) {
    final words = text
        .split(RegExp(r'\s+'))
        .where((w) =>
            w.isNotEmpty && RegExp(r'[\p{L}\p{N}]', unicode: true).hasMatch(w))
        .toList();
    if (words.isEmpty) return '';
    String first(String w) {
      final m = RegExp(r'[\p{L}\p{N}]', unicode: true).firstMatch(w);
      return m == null ? '' : m.group(0)!.toUpperCase();
    }

    return words.length == 1
        ? first(words.first)
        : '${first(words[0])}${first(words[1])}';
  }
}
