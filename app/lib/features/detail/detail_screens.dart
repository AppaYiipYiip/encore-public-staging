import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/navigation.dart';
import '../../app/providers.dart';
import '../../data/catalogue/catalogue_models.dart' show CatalogueTrack;
import '../../data/db/app_database.dart';
import '../../data/repos/downloads_repository.dart';
import '../../design/tokens.dart';
import '../../domain/album_names.dart';
import '../../domain/artwork_color.dart';
import '../catalogue/artist_sections.dart';
import '../catalogue/catalogue_providers.dart';
import '../catalogue/catalogue_widgets.dart';
import '../common/artwork_color.dart';
import '../common/collection_menu.dart';
import '../common/cover_art.dart';
import '../common/download_button.dart';
import '../common/format.dart';
import '../common/playability.dart';
import '../common/playlist_actions.dart';
import '../common/track_menu.dart';
import '../common/track_swipe.dart';
import '../common/widgets.dart';
import '../downloads/download_line_providers.dart';
import '../downloads/download_providers.dart';
import '../downloads/download_status.dart';
import '../downloads/storage_widgets.dart';
import '../instant/instant_controller.dart';
import '../instant/tap_play.dart';
import '../providers.dart';
import 'album_gap.dart';
import 'hero_header.dart';

/// Download / more / shuffle / play row under the title.
class _ActionRow extends ConsumerWidget {
  const _ActionRow({
    required this.tracks,
    required this.sourceName,
    required this.sourceId,
    this.pinType,
    this.pinId,
    this.artistId,
    this.playlist,
  });

  final List<TrackRow> tracks;
  final String sourceName;

  /// Set when the page is a playlist the user can edit.
  final PlaylistRow? playlist;

  /// Stable collection id (`album:ID`) used to recognise "this is playing".
  final String sourceId;

  /// What the download toggle pins; `null` hides the toggle.
  final PinTargetType? pinType;
  final String? pinId;
  final String? artistId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final facade = ref.watch(playbackFacadeProvider);
    final snapshot = ref.watch(playbackSnapshotProvider).value;
    final c = context.colors;
    final isCurrent = snapshot?.sourceId == sourceId;
    final isPlaying = isCurrent && (snapshot?.isPlaying ?? false);
    final shuffle = isCurrent && (snapshot?.shuffle ?? false);

    return Row(
      children: [
        if (pinType != null && pinId != null)
          DownloadButton(type: pinType!, targetId: pinId!, name: sourceName),
        IconButton(
          tooltip: 'More options',
          icon: const Icon(Icons.more_vert_rounded),
          color: c.onBgMuted,
          onPressed: tracks.isEmpty && playlist == null
              ? null
              : () => showCollectionMenu(
                    context,
                    title: sourceName,
                    tracks: tracks,
                    artistId: artistId,
                    playlist: playlist,
                    leaveAfterDelete: true,
                  ),
        ),
        const Spacer(),
        IconButton(
          tooltip: shuffle ? 'Shuffle on' : 'Shuffle',
          icon: const Icon(Icons.shuffle_rounded),
          color: shuffle ? c.accent : c.onBgMuted,
          iconSize: 28,
          onPressed: tracks.isEmpty
              ? null
              : () => facade.playTracks(tracks,
                  sourceName: sourceName,
                  sourceId: sourceId,
                  shuffle: true,
                  skipUnavailable: true),
        ),
        const SizedBox(width: Space.sm),
        PlayButton(
          isPlaying: isPlaying,
          size: 56,
          onPressed: tracks.isEmpty
              ? null
              : () => isCurrent
                  ? facade.togglePlayPause()
                  : facade.playTracks(tracks,
                      sourceName: sourceName,
                      sourceId: sourceId,
                      skipUnavailable: true),
        ),
      ],
    );
  }
}

class _TrackList extends ConsumerWidget {
  const _TrackList({
    required this.tracks,
    required this.sourceName,
    required this.sourceId,
    this.numbered = false,
    this.showAlbum = false,
    this.editablePlaylist,
    this.positions,
  });

  final List<TrackRow> tracks;
  final String sourceName;
  final String sourceId;
  final bool numbered;
  final bool showAlbum;

  /// The playlist this list shows, when the user may remove entries from it;
  /// [positions] are the entries' positions, parallel to [tracks].
  final PlaylistRow? editablePlaylist;
  final List<int>? positions;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final facade = ref.watch(playbackFacadeProvider);
    final snapshot = ref.watch(playbackSnapshotProvider).value;
    final downloaded = ref.watch(downloadedIdsProvider).value ?? const {};
    final playable = ref.watch(playabilityProvider);

