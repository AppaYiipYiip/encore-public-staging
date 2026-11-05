import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/navigation.dart';
import '../../app/providers.dart';
import '../../data/db/app_database.dart';
import '../../data/repos/downloads_repository.dart';
import '../../design/tokens.dart';
import '../../domain/album_names.dart';
import '../downloads/download_notifications_prompt.dart';
import '../downloads/download_providers.dart';
import '../instant/release_save.dart';
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
  List<MenuAction> extraActions = const [],
}) {
  return showEncoreSheet<void>(
    context: context,
    builder: (sheetContext) => _TrackMenu(
      track: track,
      parent: context,
      fromPlaylist: fromPlaylist,
      extraActions: extraActions,
    ),
  );
}

/// One more line at the end of a track's menu (the player puts the speed, the sleep timer and private listening here, as Spotify's "..." menu does).
class MenuAction {
  const MenuAction(this.icon, this.label, this.onTap);

  final IconData icon;
  final String label;
  final VoidCallback onTap;
}

/// A menu with only [actions]: for a song that has no library row to act on (a sample, a song still being added). [note] is a line of plain
/// words above them (why the library lines are missing).
Future<void> showActionsMenu(
  BuildContext context,
  List<MenuAction> actions, {
  String? note,
}) {
  return showEncoreSheet<void>(
    context: context,
    builder: (sheetContext) => SafeArea(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (note != null)
            Padding(
              padding: const EdgeInsets.fromLTRB(
                  Space.xl, Space.sm, Space.xl, Space.md),
              child: Text(note,
                  style: sheetContext.text.bodyMedium
                      ?.copyWith(color: sheetContext.colors.onBgMuted)),
            ),
          for (final a in actions)
            _Action(
              icon: a.icon,
              label: a.label,
              onTap: () {
                Navigator.of(sheetContext).pop();
                a.onTap();
              },
            ),
          const SizedBox(height: Space.md),
        ],
      ),
    ),
  );
}

class _TrackMenu extends ConsumerWidget {
  const _TrackMenu({
    required this.track,
    required this.parent,
    this.fromPlaylist,
    this.extraActions = const [],
  });

  final TrackRow track;
  final List<MenuAction> extraActions;
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
    // Three states of "is this song on the phone" (D-32): chosen by the person for this song alone, there only because of a downloaded
    // playlist or album (cannot be removed from here: that one still wants it), or not there.
    final ownDownload = ref
            .watch(pinStateProvider((PinTargetType.track, track.id)))
            .value
            ?.pinned ??
        false;
    final onPhone =
        ref.watch(downloadedIdsProvider).value?.contains(track.id) ?? false;

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
                      fallbackLabel: realAlbumName(track.album) ?? track.title,
                      fallbackArtist: realAlbumName(track.album) == null
                          ? null
                          : track.artist,
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
            if (ownDownload)
              _Action(
                icon: Icons.arrow_circle_down_rounded,
                iconColor: c.accent,
                label: 'Remove download',
                onTap: () async {
                  final repo = ref.read(downloadsRepositoryProvider);
                  final remove = ref.read(releaseSavesProvider.notifier);
                  close();
                  await remove.removeSongDownload(track.id);
                  // Another pin (a downloaded playlist or album) may still want it: then it did not leave the phone.
                  final stays = onPhone &&
                      repo != null &&
                      (await repo.desired()).containsKey(track.id);
                  toast(stays
                      ? '"${track.title}" stays on this phone: it is part of a downloaded playlist or album.'
                      : 'Removed "${track.title}" from this phone');
                },
              )
            else if (onPhone)
              const _Action(
                icon: Icons.arrow_circle_down_rounded,
                label: 'Downloaded',
                subtitle: 'It is on this phone with its playlist or album.',
                enabled: false,
                onTap: _noop,
              )
            else
              _Action(
                icon: Icons.arrow_circle_down_outlined,
                label: 'Download',
                onTap: () {
                  unawaited(ref
                      .read(downloadActionsProvider)
                      .pin(PinTargetType.track, track.id));
                  // Before the menu closes: the question takes the root navigator now, because the menu's own context is gone a moment later.
                  unawaited(askAboutDownloadNotifications(context, ref));
                  close();
                  toast('Downloading "${track.title}" for offline listening');
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
            for (final a in extraActions)
              _Action(
                icon: a.icon,
                label: a.label,
                onTap: () {
                  close();
                  a.onTap();
                },
              ),
            const SizedBox(height: Space.md),
          ],
        ),
      ),
    );
  }
}

void _noop() {}

class _Action extends StatelessWidget {
  const _Action({
    required this.icon,
    required this.label,
    required this.onTap,
    this.iconColor,
    this.enabled = true,
    this.subtitle,
  });

  final IconData icon;
  final String label;
  final VoidCallback onTap;
  final Color? iconColor;
  final bool enabled;
  final String? subtitle;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      enabled: enabled,
      leading: Icon(icon, color: iconColor),
      title: Text(label, style: context.text.bodyLarge),
      subtitle: subtitle == null ? null : Text(subtitle!),
      onTap: enabled ? onTap : null,
    );
  }
}
