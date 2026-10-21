import 'package:flutter/material.dart';

/// App-wide scrolling: lists stop dead at their ends.
///
/// Android 12+ ships a "stretch" overscroll effect that Flutter's
/// [MaterialScrollBehavior] enables by default. On our detail pages it
/// stretched the hero artwork when the list was pulled past the top, which
/// looked broken (user report, docs/11-feedback-log.md FB-003). Spotify has no
/// overscroll effect at all, so neither do we: no stretch, no glow, no bounce.
class EncoreScrollBehavior extends MaterialScrollBehavior {
  const EncoreScrollBehavior();

  @override
  Widget buildOverscrollIndicator(
    BuildContext context,
    Widget child,
    ScrollableDetails details,
  ) =>
      child;

  @override
  ScrollPhysics getScrollPhysics(BuildContext context) =>
      const ClampingScrollPhysics();
}
