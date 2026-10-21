import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/navigation.dart';
import '../../data/catalogue/catalogue_models.dart';
import '../../design/tokens.dart';
import '../catalogue/catalogue_widgets.dart' show formatFans;
import '../common/cover_art.dart';
import '../common/format.dart';
import '../common/widgets.dart';
import '../instant/instant_controller.dart';
import '../providers.dart';
import '../requests/request_providers.dart';
import '../requests/request_ui.dart';

/// "Beyond your library": catalogue matches that can be played or requested
/// (docs/07-request-pipeline.md section 2). Never a dead end: when the
/// library has nothing, this is what the user sees instead of "No results".
///
/// Artists the library has are shown too, marked, with how well known they
/// are: that row leads to the page that lists what is missing (ADR-058).
class CatalogueSection extends ConsumerWidget {
  const CatalogueSection({
    super.key,
    required this.query,
    required this.localIsEmpty,
  });

  final String query;
  final bool localIsEmpty;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final results = ref.watch(catalogueSearchProvider(query));
    // The person is reading the results: have the service look the top song up
    // now (search and streams are 4.6 s of a first play), so the tap that
    // probably follows starts at the download. One song per search, once.
    ref.listen(catalogueSearchProvider(query), (_, next) {
      final tracks = next.value?.tracks;
      if (tracks == null || tracks.isEmpty) return;
      if (!ref.read(instantAvailableProvider)) return;
      unawaited(
          ref.read(instantControllerProvider.notifier).prepare(tracks.first));
    });
    return results.when(
      loading: () => localIsEmpty
          ? const Padding(
              padding: EdgeInsets.all(Space.xl),
              child: Center(child: CircularProgressIndicator()),
            )
          : const SizedBox.shrink(),
      error: (_, __) => const SizedBox.shrink(),
      data: (r) {
        if (r.isEmpty) {
          return localIsEmpty
              ? EmptyState(
                  icon: Icons.search_off_rounded,
                  title: 'No results for "$query"',
                  message: 'Check the spelling, or try fewer words.',
                )
              : const SizedBox.shrink();
        }
        final instant = ref.watch(instantAvailableProvider);
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const SectionHeader(title: 'Not in your library yet'),
            Padding(
              padding: const EdgeInsets.fromLTRB(
                  Space.gutter, 0, Space.gutter, Space.sm),
              child: Text(
                instant
                    ? 'Tap a song to play it. It is added to your library '
                        'first, which takes a few seconds.'
                    : 'Tap a song for a 30-second preview. Request what you '
                        'want and it is added to your library.',
                style: context.text.bodyMedium,
              ),
            ),
            for (final a in _namesakesLast(r.artists).take(3))
              _ArtistRow(artist: a, libraryArtistId: r.ownedArtists[a.id]),
            for (final a in r.albums.take(5)) _AlbumRow(album: a),
            for (final t in r.tracks.take(6)) _TrackRow(track: t),
          ],
        );
      },
    );
  }
}

/// Deezer lists collaborations and tribute acts with no releases next to the
/// real artist; those go last so the actual artist is the first row.
List<CatalogueArtist> _namesakesLast(List<CatalogueArtist> artists) => [
      ...artists.where((a) => (a.albumCount ?? 1) > 0),
      ...artists.where((a) => (a.albumCount ?? 1) <= 0),
    ];

class _Row extends StatelessWidget {
  const _Row({
    required this.leading,
    required this.title,
    required this.subtitle,
    required this.trailing,
    this.onTap,
    this.subtitleLines = 1,
  });

  final Widget leading;
  final String title;
  final String subtitle;
  final Widget trailing;
  final VoidCallback? onTap;

  /// A sentence that tells a person what to do next (why a song could not be
  /// fetched) gets a second line instead of an ellipsis (B42).
  final int subtitleLines;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(
            horizontal: Space.gutter, vertical: Space.sm),
        child: Row(
          children: [
            SizedBox.square(dimension: 52, child: leading),
            const SizedBox(width: Space.md),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(title,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: context.text.bodyLarge),
                  Text(subtitle,
                      maxLines: subtitleLines,
                      overflow: TextOverflow.ellipsis,
                      style: context.text.bodyMedium),
                ],
              ),
            ),
            const SizedBox(width: Space.sm),
            trailing,
          ],
        ),
      ),
    );
  }
}

class _ArtistRow extends ConsumerWidget {
  const _ArtistRow({required this.artist, this.libraryArtistId});

  final CatalogueArtist artist;