    return SliverList.builder(
      itemCount: tracks.length,
      itemBuilder: (context, i) {
        final t = tracks[i];
        final current = snapshot?.track?.id == t.id;
        return TrackSwipe(
          track: t,
          index: i,
          child: TrackTile(
            track: t,
            showArt: !numbered,
            number: numbered ? (t.trackNo ?? i + 1) : null,
            showAlbum: showAlbum,
            isCurrent: current,
            isPlaying: current && (snapshot?.isPlaying ?? false),
            downloaded: downloaded.contains(t.id),
            available: playable(t.id),
            onTap: () => facade.playTracks(tracks,
                startIndex: i, sourceName: sourceName, sourceId: sourceId),
            onMore: () => showTrackMenu(
              context,
              t,
              fromPlaylist: editablePlaylist == null || positions == null
                  ? null
                  : (
                      playlistId: editablePlaylist!.id,
                      playlistName: editablePlaylist!.name,
                      position: positions![i],
                    ),
            ),
          ),
        );
      },
    );
  }
}

Widget _meta(BuildContext context, String text) =>
    Text(text, style: context.text.bodyMedium);

// ------------------------------------------------------------------- album

class AlbumScreen extends ConsumerWidget {
  const AlbumScreen({super.key, required this.albumId});

  final String albumId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final album = ref.watch(albumProvider(albumId)).value;
    final tracks = ref.watch(albumTracksProvider(albumId)).value ?? const [];
    // What the catalogue says the album still lacks (B39): looked up in the
    // background, never waited for.
    final gap = ref.watch(albumGapProvider(albumId)).value;
    if (album == null) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    final total = tracks.fold<int>(0, (s, t) => s + (t.durationSec ?? 0));
    final swatch = ref
        .watch(artworkSwatchProvider(
            (albumId: album.id, coverArtId: album.coverArt)))
        .value;
    final tint = swatch == null ? null : backdropFor(swatch);

    return CollectionScaffold(
      title: albumDisplayName(album.name),
      tint: tint,
      art: CoverArt(
        coverArtId: album.coverArt,
        fallbackLabel: albumDisplayName(album.name),
        fallbackArtist: album.artist,
        radius: Radii.hero,
      ),
      subtitleLines: [
        if (album.artist != null)
          InkWell(
            onTap: album.artistId == null
                ? null
                : () => Nav.artist(context, album.artistId!),
            // A 48 dp high target; the text keeps its place.
            child: ConstrainedBox(
              constraints: const BoxConstraints(minHeight: 48, minWidth: 48),
              child: Align(
                alignment: Alignment.centerLeft,
                widthFactor: 1,
                child: Text(album.artist!,
                    style: context.text.titleMedium
                        ?.copyWith(fontWeight: FontWeight.w700)),
              ),
            ),
          ),
        _meta(
          context,
          [
            if (album.year != null) '${album.year}',
            gap == null
                ? plural(tracks.length, 'song')
                : '${gap.ownedCount} of ${gap.total} songs',
            formatTotalDuration(total),
          ].where((e) => e.isNotEmpty).join(' • '),
        ),
      ],
      actions: _ActionRow(
        tracks: tracks,
        sourceName: albumDisplayName(album.name),
        sourceId: 'album:${album.id}',
        pinType: PinTargetType.album,
        pinId: album.id,
        artistId: album.artistId,
      ),
      slivers: [
        _TrackList(
          tracks: tracks,
          sourceName: albumDisplayName(album.name),
          sourceId: 'album:${album.id}',
          numbered: true,
        ),
        if (gap != null) ..._missingSongs(ref, album, gap),
      ],
    );
  }
}

/// "Not in your library": the songs of an album the library holds only part of
/// (B39), each one a tap away - the song is fetched into the library and
/// plays, as on a catalogue page.
List<Widget> _missingSongs(WidgetRef ref, AlbumRow album, AlbumGap gap) {
  final facade = ref.watch(playbackFacadeProvider);
  final snapshot = ref.watch(playbackSnapshotProvider).value;
  final instant = ref.watch(instantAvailableProvider);
  final sourceId = 'album-missing:${album.id}';
  return [
    const SliverToBoxAdapter(
        child: SectionHeader(title: 'Not in your library')),
    SliverList.builder(
      itemCount: gap.missing.length,
      itemBuilder: (context, i) {
        final t = gap.missing[i];
        final status = ref.watch(instantStatusProvider(t.id));
        final playingId = snapshot?.track?.id;
        final current = playingId == t.id ||
            (status?.track != null && playingId == status!.track!.id);
        void preview() => unawaited(playExplicitPreview(
              facade,
              gap.missing,
              index: i,
              sourceName: albumDisplayName(album.name),
              sourceId: sourceId,
            ));
        return PreviewTrackTile(
          track: t,
          number: t.trackNumber ?? i + 1,
          isCurrent: current,
          isPlaying: current && (snapshot?.isPlaying ?? false),
          instant: instant,
          status: status,
          onTap: () => unawaited(tapPlayRun(ref, gap.missing,
              startIndex: i,
              sourceName: albumDisplayName(album.name),
              sourceId: sourceId)),
          onLongPress: instant && t.previewUrl != null ? preview : null,
        );
      },
    ),
  ];
}

