import 'package:flutter/material.dart';

import '../../data/people/people_client.dart';
import '../../design/tokens.dart';
import '../common/cover_art.dart';
import '../common/widgets.dart';

/// The Home slivers for "Friends": one card for each friend who chose to
/// share what they are listening to (docs/35). Empty when nobody does.
List<Widget> friendsShelf(BuildContext context, List<FriendActivity> friends) {
  if (friends.isEmpty) return const [];
  final scale = MediaQuery.textScalerOf(context).scale(1);
  return [
    const SliverToBoxAdapter(child: SectionHeader(title: 'Friends')),
    SliverToBoxAdapter(
      child: MediaShelf(
        itemCount: friends.length,
        cardWidth: 260,
        height: 76 + 30 * (scale - 1).clamp(0, 1),
        itemBuilder: (context, i) => _FriendCard(friend: friends[i]),
      ),
    ),
  ];
}

class _FriendCard extends StatelessWidget {
  const _FriendCard({required this.friend});

  final FriendActivity friend;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final status = friend.isPlaying ? 'Listening now' : 'Paused';
    final what = [
      friend.title,
      if (friend.artist.isNotEmpty) friend.artist,
    ].join(' • ');
    return Semantics(
      container: true,
      label: '${friend.user}, '
          '${friend.isPlaying ? 'listening to' : 'paused on'} ${friend.title}'
          '${friend.artist.isEmpty ? '' : ' by ${friend.artist}'}',
      excludeSemantics: true,
      child: SizedBox(
        width: 260,
        child: DecoratedBox(
          decoration: BoxDecoration(
            color: c.surface,
            borderRadius: BorderRadius.circular(Radii.card),
          ),
          child: Padding(
            padding: const EdgeInsets.all(Space.sm),
            child: Row(
              children: [
                SizedBox.square(
                  dimension: 60,
                  child: CoverArt(
                    imageUrl: friend.coverUrl,
                    // Without a picture the card shows who it is, not the
                    // song's letter (which looks like the person's own).
                    fallbackLabel: friend.user,
                  ),
                ),
                const SizedBox(width: Space.md),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Text(
                        friend.user,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: context.text.bodyLarge
                            ?.copyWith(fontWeight: FontWeight.w700),
                      ),
                      Text(
                        what,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: context.text.bodyMedium,
                      ),
                      Row(
                        children: [
                          Icon(
                            friend.isPlaying
                                ? Icons.graphic_eq_rounded
                                : Icons.pause_rounded,
                            size: 14,
                            color: friend.isPlaying ? c.accent : c.onBgMuted,
                          ),
                          const SizedBox(width: 4),
                          Text(
                            status,
                            style: context.text.bodySmall?.copyWith(
                              color: friend.isPlaying ? c.accent : c.onBgMuted,
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
