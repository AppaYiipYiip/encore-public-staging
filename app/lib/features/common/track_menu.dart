import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/navigation.dart';
import '../../app/providers.dart';
import '../../data/db/app_database.dart';
import '../../design/tokens.dart';
import '../providers.dart';
import 'cover_art.dart';
import 'encore_sheet.dart';
import 'format.dart';
import 'playlist_actions.dart';

/// Opens the action sheet for one track (docs/06-ux-spec.md section 0: an
/// action on one item lives in its three-dot sheet, never its own screen).
///
/// [fromPlaylist] adds "Remove from this playlist" when the menu was opened
/// on an entry of a playlist the user can edit.
Future<void> showTrackMenu(
  BuildContext context,
  TrackRow track, {
  ({String playlistId, String playlistName, int position})? fromPlaylist,
}) {
  return showEncoreSheet<void>(
    context: context,
    builder: (sheetContext) => _TrackMenu(
      track: track,
      parent: context,
      fromPlaylist: fromPlaylist,
    ),
  );
}

class _TrackMenu extends ConsumerWidget {
  const _TrackMenu({
    required this.track,
    required this.parent,
    this.fromPlaylist,
  });

  final TrackRow track;
  final ({String playlistId, String playlistName, int position})? fromPlaylist;

  /// Context of the screen that opened the sheet (used for navigation, since
  /// the sheet's own context disappears when it closes).
  final BuildContext parent;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final live = ref.watch(trackProvider(track.id)).value ?? track;
    final liked = live.starredAtMs != null;
    final session = ref.watch(sessionProvider).value;
    final facade = ref.watch(playbackFacadeProvider);
    final c = context.colors;
    final quality = qualityLabel(suffix: track.suffix, bitRate: track.bitRate);

    void close() => Navigator.of(context).pop();

    void toast(String message) {
      ScaffoldMessenger.of(parent)
        ..hideCurrentSnackBar()
        ..showSnackBar(SnackBar(content: Text(message)));
    }

    return SafeArea(
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(
                  Space.gutter, Space.sm, Space.gutter, Space.md),
              child: Row(
                children: [
                  SizedBox.square(
                    dimension: 56,
                    child: CoverArt(
                      coverArtId: track.coverArt,
                      fallbackLabel: track.album ?? track.title,
                      fallbackArtist: track.album == null ? null : track.artist,
                    ),
                  ),
                  const SizedBox(width: Space.md),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(track.title,
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                            style: context.text.titleMedium),
                        Text(
                          [
                            if (track.artist != null) track.artist!,
                            if (quality.isNotEmpty) quality,
                          ].join(' • '),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: context.text.bodyMedium,
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            Divider(color: c.outline),
            _Action(
              icon: liked
                  ? Icons.favorite_rounded
                  : Icons.favorite_border_rounded,
              iconColor: liked ? c.accent : null,
              label: liked ? 'Remove from Liked Songs' : 'Add to Liked Songs',
              enabled: session != null,
              onTap: () {
                HapticFeedback.mediumImpact();
                session!.mutations.setTrackStarred(track.id, !liked);
                close();
                toast(liked
                    ? 'Removed from Liked Songs'
                    : 'Added to Liked Songs');
              },
            ),
            _Action(
              icon: Icons.playlist_add_rounded,
              label: 'Add to playlist',
              onTap: () {
                close();
                unawaited(showAddToPlaylistSheet(
                  parent,
                  trackIds: [track.id],
                ));
              },
            ),
            if (fromPlaylist != null)
              _Action(
                icon: Icons.remove_circle_outline_rounded,
                label: 'Remove from this playlist',
                enabled: session != null,
                onTap: () async {
                  final from = fromPlaylist!;
                  close();
                  final ok = await session!.playlists
                      .removeAt(from.playlistId, from.position);
                  toast(ok
                      ? 'Removed from "${from.playlistName}"'
                      : 'Could not remove it');
                },
              ),
            _Action(
              icon: Icons.playlist_play_rounded,
              label: 'Play next',
              onTap: () {
                facade.playNext(track);
                close();
                toast('Will play next');
              },
            ),
            _Action(
              icon: Icons.queue_music_rounded,
              label: 'Add to queue',
              onTap: () {
                facade.addToQueue(track);
                close();
                toast('Added to queue');
              },
            ),
            if (track.albumId != null)
              _Action(
                icon: Icons.album_outlined,
                label: 'Go to album',
                onTap: () {
                  close();
                  Nav.album(parent, track.albumId!);
                },
              ),
            if (track.artistId != null)
              _Action(
                icon: Icons.person_outline_rounded,
                label: 'Go to artist',
                onTap: () {
                  close();
                  Nav.artist(parent, track.artistId!);
                },
              ),
            const SizedBox(height: Space.md),
          ],
        ),
      ),
    );
  }
}

class _Action extends StatelessWidget {
  const _Action({
    required this.icon,
    required this.label,
    required this.onTap,
    this.iconColor,
    this.enabled = true,
  });

  final IconData icon;
  final String label;
  final VoidCallback onTap;
  final Color? iconColor;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      enabled: enabled,
      leading: Icon(icon, color: iconColor),
      title: Text(label, style: context.text.bodyLarge),
      onTap: enabled ? onTap : null,
    );
  }
}
