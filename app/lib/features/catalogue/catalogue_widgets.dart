import 'package:flutter/material.dart';

import '../../app/navigation.dart';
import '../../data/catalogue/catalogue_models.dart';
import '../../design/tokens.dart';
import '../common/cover_art.dart';
import '../common/format.dart';
import '../instant/instant_play.dart';
import '../player/playback_facade.dart';
import 'catalogue_providers.dart' show ArtistRelease;

/// Length of every catalogue sample.
const Duration kPreviewLength = Duration(seconds: 30);

/// The playable sample of [t], `null` when the catalogue has none for it.
PreviewTrack? previewOf(CatalogueTrack t) {
  final url = t.previewUrl;
  final uri = url == null ? null : Uri.tryParse(url);
  if (uri == null || !uri.hasScheme) return null;
  return PreviewTrack(
    id: t.id,
    title: t.title,
    uri: uri,
    artist: t.artistName,
    catalogueArtistId: t.artistId,
    album: t.albumTitle,
    imageUrl: t.coverUrl,
    duration: kPreviewLength,
  );
}

/// `1.2M fans`, `850K fans`, `12,345 fans` -> short form.
String formatFans(int fans) {
  if (fans >= 1000000) {
    final v = fans / 1000000;
    return '${v >= 10 ? v.round() : v.toStringAsFixed(1)}M fans';
  }
  if (fans >= 10000) return '${(fans / 1000).round()}K fans';
  return plural(fans, 'fan');
}

/// `Album`, `EP`, `Single`, `Compilation` for Deezer's record types.
String? recordTypeLabel(String? type) => switch (type) {
      'album' => 'Album',
      'ep' => 'EP',
      'single' => 'Single',
      'compile' => 'Compilation',
      _ => null,
    };

/// One release of an artist: opens the library's copy when the person owns
/// it, otherwise the catalogue page where it can be played or fetched.
class ReleaseTile extends StatelessWidget {
  const ReleaseTile({super.key, required this.release});

  final ArtistRelease release;

  @override
  Widget build(BuildContext context) {
    final album = release.album;
    final c = context.colors;
    final subtitle = [
      if (album.year != null) '${album.year}',
      recordTypeLabel(album.recordType) ?? 'Album',
    ].join(' • ');
    return Semantics(
      button: true,
      label: '${album.title}, $subtitle'
          '${release.owned ? ', in your library' : ''}',
      excludeSemantics: true,
      child: InkWell(
        onTap: () => release.owned
            ? Nav.album(context, release.libraryAlbumId!)
            : Nav.catalogueAlbum(context, album),
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: 64),
          child: Padding(
            padding: const EdgeInsets.symmetric(
                horizontal: Space.gutter, vertical: Space.xs),
            child: Row(
              children: [
                SizedBox.square(
                  dimension: 52,
                  child: CoverArt(
                    imageUrl: album.coverUrl,
                    fallbackLabel: album.title,
                    radius: Radii.art,
                  ),
                ),
                const SizedBox(width: Space.md),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(album.title,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: context.text.bodyLarge),
                      Text(subtitle, style: context.text.bodyMedium),
                    ],
                  ),
                ),
                if (release.owned)
                  Icon(Icons.library_music_rounded,
                      size: 20, color: c.accent, semanticLabel: 'In library'),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// One row of a catalogue track list (album page, artist "Popular").
///
/// Without an instant-play service tapping plays the 30 s sample, and a track
/// the catalogue has no sample for is shown dimmed and does nothing, rather
/// than hiding it, so the list matches the real release. With the service
/// ([instant]) every row plays the whole song: the server gets it, adds it to
/// the library, and it starts (ADR-057); [onLongPress] keeps the sample one
/// press away.
class PreviewTrackTile extends StatelessWidget {
  const PreviewTrackTile({
    super.key,
    required this.track,
    required this.isCurrent,
    required this.isPlaying,
    this.number,
    this.showCover = false,
    this.onTap,
    this.instant = false,
    this.status,
    this.onLongPress,
  });

  final CatalogueTrack track;
  final bool isCurrent;
  final bool isPlaying;

  /// Shown instead of the cover on album pages.
  final int? number;
  final bool showCover;
  final VoidCallback? onTap;

  /// Tapping fetches and plays the full song.
  final bool instant;

  /// Progress of that fetch for this row, if one was started.
  final InstantStatus? status;
  final VoidCallback? onLongPress;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final playable = instant || track.previewUrl != null;
    final working = status?.isWorking ?? false;
    final subtitle = working
        ? status!.label
        : (status?.isFailed ?? false)
            ? (status!.message ?? 'Could not get it')
            : [
                track.artistName,
                if (showCover && track.albumTitle != null) track.albumTitle!,
              ].join(' • ');
    final Widget? trailingStatus = working
        ? SizedBox.square(
            dimension: 18,
            child: CircularProgressIndicator(strokeWidth: 2, color: c.accent),
          )
        : (status?.isReady ?? false)
            ? Icon(Icons.check_circle_rounded,
                size: 20, color: c.accent, semanticLabel: 'In your library')
            : (status?.isFailed ?? false)
                ? Icon(Icons.error_outline_rounded,
                    size: 20, color: c.warning, semanticLabel: 'Failed')
                : null;

    final leading = showCover
        ? SizedBox.square(
            dimension: 48,
            child: CoverArt(
              imageUrl: track.coverUrl,
              fallbackLabel: track.albumTitle ?? track.title,
            ),
          )
        : SizedBox(
            width: 32,
            child: isCurrent
                ? Icon(
                    isPlaying
                        ? Icons.graphic_eq_rounded
                        : Icons.volume_mute_rounded,
                    color: c.accent,
                    size: 20,
                  )
                : Text(
                    number?.toString() ?? '',
                    style: context.text.bodyMedium,
                    textAlign: TextAlign.center,
                  ),
          );

    return Semantics(
      button: playable,
      label: '${track.title}, ${track.artistName}, '
          '${instant ? 'play now' : (playable ? '30 second preview' : 'no preview available')}'
          '${working ? ', ${status!.label}' : ''}',
      excludeSemantics: true,
      child: Opacity(
        opacity: playable ? 1 : 0.45,
        child: InkWell(
          onTap: playable && !working ? onTap : null,
          onLongPress: onLongPress,
          child: ConstrainedBox(
            constraints: const BoxConstraints(minHeight: 56),
            child: Padding(
              padding: const EdgeInsets.symmetric(
                  horizontal: Space.gutter, vertical: Space.xs),
              child: Row(
                children: [
                  leading,
                  const SizedBox(width: Space.md),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Text(
                          track.title,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: context.text.bodyLarge?.copyWith(
                            color: isCurrent ? c.accent : c.onBg,
                            fontWeight:
                                isCurrent ? FontWeight.w700 : FontWeight.w500,
                          ),
                        ),
                        Text(
                          subtitle,
                          // Why a song could not be fetched is the one
                          // line a person needs whole (B42).
                          maxLines: (status?.isFailed ?? false) ? 2 : 1,
                          overflow: TextOverflow.ellipsis,
                          style: context.text.bodyMedium,
                        ),
                      ],
                    ),
                  ),
                  if (trailingStatus != null)
                    Padding(
                      padding: const EdgeInsets.only(left: Space.sm),
                      child: trailingStatus,
                    )
                  else if (track.duration != null)
                    Padding(
                      padding: const EdgeInsets.only(left: Space.sm),
                      child: Text(
                        formatClock(track.duration!),
                        style: context.text.bodyMedium,
                      ),
                    ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