// ---------------------------------------------------------------- playlist

class PlaylistScreen extends ConsumerWidget {
  const PlaylistScreen({super.key, required this.playlistId});

  final String playlistId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final playlist = ref.watch(playlistProvider(playlistId)).value;
    final entries =
        ref.watch(playlistEntriesProvider(playlistId)).value ?? const [];
    final tracks = [for (final e in entries) e.track];
    final username = ref.watch(activeServerProvider).value?.username;
    final editable = playlist != null && isEditablePlaylist(playlist, username)
        ? playlist
        : null;
    final mosaic =
        ref.watch(playlistCoverIdsProvider(playlistId)).value ?? const [];
    final ensure = ref.watch(ensurePlaylistProvider(playlistId));
    if (playlist == null) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    final total = tracks.fold<int>(0, (s, t) => s + (t.durationSec ?? 0));
    // The header takes the colour of the first song's album.
    final first = tracks.firstOrNull;
    final swatch = first == null
        ? null
        : ref
            .watch(artworkSwatchProvider(
                (albumId: first.albumId, coverArtId: first.coverArt)))
            .value;

    return CollectionScaffold(
      title: playlist.name,
      tint: swatch == null ? null : backdropFor(swatch),
      art: CoverArt(
        coverArtId: playlist.coverArt,
        mosaicIds: mosaic,
        fallbackLabel: playlist.name,
        radius: Radii.hero,
      ),
      subtitleLines: [
        if (playlist.comment?.isNotEmpty == true)
          _meta(context, playlist.comment!),
        _meta(
          context,
          [
            if (playlist.owner != null) playlist.owner!,
            plural(tracks.isEmpty ? playlist.songCount : tracks.length, 'song'),
            formatTotalDuration(total),
          ].where((e) => e.isNotEmpty).join(' • '),
        ),
        // How far the two stages of the download have got (docs/design S-17); nothing when it is not downloaded or finished.
        DownloadStatus(
            target: DownloadTarget.pin(PinTargetType.playlist, playlist.id)),
      ],
      actions: _ActionRow(
        tracks: tracks,
        sourceName: playlist.name,
        sourceId: 'playlist:${playlist.id}',
        pinType: PinTargetType.playlist,
        pinId: playlist.id,
        playlist: editable,
      ),
      slivers: [
        if (tracks.isEmpty && playlist.songCount == 0)
          SliverToBoxAdapter(
            child: EmptyState(
              icon: Icons.queue_music_rounded,
              title: editable == null
                  ? 'This playlist is empty'
                  : 'Add songs to "${playlist.name}"',
              message: editable == null
                  ? null
                  : 'Use the three-dot menu on a song or an album and '
                      'choose "Add to playlist".',
              actionLabel: editable == null ? null : 'Find songs',
              onAction: editable == null ? null : () => context.go('/search'),
            ),
          )
        else if (tracks.isEmpty && playlist.songCount > 0)
          SliverToBoxAdapter(
            child: ensure.hasError
                ? Padding(
                    padding: const EdgeInsets.all(Space.xl),
                    child: Column(
                      children: [
                        const Text("Couldn't load this playlist."),
                        const SizedBox(height: Space.sm),
                        TextButton(
                          onPressed: () => ref
                              .invalidate(ensurePlaylistProvider(playlistId)),
                          child: const Text('Try again'),
                        ),
                      ],
                    ),
                  )
                : const Padding(
                    padding: EdgeInsets.all(Space.xl),
                    child: Center(child: CircularProgressIndicator()),
                  ),
          )
        else
          _TrackList(
            tracks: tracks,
            sourceName: playlist.name,
            sourceId: 'playlist:${playlist.id}',
            showAlbum: true,
            editablePlaylist: editable,
            positions: [for (final e in entries) e.position],
          ),
      ],
    );
  }
}

// ------------------------------------------------------------------ artist

class ArtistScreen extends ConsumerWidget {
  const ArtistScreen({super.key, required this.artistId});

