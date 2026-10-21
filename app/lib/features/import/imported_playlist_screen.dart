import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/navigation.dart';
import '../../data/catalogue/catalogue_models.dart';
import '../../data/fetch/import_models.dart';
import '../../design/tokens.dart';
import '../catalogue/catalogue_widgets.dart';
import '../common/cover_art.dart';
import '../common/format.dart';
import '../common/widgets.dart';
import '../detail/hero_header.dart';
import '../instant/instant_controller.dart';
import '../instant/instant_play.dart';
import '../providers.dart';
import 'import_providers.dart';

/// An imported playlist as it is right now: **every song at once**, each one
/// playable at once (ADR-102).
///
/// Importing puts a copy of each song on the person's own server. That takes
/// minutes for a long playlist, and nobody should have to wait for it: this page
/// lists the whole playlist the moment the import starts, a song already in the
/// library plays instantly, and a song that is not yet is fetched when it is
/// tapped (the same "play any song" path as a search result, a few seconds)
/// while the import carries on behind it. It is the catalogue album page with
/// the playlist's songs in place of the catalogue's.
class ImportedPlaylistScreen extends ConsumerWidget {
  const ImportedPlaylistScreen({super.key, required this.importId});

  final String importId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(importSongsProvider(importId));
    final job = async.value;
    if (job == null) {
      return Scaffold(
        appBar: AppBar(),
        body: Center(
          child: async.hasError
              ? Padding(
                  padding: const EdgeInsets.all(Space.xl),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        'The playlist could not be loaded.',
                        style: context.text.titleMedium,
                      ),
                      const SizedBox(height: Space.md),
                      FilledButton(
                        onPressed: () =>
                            ref.invalidate(importSongsProvider(importId)),
                        child: const Text('Try again'),
                      ),
                    ],
                  ),
                )
              : const CircularProgressIndicator(),
        ),
      );
    }

    final facade = ref.watch(playbackFacadeProvider);
    final snapshot = ref.watch(playbackSnapshotProvider).value;
    final sourceId = 'import:${job.id}';
    final isCurrent = snapshot?.sourceId == sourceId;
    final isPlaying = isCurrent && (snapshot?.isPlaying ?? false);

    // The songs that can be played, in the playlist's order; the ones that
    // cannot be had stay in the list (dimmed, with why) but are not played.
    final songs = job.songs;
    final tracks = <int, CatalogueTrack>{
      for (var i = 0; i < songs.length; i++)
        if (songs[i].state != ImportSongState.missing)
          i: CatalogueTrack(
            id: 'import:${job.id}:$i',
            title: songs[i].title,
            artistName: songs[i].artist,
            albumTitle: songs[i].album,
            duration: songs[i].durationSec == null
                ? null
                : Duration(seconds: songs[i].durationSec!),
            videoId: songs[i].videoId,
            officialVideo: songs[i].official,
          ),
    };
    final playable = tracks.values.toList();
    final name = job.isLiked ? 'Your liked songs' : job.name;

    void playFrom(int songIndex) {
      final at = playable.indexOf(tracks[songIndex]!);
      unawaited(ref.read(instantControllerProvider.notifier).playRun(playable,
          startIndex: at < 0 ? 0 : at, sourceName: name, sourceId: sourceId));
    }

    final inLibrary =
        songs.where((s) => s.state == ImportSongState.ready).length;
    final stillComing = songs
        .where((s) =>
            s.state == ImportSongState.waiting ||
            s.state == ImportSongState.working)
        .length;
    final leftOut = songs.where((s) => s.reason == 'skipped').length;
    final missing = songs
        .where(
            (s) => s.state == ImportSongState.missing && s.reason != 'skipped')
        .length;
    final summary = [
      plural(songs.length, 'song'),
      if (stillComing > 0)
        '$inLibrary in your library, fetching the other $stillComing'
      else if (missing == 0)
        'all in your library'
      else
        '${plural(missing, 'song')} could not be found',
      if (leftOut > 0) '$leftOut left out',
    ].join(' - ');

    return CollectionScaffold(
      title: name,
      art: CoverArt(
        imageUrl: null,
        fallbackLabel: name,
        radius: Radii.hero,
      ),
      subtitleLines: [
        Text(summary,
            key: const Key('imported-summary'), style: context.text.bodyMedium),
        if (job.isRunning && job.etaText != null)
          Text(job.etaText!, style: context.text.bodyMedium),
        if (job.pausedMessage != null)
          Text(job.pausedMessage!, style: context.text.bodyMedium),
      ],
      actions: Row(
        children: [
          // The library's own playlist exists from the first song and is where a song is taken off.
          if (job.playlistId != null && !job.isLiked)
            OutlinedButton(
              onPressed: () => Nav.playlist(context, job.playlistId!),
              child: const Text('Open in library'),
            ),
          const Spacer(),
          PlayButton(
            isPlaying: isPlaying,
            size: 56,
            onPressed: playable.isEmpty
                ? null
                : () => isCurrent
                    ? facade.togglePlayPause()
                    : playFrom(tracks.keys.first),
          ),
        ],
      ),
      slivers: [
        SliverToBoxAdapter(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(
                Space.gutter, Space.md, Space.gutter, Space.sm),
            child: Text(
              job.isRunning
                  ? 'Tap any song to play it. One that is not in your library '
                      'yet is fetched as you tap, a few seconds; the rest keep '
                      'arriving in the background.'
                  : 'Tap any song to play it.',
              style: context.text.bodyMedium
                  ?.copyWith(color: context.colors.onBgMuted),
            ),
          ),
        ),
        SliverList.builder(
          itemCount: songs.length,
          itemBuilder: (context, i) {
            final song = songs[i];
            final track = tracks[i];
            if (track == null) {
              // Not to be had: said in one line, not hidden.
              return PreviewTrackTile(
                key: Key('imported-song-$i'),
                track: CatalogueTrack(
                  id: 'import:${job.id}:$i',
                  title: song.title,
                  artistName: song.artist,
                ),
                number: i + 1,
                isCurrent: false,
                isPlaying: false,
                instant: true,
                status: InstantStatus.failed(
                    song.message ?? 'This song could not be found.'),
              );
            }
            final status = ref.watch(instantStatusProvider(track.id));
            final playingId = snapshot?.track?.id;
            final current = playingId == track.id ||
                (status?.track != null && playingId == status!.track!.id);
            return PreviewTrackTile(
              key: Key('imported-song-$i'),
              track: track,
              number: i + 1,
              isCurrent: current,
              isPlaying: current && (snapshot?.isPlaying ?? false),
              instant: true,
              status: status,
              onTap: () => playFrom(i),
              onLongPress: () => unawaited(_songMenu(context, ref, job, i)),
            );
          },
        ),
      ],
    );
  }

  /// A song of the list, held down: leave it out before it is fetched, or how to take it off the playlist
  /// (a song already in the library is edited in the library's own playlist).
  Future<void> _songMenu(
      BuildContext context, WidgetRef ref, ImportJob job, int index) async {
    final song = job.songs[index];
    final messenger = ScaffoldMessenger.of(context);
    await showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      // Above the mini-player and the tab bar: the last row sat under them and was hidden (2026-10-18).
      useRootNavigator: true,
      // The default sheet is at most a little over half the screen high and clipped its last row (2026-10-18).
      isScrollControlled: true,
      builder: (sheet) => SafeArea(
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              ListTile(
                title: Text(song.title,
                    maxLines: 1, overflow: TextOverflow.ellipsis),
                subtitle: Text(song.artist),
              ),
              if (song.state == ImportSongState.waiting)
                ListTile(
                  key: const Key('imported-skip'),
                  leading: const Icon(Icons.block_rounded),
                  title: const Text("Don't import this song"),
                  subtitle: const Text(
                      'It will not be fetched and will not be in the playlist.'),
                  onTap: () async {
                    Navigator.of(sheet).pop();
                    final ok = await ref
                        .read(importsProvider.notifier)
                        .skip(job.id, [index]);
                    ref.invalidate(importSongsProvider(job.id));
                    messenger.showSnackBar(SnackBar(
                      content: Text(ok
                          ? 'Left out: ${song.title}'
                          : 'Could not leave it out. Try again.'),
                    ));
                  },
                )
              else if (song.state == ImportSongState.working)
                const ListTile(
                  leading: Icon(Icons.downloading_rounded),
                  title: Text('Being fetched right now'),
                  subtitle: Text(
                      'When it has arrived, take it off the playlist in your library.'),
                )
              else ...[
                const ListTile(
                  leading: Icon(Icons.playlist_remove_rounded),
                  title: Text('To take it off the playlist'),
                  subtitle: Text('Open the playlist in your library, tap the '
                      'three dots on the song, then "Remove from this playlist".'),
                ),
                if (job.playlistId != null && !job.isLiked)
                  ListTile(
                    leading: const Icon(Icons.library_music_rounded),
                    title: const Text('Open the playlist in your library'),
                    onTap: () {
                      Navigator.of(sheet).pop();
                      Nav.playlist(context, job.playlistId!);
                    },
                  ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
