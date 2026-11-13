import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../data/db/app_database.dart';
import '../../design/tokens.dart';
import '../../domain/album_names.dart';
import 'cover_art.dart';
import 'format.dart';
import 'playability.dart' show kNotDownloadedWords;

/// Bold section title with an optional "Show all" action.
class SectionHeader extends StatelessWidget {
  const SectionHeader({
    super.key,
    required this.title,
    this.onSeeAll,
    this.seeAllLabel = 'Show all',
  });

  final String title;
  final VoidCallback? onSeeAll;
  final String seeAllLabel;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(
          Space.gutter, Space.xl, Space.gutter, Space.md),
      child: Row(
        children: [
          Expanded(
            child: Semantics(
              header: true,
              child: Text(title, style: context.text.headlineSmall),
            ),
          ),
          if (onSeeAll != null)
            TextButton(
              onPressed: onSeeAll,
              child: Text(seeAllLabel,
                  style: context.text.labelLarge
                      ?.copyWith(color: context.colors.onBgMuted)),
            ),
        ],
      ),
    );
  }
}

/// Square (or circular) artwork card with title and subtitle - the unit of
/// every horizontal shelf.
class MediaCard extends StatelessWidget {
  const MediaCard({
    super.key,
    required this.title,
    this.subtitle,
    this.coverArtId,
    this.mosaicIds = const [],
    this.circular = false,
    this.width = 148,
    this.onTap,
    this.onLongPress,
    this.artistName,
  });

  final String title;
  final String? subtitle;
  final String? coverArtId;
  final List<String> mosaicIds;
  final bool circular;
  final double width;
  final VoidCallback? onTap;
  final VoidCallback? onLongPress;

  /// Artist of an album card: lets the catalogue supply a missing cover.
  final String? artistName;

  @override
  Widget build(BuildContext context) {
    final art = CoverArt(
      coverArtId: coverArtId,
      mosaicIds: mosaicIds,
      fallbackLabel: title,
      fallbackArtist: artistName,
      radius: Radii.card,
      circular: circular,
    );
    return Semantics(
      button: true,
      label: subtitle == null ? title : '$title, $subtitle',
      excludeSemantics: true,
      child: InkWell(
        onTap: onTap,
        onLongPress: onLongPress,
        borderRadius: BorderRadius.circular(Radii.card),
        child: SizedBox(
          // `double.infinity` = fill the grid cell (width from the parent,
          // artwork stays square via AspectRatio).
          width: width.isFinite ? width : null,
          child: Column(
            crossAxisAlignment:
                circular ? CrossAxisAlignment.center : CrossAxisAlignment.start,
            children: [
              if (width.isFinite)
                SizedBox.square(dimension: width, child: art)
              else
                AspectRatio(aspectRatio: 1, child: art),
              const SizedBox(height: Space.sm),
              Text(
                title,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                textAlign: circular ? TextAlign.center : TextAlign.start,
                style: context.text.titleSmall,
              ),
              if (subtitle != null)
                Text(
                  subtitle!,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  textAlign: circular ? TextAlign.center : TextAlign.start,
                  style: context.text.bodySmall,
                ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Horizontally scrolling row of cards. Lazy: only visible cards are built.
class MediaShelf extends StatelessWidget {
  const MediaShelf({
    super.key,
    required this.itemCount,
    required this.itemBuilder,
    this.cardWidth = 148,
    this.height,
  });

  final int itemCount;
  final Widget Function(BuildContext context, int index) itemBuilder;
  final double cardWidth;
  final double? height;

  @override
  Widget build(BuildContext context) {
    // Artwork + 2 lines of text; scales with the user's text size.
    final scale = MediaQuery.textScalerOf(context).scale(1);
    final h = height ?? cardWidth + 62 * scale;
    return SizedBox(
      height: h,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: Space.gutter),
        itemCount: itemCount,
        separatorBuilder: (_, __) => const SizedBox(width: Space.md),
        itemBuilder: itemBuilder,
      ),
    );
  }
}

/// The "..." button of a song: it opens the song's menu (`showTrackMenu`). One widget for every place a song is drawn (a row, the Top
/// result of a search), so no song has a different button.
class TrackMoreButton extends StatelessWidget {
  const TrackMoreButton({super.key, required this.onPressed});

  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return IconButton(
      tooltip: 'More options',
      icon: Icon(Icons.more_vert_rounded, color: context.colors.onBgMuted),
      onPressed: onPressed,
    );
  }
}

/// One track row (list of an album, playlist, search results, queue).
class TrackTile extends StatelessWidget {
  const TrackTile({
    super.key,
    required this.track,
    this.number,
    this.showArt = true,
    this.isCurrent = false,
    this.isPlaying = false,
    this.available = true,
    this.downloaded = false,
    this.showAlbum = false,
    this.onTap,
    this.onMore,
  });

  final TrackRow track;

  /// Shown instead of artwork when [showArt] is false (album track lists).
  final int? number;
  final bool showArt;
  final bool isCurrent;
  final bool isPlaying;

  /// `false` when the track cannot be played right now (offline and not
  /// downloaded): dimmed, with an explanation on tap (ADR-008).
  final bool available;
  final bool downloaded;
  final bool showAlbum;
  final VoidCallback? onTap;
  final VoidCallback? onMore;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final titleColor = isCurrent ? c.accent : c.onBg;
    final album = realAlbumName(track.album);
    // A song that cannot be played now says so in words, as drawn (S-17, S-18: "Not downloaded" where the artist stood); it is also greyed, and
    // a tap on it says what to do.
    final subtitle = !available
        ? kNotDownloadedWords
        : [
            if (track.artist != null) track.artist!,
            if (showAlbum && album != null) album,
          ].join(' • ');

    final row = Row(
      children: [
        if (showArt)
          SizedBox.square(
            dimension: 48,
            child: CoverArt(
              coverArtId: track.coverArt,
              fallbackLabel: album ?? track.title,
              fallbackArtist: album == null ? null : track.artist,
            ),
          )
        else
          SizedBox(
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
          ),
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
                  color: titleColor,
                  fontWeight: isCurrent ? FontWeight.w700 : FontWeight.w500,
                ),
              ),
              if (subtitle.isNotEmpty)
                Row(
                  children: [
                    if (downloaded) ...[
                      Icon(Icons.arrow_circle_down_rounded,
                          size: 14, color: c.accent),
                      const SizedBox(width: 4),
                    ],
                    Flexible(
                      child: Text(
                        subtitle,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: context.text.bodyMedium,
                      ),
                    ),
                  ],
                ),
            ],
          ),
        ),
        if (!available)
          Padding(
            padding: const EdgeInsets.only(right: Space.xs),
            child: Icon(Icons.cloud_off_rounded, size: 18, color: c.onBgFaint),
          ),
        if (onMore != null) TrackMoreButton(onPressed: onMore!),
      ],
    );