  final String artistId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final artist = ref.watch(artistProvider(artistId)).value;
    final albums = ref.watch(artistAlbumsProvider(artistId)).value ?? const [];
    if (artist == null) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    final facade = ref.watch(playbackFacadeProvider);
    final c = context.colors;
    final firstAlbum = albums.firstOrNull;
    final swatch = ref
        .watch(artworkSwatchProvider((
          albumId: firstAlbum?.id,
          coverArtId: artist.coverArt ?? firstAlbum?.coverArt,
        )))
        .value;

    // What the catalogue knows of this artist: its popular songs and everything it released, next to what the library holds. Only
    // when it is reachable; without it the page is the library's own albums.
    final catalogueArtist =
        ref.watch(libraryArtistCatalogueProvider(artistId)).value;
    final releasesAsync = catalogueArtist == null
        ? null
        : ref.watch(catalogueArtistReleasesProvider(
            (catalogueArtist.id, catalogueArtist.name)));
    final releases = releasesAsync?.value;
    final instant = ref.watch(instantAvailableProvider);
    final popular = catalogueArtist == null
        ? const <CatalogueTrack>[]
        : ref.watch(catalogueArtistTopProvider(catalogueArtist.id)).value ??
            const <CatalogueTrack>[];
    final popularSource = 'catalogue-artist:${catalogueArtist?.id}';

    // "2 of 5 albums on your server": what the artist has made, next to what
    // the library holds, instead of only the library's own count (which made
    // an artist with five albums look like one with two).
    final catalogueAlbums =
        releases == null ? null : groupReleases(releases).albums;
    final albumsLine = () {
      if (catalogueAlbums == null || catalogueAlbums.isEmpty) {
        return plural(albums.length, 'album');
      }
      final total = catalogueAlbums.length;
      final matched = catalogueAlbums.where((r) => r.owned).length;
      // Titles may not match one for one; never show fewer than the library
      // plainly has.
      final have = math.min(total, math.max(matched, albums.length));
      return have >= total
          ? plural(total, 'album')
          : '$have of $total albums on your server';
    }();

    // The library's own albums, in a grid: the page while the catalogue is not there (offline, still loading, or it failed).
    final libraryDiscography = <Widget>[
      const SliverToBoxAdapter(child: SectionHeader(title: 'Discography')),
      SliverPadding(
        padding: const EdgeInsets.symmetric(horizontal: Space.gutter),
        sliver: SliverGrid.builder(
          gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
            maxCrossAxisExtent: 180,
            mainAxisSpacing: Space.lg,
            crossAxisSpacing: Space.md,
            childAspectRatio: 0.78,
          ),
          itemCount: albums.length,
          itemBuilder: (context, i) {
            final a = albums[i];
            return MediaCard(
              title: albumDisplayName(a.name),
              subtitle: a.year?.toString(),
              coverArtId: a.coverArt,
              artistName: artist.name,
              width: double.infinity,
              onTap: () => Nav.album(context, a.id),
            );
          },
        ),
      ),
    ];

    return CollectionScaffold(
      title: artist.name,
      art: CoverArt(
        // The server's picture can belong to a namesake (an unrelated "Tool"
        // showed another band's cover); once the catalogue has settled which
        // artist this is, its picture wins.
        coverArtId: catalogueArtist?.imageUrl == null ? artist.coverArt : null,
        imageUrl: catalogueArtist?.imageUrl,
        fallbackLabel: artist.name,
        circular: true,
      ),
      subtitleLines: [
        _meta(
          context,
          [
            albumsLine,
            if (catalogueArtist?.fans != null && catalogueArtist!.fans! > 0)
              formatFans(catalogueArtist.fans!),
          ].join(' - '),
        ),
      ],
      actions: Row(
        children: [
          const Spacer(),
          PlayButton(
            isPlaying: false,
            onPressed: albums.isEmpty && popular.isEmpty
                ? null
                : () async {
                    // With the popular songs on the page, play is those (as everywhere else); otherwise what the library holds.
                    if (instant && popular.isNotEmpty) {
                      unawaited(ref
                          .read(instantControllerProvider.notifier)
                          .playRun(popular,
                              startIndex: 0,
                              sourceName: artist.name,
                              sourceId: popularSource));
                      return;
                    }
                    // Gone if the person signed out while this page was open.
                    final repo = ref.read(libraryRepositoryProvider);
                    if (repo == null) return;
                    final tracks = await repo.artistTracks(artistId);
                    await facade.playTracks(tracks,
                        sourceName: artist.name,
                        sourceId: 'artist:${artist.id}');
                  },
          ),
        ],
      ),
      tint: swatch == null ? c.surfaceHigh : backdropFor(swatch),
      circularArt: true,
      slivers: [
        if (catalogueArtist != null && releasesAsync != null) ...[
          ArtistPopularSection(
              artist: catalogueArtist, sourceId: popularSource),
          if (releases != null)
            ArtistReleaseSections(releases: withLibraryAlbums(releases, albums))
          else if (releasesAsync.hasError)
            ...libraryDiscography
          else
            loadingSliver(),
        ] else
          ...libraryDiscography,
      ],
    );
  }
}

