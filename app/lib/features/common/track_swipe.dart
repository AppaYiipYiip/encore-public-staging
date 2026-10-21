import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../data/db/app_database.dart';
import '../providers.dart';
import 'widgets.dart';

/// Wires [SwipeActions] to a track: swipe right = add to queue, swipe left =
/// like / unlike (local-first, queued for the server).
class TrackSwipe extends ConsumerWidget {
  const TrackSwipe({
    super.key,
    required this.track,
    required this.index,
    required this.child,
  });

  final TrackRow track;

  /// Position in the list, so keys stay unique if a track appears twice.
  final int index;
  final Widget child;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final facade = ref.watch(playbackFacadeProvider);
    final session = ref.watch(sessionProvider).value;
    final liked = track.starredAtMs != null;

    void toast(String message) {
      ScaffoldMessenger.of(context)
        ..hideCurrentSnackBar()
        ..showSnackBar(SnackBar(content: Text(message)));
    }

    return SwipeActions(
      id: '${track.id}-$index',
      rightLabel: 'Add to queue',
      leftLabel: liked ? 'Unlike' : 'Like',
      leftIcon: liked ? Icons.heart_broken_rounded : Icons.favorite_rounded,
      onSwipeRight: () {
        facade.addToQueue(track);
        toast('Added to queue');
      },
      onSwipeLeft: session == null
          ? null
          : () {
              session.mutations.setTrackStarred(track.id, !liked);
              toast(
                  liked ? 'Removed from Liked Songs' : 'Added to Liked Songs');
            },
      child: child,
    );
  }
}