  /// The library's artist when the person has this one.
  final String? libraryArtistId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final owned = libraryArtistId != null;
    final parts = [
      // The "In your library" chip says what this row is and needs the room.
      if (!owned) 'Artist',
      if ((artist.fans ?? 0) > 0) formatFans(artist.fans!),
      if ((artist.albumCount ?? 0) > 0) plural(artist.albumCount!, 'release'),
    ];
    return _Row(
      leading: CoverArt(
        imageUrl: artist.imageUrl,
        circular: true,
        fallbackLabel: artist.name,
      ),
      title: artist.name,
      subtitle: parts.join(' - '),
      onTap: () => owned
          ? Nav.artist(context, libraryArtistId!)
          : Nav.catalogueArtist(context, artist.id, preloaded: artist),
      trailing: owned
          ? Chip(
              avatar: Icon(Icons.check_circle_rounded,
                  size: 18, color: context.colors.accent),
              label: const Text('In your library'),
            )
          : (ref.watch(instantAvailableProvider)
              ? const SizedBox.shrink()
              : RequestChip(artist: artist.name)),
    );
  }
}

class _AlbumRow extends ConsumerWidget {
  const _AlbumRow({required this.album});

  final CatalogueAlbum album;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final parts = [
      album.artistName,
      if (album.year != null) '${album.year}',
      if (album.trackCount != null) plural(album.trackCount!, 'song'),
    ];
    return _Row(
      leading: CoverArt(
        imageUrl: album.coverUrl,
        fallbackLabel: album.title,
        radius: Radii.art,
      ),
      title: album.title,
      subtitle: parts.join(' - '),
      onTap: () => Nav.catalogueAlbum(context, album),
      // With the instant-play service a row is just a row; asking for the
      // original files is on the release page (ADR-067).
      trailing: ref.watch(instantAvailableProvider)
          ? const SizedBox.shrink()
          : RequestChip(artist: album.artistName, album: album.title),
    );
  }
}

class _TrackRow extends ConsumerWidget {
  const _TrackRow({required this.track});

  final CatalogueTrack track;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final facade = ref.watch(playbackFacadeProvider);
    final playing = ref.watch(playbackSnapshotProvider).value;
    final instant = ref.watch(instantAvailableProvider);
    final status = ref.watch(instantStatusProvider(track.id));
    final isThis = playing?.track?.id == track.id ||
        (status?.track != null && playing?.track?.id == status!.track!.id);
    final preview = track.previewUrl;
    final working = status?.isWorking ?? false;

    void play() {
      if (instant) {
        if (isThis) {
          unawaited(facade.togglePlayPause());
        } else if (!working) {
          unawaited(ref.read(instantControllerProvider.notifier).play(track));
        }
        return;
      }
      if (preview == null) return;
      if (isThis) {
        unawaited(facade.togglePlayPause());
        return;
      }
      unawaited(facade.playPreview(
        id: track.id,
        title: track.title,
        uri: Uri.parse(preview),
        artist: track.artistName,
        catalogueArtistId: track.artistId,
        album: track.albumTitle,
        imageUrl: track.coverUrl,
        duration: const Duration(seconds: 30),
      ));
    }

    final playable = instant || preview != null;
    return _Row(
      onTap: playable ? play : null,
      subtitleLines: (status?.isFailed ?? false) ? 2 : 1,
      leading: Stack(
        fit: StackFit.expand,
        children: [
          CoverArt(
            imageUrl: track.coverUrl,
            fallbackLabel: track.albumTitle ?? track.title,
            radius: Radii.art,
          ),
          if (playable)
            DecoratedBox(
              decoration: BoxDecoration(
                color: Colors.black.withValues(alpha: 0.35),
                borderRadius: BorderRadius.circular(Radii.art),
              ),
              child: working
                  ? const Center(
                      child: SizedBox.square(
                        dimension: 22,
                        child: CircularProgressIndicator(
                            strokeWidth: 2, color: Colors.white),
                      ),
                    )
                  : Icon(
                      isThis && (playing?.isPlaying ?? false)
                          ? Icons.pause_rounded
                          : Icons.play_arrow_rounded,
                      color: Colors.white,
                    ),
            ),
        ],
      ),
      title: track.title,
      subtitle: working
          ? status!.label
          : (status?.isFailed ?? false)
              ? (status!.message ?? 'Could not get it')
              : '${track.artistName}'
                  '${track.albumTitle == null ? '' : ' - ${track.albumTitle}'}'
                  '${instant || preview == null ? '' : '  (preview)'}',
      trailing: instant
          ? const SizedBox.shrink()
          : RequestChip(
              artist: track.artistName,
              album: track.albumTitle,
            ),
    );
  }
}