// ------------------------------------------------------------------- liked

class LikedScreen extends ConsumerWidget {
  const LikedScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tracks = ref.watch(likedTracksProvider).value ?? const [];
    final c = context.colors;
    return CollectionScaffold(
      title: 'Liked Songs',
      tint: c.accent.withValues(alpha: 0.55),
      art: DecoratedBox(
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(Radii.hero),
          gradient: LinearGradient(
            colors: [c.accent, c.accent.withValues(alpha: 0.4)],
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
          ),
        ),
        child: Icon(Icons.favorite_rounded, size: 96, color: c.onAccent),
      ),
      subtitleLines: [_meta(context, plural(tracks.length, 'song'))],
      actions: _ActionRow(
        tracks: tracks,
        sourceName: 'Liked Songs',
        sourceId: 'liked',
        pinType: PinTargetType.liked,
        pinId: kLikedPinId,
      ),
      slivers: [
        if (tracks.isEmpty)
          const SliverFillRemaining(
            hasScrollBody: false,
            child: EmptyState(
              icon: Icons.favorite_border_rounded,
              title: 'Songs you like appear here',
              message: 'Tap the heart on any song to save it.',
            ),
          )
        else
          _TrackList(
            tracks: tracks,
            sourceName: 'Liked Songs',
            sourceId: 'liked',
            showAlbum: true,
          ),
      ],
    );
  }
}

// -------------------------------------------------------------- downloaded

class DownloadedScreen extends ConsumerWidget {
  const DownloadedScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tracks = ref.watch(downloadedTracksProvider).value ?? const [];
    final storage = ref.watch(storageSummaryProvider).value;
    final c = context.colors;
    return CollectionScaffold(
      title: 'Downloaded',
      tint: c.surfaceHigh,
      art: DecoratedBox(
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(Radii.hero),
          color: c.accent,
        ),
        child: Icon(Icons.arrow_downward_rounded, size: 96, color: c.onAccent),
      ),
      subtitleLines: [
        _meta(
          context,
          [
            plural(tracks.length, 'song'),
            if (storage != null && storage.bytes > 0)
              formatBytes(storage.bytes),
          ].join(' • '),
        ),
      ],
      actions: _ActionRow(
        tracks: tracks,
        sourceName: 'Downloaded',
        sourceId: 'downloaded',
      ),
      slivers: [
        const SliverToBoxAdapter(child: DownloadsPausedBanner()),
        if (tracks.isEmpty)
          const SliverFillRemaining(
            hasScrollBody: false,
            child: EmptyState(
              icon: Icons.arrow_downward_rounded,
              title: 'Nothing downloaded yet',
              message: 'Tap the download arrow on any album or playlist.',
            ),
          )
        else
          _TrackList(
            tracks: tracks,
            sourceName: 'Downloaded',
            sourceId: 'downloaded',
            showAlbum: true,
          ),
      ],
    );
  }
}

// ------------------------------------------------------------------- genre

class GenreScreen extends ConsumerWidget {
  const GenreScreen({super.key, required this.genre});

  final String genre;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final albums = ref.watch(genreAlbumsProvider(genre)).value ?? const [];
    return Scaffold(
      appBar: AppBar(title: Text(genre)),
      body: albums.isEmpty
          ? const EmptyState(
              icon: Icons.library_music_outlined,
              title: 'Nothing here yet',
            )
          : GridView.builder(
              padding: const EdgeInsets.all(Space.gutter),
              gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
                maxCrossAxisExtent: 180,
                mainAxisSpacing: Space.lg,
                crossAxisSpacing: Space.md,
                childAspectRatio: 0.78,
              ),
              itemCount: albums.length,
              itemBuilder: (context, i) {
                final a = albums[i];
                return MediaCard(
                  title: albumDisplayName(a.name),
                  subtitle: a.artist,
                  coverArtId: a.coverArt,
                  artistName: a.artist,
                  width: double.infinity,
                  onTap: () => Nav.album(context, a.id),
                );
              },
            ),
    );
  }
}