    return Semantics(
      button: true,
      label: '${track.title}, ${track.artist ?? ''}'
          '${available ? '' : ', not downloaded'}',
      excludeSemantics: true,
      child: Opacity(
        opacity: available ? 1 : 0.45,
        child: InkWell(
          onTap: onTap,
          // A long press opens the same menu as the three dots (D-26).
          onLongPress: onMore,
          child: ConstrainedBox(
            constraints: const BoxConstraints(minHeight: 56),
            child: Padding(
              padding: const EdgeInsets.symmetric(
                horizontal: Space.gutter,
                vertical: Space.xs,
              ),
              child: row,
            ),
          ),
        ),
      ),
    );
  }
}

/// Big circular play/pause button used on detail headers and the player.
class PlayButton extends StatelessWidget {
  const PlayButton({
    super.key,
    required this.isPlaying,
    required this.onPressed,
    this.size = 56,
    this.filled = true,
  });

  final bool isPlaying;
  final VoidCallback? onPressed;
  final double size;
  final bool filled;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final button = Material(
      color: filled ? c.accent : Colors.transparent,
      shape: const CircleBorder(),
      child: InkWell(
        customBorder: const CircleBorder(),
        onTap: onPressed == null
            ? null
            : () {
                HapticFeedback.selectionClick();
                onPressed!();
              },
        child: SizedBox.square(
          dimension: size,
          child: Icon(
            isPlaying ? Icons.pause_rounded : Icons.play_arrow_rounded,
            size: size * 0.6,
            color: filled ? c.onAccent : c.onBg,
          ),
        ),
      ),
    );
    return Semantics(
      button: true,
      enabled: onPressed != null,
      label: isPlaying ? 'Pause' : 'Play',
      excludeSemantics: true,
      // A Play that cannot play (an empty playlist) must not look like the one that can (Q2).
      child: onPressed == null ? Opacity(opacity: 0.38, child: button) : button,
    );
  }
}

