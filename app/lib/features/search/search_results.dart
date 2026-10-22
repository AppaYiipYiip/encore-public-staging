import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/navigation.dart';
import '../../data/catalogue/catalogue_models.dart';
import '../../design/tokens.dart';
import '../catalogue/catalogue_widgets.dart' show formatFans;
import '../common/cover_art.dart';
import '../common/format.dart';
import '../common/playability.dart';
import '../common/track_menu.dart';
import '../common/track_swipe.dart';
import '../common/widgets.dart';
import '../instant/instant_controller.dart';
import '../providers.dart';
import '../requests/request_providers.dart';
import '../requests/request_ui.dart';
import 'search_assembly.dart';

/// What a typed search shows (P1-07): the **Top result**, then songs, artists and albums, each list ranked, the library's and the
/// catalogue's mixed and looking the same. Whether the library has a song is never a header or a sentence; it is only a tie-break.
///
/// The library answers at once; the catalogue joins when it arrives, and the order is worked out again with both.
class SearchResultsView extends ConsumerStatefulWidget {
  const SearchResultsView({
    super.key,
    required this.query,
    required this.onOpen,
  });

  final String query;

  /// The person opened something from this search (remembered as a recent search).
  final ValueChanged<String> onOpen;

  @override
  ConsumerState<SearchResultsView> createState() => _SearchResultsViewState();
}

class _SearchResultsViewState extends ConsumerState<SearchResultsView> {
  /// The catalogue song the service was last asked to have ready: one per search, once.
  String? _prepared;

  void _prepareLikelyTap(AssembledSearch found) {
    final candidate =
        found.top is SongHit ? found.top! as SongHit : found.songs.firstOrNull;
    final track = candidate?.catalogue;
    if (track == null || track.id == _prepared) return;
    if (!ref.read(instantAvailableProvider)) return;
    _prepared = track.id;
    // The person is reading the results: have the service look the likely song up now (a first play spends seconds in the look-up),
    // so the tap that probably follows starts at the download.
    unawaited(ref.read(instantControllerProvider.notifier).prepare(track));
  }

  @override
  Widget build(BuildContext context) {
    final query = widget.query;
    final local = ref.watch(searchResultsProvider(query));
    final catalogue = ref.watch(catalogueSearchProvider(query));

    if (local.hasError) {
      return EmptyState(
        icon: Icons.error_outline_rounded,
        title: "Couldn't search",
        message: '${local.error}',
      );
    }
    if (!local.hasValue) return const SizedBox.shrink();

    final found = assembleSearch(
      query,
      local: local.requireValue,
      catalogue: catalogue.value,
    );
    WidgetsBinding.instance
        .addPostFrameCallback((_) => mounted ? _prepareLikelyTap(found) : null);

    if (found.isEmpty) {
      return catalogue.isLoading
          ? const Padding(
              padding: EdgeInsets.all(Space.xl),
              child: Center(child: CircularProgressIndicator()),
            )
          : EmptyState(
              icon: Icons.search_off_rounded,
              title: 'No results for "$query"',
              message: 'Check the spelling, or try fewer words.',
            );
    }

    return ListView(
      padding: const EdgeInsets.only(bottom: Space.xxl),
      children: [
        if (found.top != null) _TopResult(hit: found.top!, onOpen: _opened),
        if (found.songs.isNotEmpty) ...[
          const SectionHeader(title: 'Songs'),
          for (final (i, hit) in found.songs.indexed)
            _SongRow(hit: hit, index: i, songs: found.songs, onOpen: _opened),
        ],
        if (found.artists.isNotEmpty) ...[
          const SectionHeader(title: 'Artists'),
          for (final hit in found.artists)
            _ArtistRow(hit: hit, onOpen: _opened),
        ],
        if (found.albums.isNotEmpty) ...[
          const SectionHeader(title: 'Albums'),
          for (final hit in found.albums) _AlbumRow(hit: hit, onOpen: _opened),
        ],
      ],
    );
  }

  void _opened() => widget.onOpen(widget.query);
}

// ----------------------------------------------------------------- the top

class _TopResult extends ConsumerWidget {
  const _TopResult({required this.hit, required this.onOpen});

