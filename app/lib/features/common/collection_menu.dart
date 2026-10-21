import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/navigation.dart';
import '../../data/db/app_database.dart';
import '../../design/tokens.dart';
import '../providers.dart';
import 'format.dart';
import 'playlist_actions.dart';

/// "More" sheet of an album / playlist / liked-songs page: actions that apply
/// to the whole collection (docs/06-ux-spec.md section 0).
///
/// [playlist] (only for a playlist the user can edit) adds rename and delete.
Future<void> showCollectionMenu(
  BuildContext context, {
  required String title,
  required List<TrackRow> tracks,
  String? artistId,
  PlaylistRow? playlist,
  bool leaveAfterDelete = false,
}) {
  return showModalBottomSheet<void>(
    context: context,
    builder: (sheet) => _CollectionMenu(
      title: title,
      tracks: tracks,
      artistId: artistId,
      playlist: playlist,
      leaveAfterDelete: leaveAfterDelete,
      parent: context,
    ),
  );
}

class _CollectionMenu extends ConsumerWidget {
  const _CollectionMenu({
    required this.title,
    required this.tracks,
    required this.artistId,
    required this.parent,
    this.playlist,
    this.leaveAfterDelete = false,
  });

  final String title;
  final List<TrackRow> tracks;
  final String? artistId;
  final BuildContext parent;
  final PlaylistRow? playlist;
  final bool leaveAfterDelete;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final facade = ref.watch(playbackFacadeProvider);

    void done(String message) {
      Navigator.of(context).pop();
      ScaffoldMessenger.of(parent)
        ..hideCurrentSnackBar()
        ..showSnackBar(SnackBar(content: Text(message)));
    }

    Future<void> queueAll({required bool next}) async {
      unawaited(HapticFeedback.selectionClick());
      // "Play next" inserts in reverse so the order is preserved.
      final ordered = next ? tracks.reversed.toList() : tracks;
      for (final t in ordered) {
        if (next) {
          await facade.playNext(t);
        } else {
          await facade.addToQueue(t);
        }
      }
      done(next
          ? '${plural(tracks.length, 'song')} will play next'
          : 'Added ${plural(tracks.length, 'song')} to queue');
    }

    return SafeArea(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(
                Space.gutter, Space.lg, Space.gutter, Space.sm),
            child: Text(title,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: context.text.titleLarge),
          ),
          if (tracks.isNotEmpty) ...[
            ListTile(
              leading: const Icon(Icons.playlist_play_rounded),
              title: const Text('Play next'),
              onTap: () => queueAll(next: true),
            ),
            ListTile(
              leading: const Icon(Icons.queue_music_rounded),
              title: const Text('Add to queue'),
              onTap: () => queueAll(next: false),
            ),
          ],
          if (tracks.isNotEmpty)
            ListTile(
              leading: const Icon(Icons.playlist_add_rounded),
              title: const Text('Add to playlist'),
              onTap: () {
                Navigator.of(context).pop();
                unawaited(showAddToPlaylistSheet(
                  parent,
                  trackIds: [for (final t in tracks) t.id],
                  suggestedName: title,
                ));
              },
            ),
          if (playlist != null)
            ListTile(
              leading: const Icon(Icons.edit_outlined),
              title: const Text('Rename playlist'),
              onTap: () {
                Navigator.of(context).pop();
                unawaited(renamePlaylistFlow(parent, playlist!));
              },
            ),
          if (playlist != null)
            ListTile(
              leading: const Icon(Icons.delete_outline_rounded),
              title: const Text('Delete playlist'),
              onTap: () async {
                Navigator.of(context).pop();
                final deleted = await confirmDeletePlaylist(parent, playlist!);
                if (deleted && leaveAfterDelete && parent.mounted) {
                  Navigator.of(parent).maybePop();
                }
              },
            ),
          if (artistId != null)
            ListTile(
              leading: const Icon(Icons.person_outline_rounded),
              title: const Text('Go to artist'),
              onTap: () {
                Navigator.of(context).pop();
                Nav.artist(parent, artistId!);
              },
            ),
          const SizedBox(height: Space.md),
        ],
      ),
    );
  }
}