/// Friendly empty state: one sentence and (optionally) the one next action.
class EmptyState extends StatelessWidget {
  const EmptyState({
    super.key,
    required this.icon,
    required this.title,
    this.message,
    this.actionLabel,
    this.onAction,
  });

  final IconData icon;
  final String title;
  final String? message;
  final String? actionLabel;
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(Space.xxl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 48, color: context.colors.onBgFaint),
            const SizedBox(height: Space.lg),
            Text(title,
                style: context.text.titleLarge, textAlign: TextAlign.center),
            if (message != null) ...[
              const SizedBox(height: Space.sm),
              Text(message!,
                  style: context.text.bodyMedium, textAlign: TextAlign.center),
            ],
            if (actionLabel != null) ...[
              const SizedBox(height: Space.xl),
              FilledButton(onPressed: onAction, child: Text(actionLabel!)),
            ],
          ],
        ),
      ),
    );
  }
}

/// Pill-shaped filter chip row (Home / Library / Search).
class ChipRow extends StatelessWidget {
  const ChipRow({
    super.key,
    required this.labels,
    required this.selected,
    required this.onSelected,
    this.padding = const EdgeInsets.symmetric(horizontal: Space.gutter),
  });

  final List<String> labels;
  final int? selected;
  final ValueChanged<int?> onSelected;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 40,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: padding,
        itemCount: labels.length,
        separatorBuilder: (_, __) => const SizedBox(width: Space.sm),
        itemBuilder: (context, i) => ChoiceChip(
          label: Text(labels[i]),
          selected: selected == i,
          onSelected: (on) => onSelected(on ? i : null),
          labelStyle: context.text.labelLarge?.copyWith(
            color:
                selected == i ? context.colors.onAccent : context.colors.onBg,
          ),
        ),
      ),
    );
  }
}

String albumSubtitle(AlbumRow a) {
  final parts = [
    if (a.year != null) '${a.year}',
    if (a.artist != null) a.artist!,
  ];
  return parts.join(' • ');
}

String trackCountLabel(int count) => plural(count, 'song');

/// Swipe gestures on a row (docs/06-ux-spec.md 4.4): right = add to queue,
/// left = like. The row never actually dismisses; the gesture just triggers
/// the action with haptic feedback.
class SwipeActions extends StatelessWidget {
  const SwipeActions({
    super.key,
    required this.id,
    required this.child,
    this.onSwipeRight,
    this.onSwipeLeft,
    this.rightLabel = 'Add to queue',
    this.leftLabel = 'Like',
    this.rightIcon = Icons.queue_music_rounded,
    this.leftIcon = Icons.favorite_rounded,
  });

  final String id;
  final Widget child;

  /// Triggered by a left-to-right swipe.
  final VoidCallback? onSwipeRight;

  /// Triggered by a right-to-left swipe.
  final VoidCallback? onSwipeLeft;
  final String rightLabel;
  final String leftLabel;
  final IconData rightIcon;
  final IconData leftIcon;

  @override
  Widget build(BuildContext context) {
    if (onSwipeRight == null && onSwipeLeft == null) return child;
    final c = context.colors;

    Widget background(Alignment alignment, IconData icon, String label) {
      return Container(
        color: c.accent,
        alignment: alignment,
        padding: const EdgeInsets.symmetric(horizontal: Space.xl),
        child: Icon(icon, color: c.onAccent, semanticLabel: label),
      );
    }

    return Dismissible(
      key: ValueKey('swipe-$id'),
      direction: onSwipeRight != null && onSwipeLeft != null
          ? DismissDirection.horizontal
          : onSwipeRight != null
              ? DismissDirection.startToEnd
              : DismissDirection.endToStart,
      dismissThresholds: const {
        DismissDirection.startToEnd: 0.25,
        DismissDirection.endToStart: 0.25,
      },
      background: background(Alignment.centerLeft, rightIcon, rightLabel),
      secondaryBackground:
          background(Alignment.centerRight, leftIcon, leftLabel),
      confirmDismiss: (direction) async {
        unawaited(HapticFeedback.mediumImpact());
        if (direction == DismissDirection.startToEnd) {
          onSwipeRight?.call();
        } else {
          onSwipeLeft?.call();
        }
        return false;
      },
      child: child,
    );
  }
}