  final SearchHit hit;
  final VoidCallback onOpen;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.colors;
    final playable = ref.watch(playabilityProvider);
    final h = hit;
    // A song of the library that is not on the phone cannot be played without a connection.
    final unavailable =
        h is SongHit && h.local != null && !playable(h.local!.id);
    final (kind, title, artist) = switch (hit) {
      final SongHit h => ('Song', h.title, h.artist),
      final ArtistHit h => (
          'Artist',
          h.name,
          (h.catalogue?.fans ?? 0) > 0 ? formatFans(h.catalogue!.fans!) : null
        ),
      final AlbumHit h => ('Album', h.title, h.artist),
    };
    final art = switch (hit) {
      final SongHit h => CoverArt(
          coverArtId: h.local?.coverArt,
          imageUrl: h.catalogue?.coverUrl,
          fallbackLabel: h.album ?? h.title,
        ),
      final ArtistHit h => CoverArt(
          coverArtId: h.local?.coverArt,
          imageUrl: h.catalogue?.imageUrl,
          circular: true,
          fallbackLabel: h.name,
        ),
      final AlbumHit h => CoverArt(
          coverArtId: h.local?.coverArt,
          imageUrl: h.catalogue?.coverUrl,
          fallbackLabel: h.title,
          fallbackArtist: h.artist,
        ),
    };
    return Padding(
      padding: const EdgeInsets.fromLTRB(
          Space.gutter, Space.sm, Space.gutter, Space.sm),
      child: Semantics(
        button: true,
        label: 'Top result: $kind, $title${artist == null ? '' : ', $artist'}',
        excludeSemantics: true,
        child: Material(
          color: c.surfaceHigh,
          borderRadius: BorderRadius.circular(Radii.card),
          clipBehavior: Clip.antiAlias,
          child: InkWell(
            key: const Key('top-result'),
            onTap: () => _open(context, ref, hit, onOpen),
            child: Padding(
              padding: const EdgeInsets.all(Space.md),
              child: Row(
                children: [
                  SizedBox.square(dimension: 92, child: art),
                  const SizedBox(width: Space.md),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('Top result',
                            style: context.text.labelLarge
                                ?.copyWith(color: c.accent)),
                        const SizedBox(height: Space.xs),
                        Text(title,
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                            style: context.text.titleLarge
                                ?.copyWith(fontWeight: FontWeight.w800)),
                        Text(
                          [kind, if (artist != null) artist].join(' • '),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: context.text.bodyMedium
                              ?.copyWith(color: c.onBgMuted),
                        ),
                      ],
                    ),
                  ),
                  if (hit is SongHit)
                    unavailable
                        ? Icon(Icons.cloud_off_rounded,
                            size: 28, color: c.onBgFaint)
                        : Icon(Icons.play_circle_fill_rounded,
                            size: 44, color: c.accent),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// What a tap on a result does: a song plays, an artist or an album opens its page.
void _open(
    BuildContext context, WidgetRef ref, SearchHit hit, VoidCallback onOpen) {
  onOpen();
  switch (hit) {
    case final SongHit h:
      _play(ref, h);
    case final ArtistHit h:
      final libraryId = h.local?.id ?? h.libraryId;
      if (libraryId != null) {
        Nav.artist(context, libraryId);
      } else {
        Nav.catalogueArtist(context, h.catalogue!.id, preloaded: h.catalogue);
      }
    case final AlbumHit h:
      if (h.local != null) {
        Nav.album(context, h.local!.id);
      } else {
        Nav.catalogueAlbum(context, h.catalogue!);
      }
  }
}

void _play(WidgetRef ref, SongHit hit, {List<SongHit> songs = const []}) {
  final facade = ref.read(playbackFacadeProvider);
  final local = hit.local;
  if (local != null) {
    // The library's songs of this list play on from the one that was tapped.
    final owned = [
      for (final s in songs)
        if (s.local != null) s.local!,
    ];
    final tracks = owned.isEmpty ? [local] : owned;
    unawaited(facade.playTracks(tracks,
        startIndex: math.max(0, tracks.indexWhere((t) => t.id == local.id)),
        sourceName: 'Search'));
    return;
  }
  final track = hit.catalogue!;
  if (ref.read(instantAvailableProvider)) {
    unawaited(ref.read(instantControllerProvider.notifier).play(track));
    return;
  }
  final preview = track.previewUrl;
  if (preview == null) return;
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

// ------------------------------------------------------------------- songs

class _SongRow extends ConsumerWidget {
  const _SongRow({
    required this.hit,
    required this.index,
    required this.songs,
    required this.onOpen,
  });

  final SongHit hit;
  final int index;
  final List<SongHit> songs;
  final VoidCallback onOpen;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final playing = ref.watch(playbackSnapshotProvider).value;
    final playable = ref.watch(playabilityProvider);
    final local = hit.local;
    if (local != null) {
      return TrackSwipe(
        track: local,
        index: index,
        child: TrackTile(
          track: local,
          showAlbum: true,
          available: playable(local.id),
          isCurrent: playing?.track?.id == local.id,
          isPlaying: playing?.isPlaying ?? false,
          onTap: () {
            onOpen();
            _play(ref, hit, songs: songs);
          },
          onMore: () => showTrackMenu(context, local),
        ),
      );
    }
    return _CatalogueSongRow(
        track: hit.catalogue!,
        onTap: () {
          onOpen();
          _play(ref, hit);
        });
  }
}

/// A catalogue song looks like a library song (same cover size, same two lines); only the work in progress shows.
class _CatalogueSongRow extends ConsumerWidget {
  const _CatalogueSongRow({required this.track, required this.onTap});

  final CatalogueTrack track;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.colors;
    final facade = ref.watch(playbackFacadeProvider);
    final playing = ref.watch(playbackSnapshotProvider).value;
    final instant = ref.watch(instantAvailableProvider);
    final status = ref.watch(instantStatusProvider(track.id));
    final isThis = playing?.track?.id == track.id ||
        (status?.track != null && playing?.track?.id == status!.track!.id);
    final working = status?.isWorking ?? false;
    final failed = status?.isFailed ?? false;
    final playable = instant || track.previewUrl != null;

    final subtitle = working
        ? status!.label
        : failed
            ? (status!.message ?? 'Could not get it')
            : [
                track.artistName,
                if (track.albumTitle != null) track.albumTitle!,
                if (!instant && track.previewUrl != null) '(preview)',
              ].join(' • ');

    return InkWell(
      onTap: !playable
          ? null
          : () {
              if (isThis) {
                unawaited(facade.togglePlayPause());
              } else if (!working) {
                onTap();
              }
            },
      child: Padding(
        padding: const EdgeInsets.symmetric(
            horizontal: Space.gutter, vertical: Space.xs),
        child: Row(
          children: [
            SizedBox.square(
              dimension: 48,
              child: CoverArt(
                imageUrl: track.coverUrl,
                fallbackLabel: track.albumTitle ?? track.title,
              ),
            ),
            const SizedBox(width: Space.md),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Text(
                    track.title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: context.text.bodyLarge?.copyWith(
                      color: isThis ? c.accent : c.onBg,
                      fontWeight: isThis ? FontWeight.w700 : FontWeight.w500,
                    ),
                  ),
                  Text(
                    subtitle,
                    maxLines: failed ? 2 : 1,
                    overflow: TextOverflow.ellipsis,
                    style: context.text.bodyMedium,
                  ),
                ],
              ),
            ),
            if (working)
              const Padding(
                padding: EdgeInsets.all(Space.sm),
                child: SizedBox.square(
                  dimension: 22,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
              )
            else if (!instant)
              RequestChip(artist: track.artistName, album: track.albumTitle),
          ],
        ),
      ),
    );
  }
}

// ------------------------------------------------- artists and albums

/// One row of the artists and albums lists.
class _Row extends StatelessWidget {
  const _Row({
    required this.leading,
    required this.title,
    required this.subtitle,
    required this.trailing,
    this.onTap,
  });

  final Widget leading;
  final String title;
  final String subtitle;
  final Widget trailing;
  final VoidCallback? onTap;

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
                      maxLines: 1,
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
  const _ArtistRow({required this.hit, required this.onOpen});

  final ArtistHit hit;
  final VoidCallback onOpen;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final catalogue = hit.catalogue;
    final owned = hit.owned;
    final parts = [
      // The "In your library" chip says what this row is and needs the room.
      if (!owned) 'Artist',
      if (catalogue != null && (catalogue.fans ?? 0) > 0)
        formatFans(catalogue.fans!),
      if (catalogue != null && (catalogue.albumCount ?? 0) > 0)
        plural(catalogue.albumCount!, 'release'),
      if (catalogue == null) 'Artist',
    ];
    return _Row(
      leading: CoverArt(
        coverArtId: hit.local?.coverArt,
        imageUrl: catalogue?.imageUrl,
        circular: true,
        fallbackLabel: hit.name,
      ),
      title: hit.name,
      subtitle: parts.join(' - '),
      onTap: () => _open(context, ref, hit, onOpen),
      trailing: catalogue != null && owned
          ? Chip(
              avatar: Icon(Icons.check_circle_rounded,
                  size: 18, color: context.colors.accent),
              label: const Text('In your library'),
            )
          : (catalogue != null && !ref.watch(instantAvailableProvider)
              ? RequestChip(artist: catalogue.name)
              : const SizedBox.shrink()),
    );
  }
}

class _AlbumRow extends ConsumerWidget {
  const _AlbumRow({required this.hit, required this.onOpen});

  final AlbumHit hit;
  final VoidCallback onOpen;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final local = hit.local;
    final catalogue = hit.catalogue;
    final parts = [
      if (hit.artist != null) hit.artist!,
      if ((local?.year ?? catalogue?.year) != null)
        '${local?.year ?? catalogue?.year}',
      if ((local?.songCount ?? catalogue?.trackCount ?? 0) > 0)
        plural((local?.songCount ?? catalogue?.trackCount)!, 'song'),
    ];
    return _Row(
      leading: CoverArt(
        coverArtId: local?.coverArt,
        imageUrl: catalogue?.coverUrl,
        fallbackLabel: hit.title,
        fallbackArtist: local == null ? null : hit.artist,
        radius: Radii.art,
      ),
      title: hit.title,
      subtitle: parts.join(' - '),
      onTap: () => _open(context, ref, hit, onOpen),
      // With the instant-play service a row is just a row; asking for the original files is on the release page (ADR-067).
      trailing: catalogue != null && !ref.watch(instantAvailableProvider)
          ? RequestChip(artist: catalogue.artistName, album: catalogue.title)
          : const SizedBox.shrink(),
    );
  }
}
