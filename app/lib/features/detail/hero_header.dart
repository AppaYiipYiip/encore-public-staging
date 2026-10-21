import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../design/tokens.dart';

/// Page scaffold for album / playlist / artist / liked songs.
///
/// Layout (docs/06-ux-spec.md 4.2):
/// * a pinned hero header: gradient, artwork that shrinks and fades as the
///   list scrolls, back button, and a title that fades in once the big title
///   has scrolled away;
/// * the title / metadata / action row, which scrolls with the content;
/// * then the page's own slivers.
///
/// There is deliberately no overscroll effect (see `EncoreScrollBehavior`):
/// the artwork can never be stretched.
class CollectionScaffold extends StatelessWidget {
  const CollectionScaffold({
    super.key,
    required this.title,
    required this.art,
    required this.subtitleLines,
    required this.actions,
    required this.slivers,
    this.tint,
    this.circularArt = false,
    this.bottomPadding = Space.xxl,
  });

  final String title;
  final Widget art;
  final List<Widget> subtitleLines;
  final Widget actions;
  final List<Widget> slivers;

  /// Header colour (usually the artwork's dominant colour).
  final Color? tint;

  /// Artists get round artwork (and a round shadow).
  final bool circularArt;
  final double bottomPadding;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final media = MediaQuery.of(context);
    final cover = math.min(media.size.width * 0.62, 260.0);
    final top = tint ?? c.surfaceHigh;
    final mid = Color.lerp(top, c.bg, 0.55)!;

    return Scaffold(
      body: CustomScrollView(
        slivers: [
          SliverPersistentHeader(
            pinned: true,
            delegate: HeroHeaderDelegate(
              topInset: media.padding.top,
              coverSize: cover,
              top: top,
              bottom: mid,
              title: title,
              art: art,
              circularArt: circularArt,
              foreground: c.onBg,
            ),
          ),
          SliverToBoxAdapter(
            child: DecoratedBox(
              decoration: BoxDecoration(
                gradient: LinearGradient(
                  begin: Alignment.topCenter,
                  end: Alignment.bottomCenter,
                  colors: [mid, c.bg],
                ),
              ),
              child: Padding(
                padding: const EdgeInsets.fromLTRB(
                    Space.gutter, Space.md, Space.gutter, Space.md),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(title, style: context.text.headlineMedium),
                    const SizedBox(height: Space.xs),
                    ...subtitleLines,
                    const SizedBox(height: Space.md),
                    actions,
                  ],
                ),
              ),
            ),
          ),
          ...slivers,
          SliverToBoxAdapter(child: SizedBox(height: bottomPadding)),
        ],
      ),
    );
  }
}

/// Pinned, collapsing header. Pure function of the scroll offset, so it
/// repaints cheaply (no animation controllers, no layout of the list).
class HeroHeaderDelegate extends SliverPersistentHeaderDelegate {
  HeroHeaderDelegate({
    required this.topInset,
    required this.coverSize,
    required this.top,
    required this.bottom,
    required this.title,
    required this.art,
    required this.foreground,
    this.circularArt = false,
  });

  final double topInset;
  final double coverSize;
  final Color top;
  final Color bottom;
  final String title;
  final Widget art;
  final Color foreground;
  final bool circularArt;

  @override
  double get minExtent => topInset + kToolbarHeight;

  @override
  double get maxExtent => topInset + kToolbarHeight + coverSize + Space.md;

  @override
  Widget build(
      BuildContext context, double shrinkOffset, bool overlapsContent) {
    final range = maxExtent - minExtent;
    final t = range <= 0 ? 1.0 : (shrinkOffset / range).clamp(0.0, 1.0);
    final scale = 1 - 0.28 * t;
    final artOpacity = (1 - t * 1.5).clamp(0.0, 1.0);
    final titleOpacity = ((t - 0.8) / 0.2).clamp(0.0, 1.0);

    return Stack(
      fit: StackFit.expand,
      children: [
        DecoratedBox(
          decoration: BoxDecoration(
            gradient: LinearGradient(
              begin: Alignment.topCenter,
              end: Alignment.bottomCenter,
              colors: [top, bottom],
            ),
          ),
        ),
        // Solid bar once collapsed so list rows never show through it.
        Positioned(
          left: 0,
          right: 0,
          top: 0,
          height: minExtent,
          child: ColoredBox(color: top.withValues(alpha: t)),
        ),
        Positioned(
          left: 0,
          right: 0,
          top: topInset + kToolbarHeight,
          height: coverSize,
          child: IgnorePointer(
            child: Opacity(
              opacity: artOpacity,
              child: Transform.scale(
                scale: scale,
                alignment: Alignment.topCenter,
                child: Center(
                  child: DecoratedBox(
                    decoration: BoxDecoration(
                      shape: circularArt ? BoxShape.circle : BoxShape.rectangle,
                      borderRadius: circularArt
                          ? null
                          : BorderRadius.circular(Radii.hero),
                      boxShadow: [
                        BoxShadow(
                          color: Colors.black.withValues(alpha: 0.35),
                          blurRadius: 24,
                          offset: const Offset(0, 8),
                        ),
                      ],
                    ),
                    child: SizedBox.square(dimension: coverSize, child: art),
                  ),
                ),
              ),
            ),
          ),
        ),
        Positioned(
          left: 0,
          right: 0,
          top: topInset,
          height: kToolbarHeight,
          child: Row(
            children: [
              BackButton(color: foreground),
              Expanded(
                child: Opacity(
                  opacity: titleOpacity,
                  child: Text(
                    title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context)
                        .textTheme
                        .titleMedium
                        ?.copyWith(color: foreground),
                  ),
                ),
              ),
              const SizedBox(width: Space.gutter),
            ],
          ),
        ),
      ],
    );
  }

  @override
  bool shouldRebuild(HeroHeaderDelegate old) =>
      old.topInset != topInset ||
      old.coverSize != coverSize ||
      old.top != top ||
      old.bottom != bottom ||
      old.title != title ||
      old.art != art ||
      old.circularArt != circularArt ||
      old.foreground != foreground;
}
