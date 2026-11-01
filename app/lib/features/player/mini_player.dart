import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/navigation.dart';
import '../../design/tokens.dart';
import '../../domain/artwork_color.dart';
import '../common/artwork_color.dart';
import '../common/cover_art.dart';
import '../common/widgets.dart';
import '../providers.dart';

/// Persistent mini-player above the navigation bar (docs/06-ux-spec.md 4.5).
///
/// Tap or swipe up = Now Playing; swipe left/right = skip.
class MiniPlayer extends ConsumerWidget {
  const MiniPlayer({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final snapshot = ref.watch(playbackSnapshotProvider).value;
    final track = snapshot?.track;
    if (track == null) return const SizedBox.shrink();

    final facade = ref.watch(playbackFacadeProvider);
    // The bar is always a dark tint of the cover: its words are the dark theme's, whatever theme the app is in (the light theme gave dark
    // grey on dark olive, QA round 1, R1-6).
    final onBar = EncoreColors.dark();
    final swatch = ref
        .watch(artworkSwatchProvider(
            (albumId: track.albumId, coverArtId: track.coverArt)))
        .value;
    final tint = swatch != null
        ? backdropFor(swatch, maxLightness: 0.24)
        : tintFor(track.album ?? track.title, lightness: 0.24);

    return Padding(
      padding: const EdgeInsets.fromLTRB(8, 0, 8, 6),
      child: Dismissible(
        key: const ValueKey('mini-player'),
        direction: DismissDirection.horizontal,
        confirmDismiss: (direction) async {
          unawaited(HapticFeedback.lightImpact());
          if (direction == DismissDirection.endToStart) {
            await facade.skipNext();
          } else {
            await facade.skipPrevious();
          }
          return false; // never actually dismiss the widget
        },
        child: GestureDetector(
          onVerticalDragEnd: (d) {
            if ((d.primaryVelocity ?? 0) < -300) Nav.nowPlaying(context);
          },
          child: Semantics(
            button: true,
            label: 'Now playing: ${track.title}, ${track.artist ?? ''}. '
                'Open player',
            child: Material(
              color: tint,
              borderRadius: BorderRadius.circular(Radii.card),
              clipBehavior: Clip.antiAlias,
              child: InkWell(
                onTap: () => Nav.nowPlaying(context),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    SizedBox(
                      height: 56,
                      // A compact control with a fixed height: text follows
                      // the system size up to 1.2x and stays readable above.
                      child: MediaQuery.withClampedTextScaling(
                        maxScaleFactor: 1.2,
                        child: Row(
                          children: [
                            const SizedBox(width: Space.sm),
                            SizedBox.square(
                              dimension: 40,
                              child: CoverArt(
                                coverArtId: track.coverArt,
                                imageUrl: track.imageUrl,
                                fallbackArtist:
                                    track.album == null ? null : track.artist,
                                fallbackLabel: track.album ?? track.title,
                              ),
                            ),
                            const SizedBox(width: Space.md),
                            Expanded(
                              child: Column(
                                mainAxisAlignment: MainAxisAlignment.center,
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    track.title,
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                    style: context.text.titleSmall
                                        ?.copyWith(color: onBar.onBg),
                                  ),
                                  if (track.artist != null)
                                    Text(
                                      track.artist!,
                                      maxLines: 1,
                                      overflow: TextOverflow.ellipsis,
                                      style: context.text.bodySmall
                                          ?.copyWith(color: onBar.onBgMuted),
                                    ),
                                ],
                              ),
                            ),
                            if (snapshot!.isLoading)
                              const Padding(
                                padding: EdgeInsets.all(14),
                                child: SizedBox.square(
                                  dimension: 20,
                                  child:
                                      CircularProgressIndicator(strokeWidth: 2),
                                ),
                              )
                            else
                              Theme(
                                data: Theme.of(context)
                                    .copyWith(extensions: [onBar]),
                                child: PlayButton(
                                  isPlaying: snapshot.isPlaying,
                                  size: 48,
                                  filled: false,
                                  onPressed: facade.togglePlayPause,
                                ),
                              ),
                          ],
                        ),
                      ),
                    ),
                    const _MiniProgress(),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// Thin progress line; isolated so only it rebuilds on position ticks.
class _MiniProgress extends ConsumerWidget {
  const _MiniProgress();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final position = ref.watch(playbackPositionProvider).value ?? Duration.zero;
    final snapshot = ref.watch(playbackSnapshotProvider).value;
    final total = snapshot?.duration ?? Duration.zero;
    final fraction = total.inMilliseconds == 0
        ? 0.0
        : (position.inMilliseconds / total.inMilliseconds).clamp(0.0, 1.0);
    return LinearProgressIndicator(
      value: fraction,
      minHeight: 2,
      backgroundColor: Colors.white.withValues(alpha: 0.15),
      valueColor: AlwaysStoppedAnimation(EncoreColors.dark().onBg),
    );
  }
}
