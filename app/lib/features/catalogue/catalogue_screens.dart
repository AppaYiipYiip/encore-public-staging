import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/navigation.dart';
import '../../data/catalogue/catalogue_models.dart';
import '../../data/repos/downloads_repository.dart';
import '../../design/tokens.dart';
import '../common/cover_art.dart';
import '../common/download_button.dart';
import '../common/format.dart';
import '../common/widgets.dart';
import '../detail/hero_header.dart';
import '../instant/instant_controller.dart';
import '../instant/instant_warmup.dart';
import '../instant/release_save.dart';
import '../instant/tap_play.dart';
import '../providers.dart';
import '../requests/request_ui.dart';
import 'adding_music_help.dart';
import 'artist_sections.dart';
import 'catalogue_providers.dart';
import 'catalogue_widgets.dart';

/// "Add to library": fetch every song of a release into the library without
/// playing any, with the progress where the button was.
class _AddToLibraryButton extends ConsumerWidget {
  const _AddToLibraryButton({
    required this.tracks,
    required this.releaseId,
    required this.encore,
    this.title,
    this.artist,
  });

  final List<CatalogueTrack> tracks;

  /// Who the release is, written down with the save so Library > Downloaded can name it offline.
  final String? title;
  final String? artist;

  /// `cat:<catalogue album id>`: how the server knows this release (docs/17 "Saving a release").
  final String releaseId;

  /// On an Encore server the server does it and the screen shows only what it confirmed (D-21).
  final bool encore;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (encore) return _encoreButton(context, ref);
    final statuses = ref.watch(instantControllerProvider);
    final mine = [for (final t in tracks) statuses[t.id]];
    final ready = mine.where((s) => s?.isReady ?? false).length;
    final working = mine.any((s) => s?.isWorking ?? false);
    final c = context.colors;
    if (tracks.isNotEmpty && ready == tracks.length) {
      return Chip(
        avatar: Icon(Icons.check_circle_rounded, size: 18, color: c.accent),
        label: const Text('In your library'),
      );
    }
    if (working) {
      return Chip(
        avatar: SizedBox.square(
          dimension: 16,
          child: CircularProgressIndicator(strokeWidth: 2, color: c.accent),
        ),
        label: Text('Adding $ready of ${tracks.length}'),
      );
    }
    return OutlinedButton.icon(
      onPressed: tracks.isEmpty
          ? null
          : () => unawaited(
              ref.read(instantControllerProvider.notifier).addAll(tracks)),
      icon: const Icon(Icons.library_add_rounded, size: 18),
      label: const Text('Add to library'),
    );
  }

  Widget _encoreButton(BuildContext context, WidgetRef ref) {
    final release = ref.watch(releaseStateProvider(releaseId));
    final c = context.colors;
    if (release?.phase == ReleasePhase.saved) {
      return Chip(
        avatar: Icon(Icons.check_circle_rounded, size: 18, color: c.accent),
        label: const Text('In your library'),
      );
    }
    if (release?.phase == ReleasePhase.saving) {
      return Chip(
        avatar: SizedBox.square(
          dimension: 16,
          child: CircularProgressIndicator(strokeWidth: 2, color: c.accent),
        ),
        label: const Text('Adding to your library'),
      );
    }
    return OutlinedButton.icon(
      onPressed: tracks.isEmpty
          ? null
          : () async {
              final messenger = ScaffoldMessenger.of(context);
              final problem = await ref
                  .read(releaseSavesProvider.notifier)
                  .save(releaseId, tracks,
                      download: false, title: title, artist: artist);
              if (problem != null) {
                messenger
                  ..hideCurrentSnackBar()
                  ..showSnackBar(SnackBar(content: Text(problem)));
              }
            },
      icon: const Icon(Icons.library_add_rounded, size: 18),
      label: const Text('Add to library'),
    );
  }
}

/// "Download": adds the release to the library *and* keeps it on the phone, in
/// one tap (ADR-067). A person never has to know that these are two steps.
class _CatalogueDownloadButton extends ConsumerWidget {
  const _CatalogueDownloadButton({
    required this.album,
    required this.tracks,
    required this.releaseId,
    required this.encore,
  });

  final CatalogueAlbum album;
  final List<CatalogueTrack> tracks;
  final String releaseId;
  final bool encore;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (encore) return _encoreButton(ref);
    final statuses = ref.watch(instantControllerProvider);
    final mine = [for (final t in tracks) statuses[t.id]];
    final working = mine.any((s) => s?.isWorking ?? false);
    final c = context.colors;
    if (working) {
      return const SizedBox.square(
        dimension: 48,
        child: Center(
          child: SizedBox.square(
            dimension: 22,
            child: CircularProgressIndicator(strokeWidth: 2.4),
          ),
        ),
      );
    }
    return IconButton(
      tooltip: 'Download ${album.title} for offline listening',
      icon: Icon(Icons.arrow_downward_rounded, color: c.onBgMuted),
      style: IconButton.styleFrom(
        side: BorderSide(color: c.onBgMuted, width: 1.6),
      ),
      onPressed:
          tracks.isEmpty ? null : () => unawaited(_download(context, ref)),
    );
  }

  /// On an Encore server (D-21): the server saves the release and keeps its songs; the phone pins them at once and downloads each as the
  /// server has it. The ring shows from the tap until the files are on the phone, and a failure is said in words.
  Widget _encoreButton(WidgetRef ref) {
    final release = ref.watch(releaseStateProvider(releaseId));
    final asked = release?.download ?? false;
    final PinState state;
    if (release?.phase == ReleasePhase.saving && asked) {
      state = const PinState(
          pinned: true); // the ring, until the server has answered
    } else if (release?.phase == ReleasePhase.saved && asked) {
      state = ref.watch(releasePinStateProvider(release!.refIds.join(',')));
    } else {
      state = PinState.none;
    }
    return DownloadButton(
      type: PinTargetType.album,
      targetId: releaseId,
      name: album.title,
      stateOverride: tracks.isEmpty ? PinState.none : state,
      preparingLabel: 'Getting ${album.title} on your server',
      onPin: () => ref.read(releaseSavesProvider.notifier).save(
          releaseId, tracks,
          download: true, title: album.title, artist: album.artistName),
      onRemove: () async => releaseRemovedNote(
          album.title,
          await ref
              .read(releaseSavesProvider.notifier)
              .removeDownload(releaseId)),
    );
  }

  Future<void> _download(BuildContext context, WidgetRef ref) async {
    final messenger = ScaffoldMessenger.of(context);
    messenger
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(
        content: Text('Getting ${album.title} - it will download to this '
            'phone when it is in your library.'),
      ));
    final result = await ref
        .read(instantControllerProvider.notifier)
        .addAndKeepOffline(tracks,
            artist: album.artistName, albumTitle: album.title);
    // The person may have left the page while the songs arrived.
    if (result.pinnedAlbumId == null || !context.mounted) return;
    messenger
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(
        content: Text('Downloading ${album.title} for offline listening'),
      ));
  }
}

/// What a catalogue page says on an Encore server, where playing a song does not save it.
const String kEncorePlayLine =
    'Tap a song to play it. Like it or download it to keep it on your server.';

/// The one calm sentence under a release's buttons, with the way to the
/// longer explanation.
SliverToBoxAdapter _explain(BuildContext context, String text,
        {required bool instant}) =>
    SliverToBoxAdapter(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(
            Space.gutter, Space.sm, Space.gutter, Space.md),
        child: Text.rich(
          TextSpan(
            style: context.text.bodyMedium,
            children: [
              TextSpan(text: '$text '),
              WidgetSpan(
                alignment: PlaceholderAlignment.baseline,
                baseline: TextBaseline.alphabetic,
                child: InkWell(
                  onTap: () =>
                      unawaited(showAddingMusicHelp(context, instant: instant)),
                  child: Text(
                    'How does this work?',
                    style: context.text.bodyMedium?.copyWith(
                      color: context.colors.accent,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );

/// Shown when a page cannot get its release from the catalogue.
class _Unavailable extends StatelessWidget {
  const _Unavailable({required this.loading, required this.onRetry});

  final bool loading;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(),
      body: loading
          ? const Center(child: CircularProgressIndicator())
          : EmptyState(
              icon: Icons.cloud_off_rounded,
              title: "Couldn't load this release",
              message: 'Check your connection and try again.',
              actionLabel: 'Try again',
              onAction: onRetry,
            ),
    );
  }
}

// ------------------------------------------------------------------- album

/// A release that is not in the library: songs to preview, one Request.
class CatalogueAlbumScreen extends ConsumerWidget {
  const CatalogueAlbumScreen({
    super.key,
    required this.albumId,
    this.preloaded,
  });

  final String albumId;

  /// The search result the user tapped; shows the header with no wait.
  final CatalogueAlbum? preloaded;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final fetched =
        preloaded == null ? ref.watch(catalogueAlbumProvider(albumId)) : null;
    final album = preloaded ?? fetched?.value;
    if (album == null) {
      return _Unavailable(
        loading: fetched?.isLoading ?? false,
        onRetry: () => ref.invalidate(catalogueAlbumProvider(albumId)),
      );
    }

    final tracks = ref.watch(catalogueAlbumTracksProvider(albumId));
    ref.watch(albumWarmupProvider(albumId));
    final facade = ref.watch(playbackFacadeProvider);
    final snapshot = ref.watch(playbackSnapshotProvider).value;
    final sourceId = 'catalogue-album:$albumId';
    final isCurrent = snapshot?.sourceId == sourceId;
    final isPlaying = isCurrent && (snapshot?.isPlaying ?? false);
    final list = tracks.value ?? const <CatalogueTrack>[];
    final instant = ref.watch(instantAvailableProvider);
    final portal = ref.watch(requestPortalOfferedProvider);
    final encore = ref.watch(onEncoreServerProvider).value ?? false;
    final saves =
        encore ? ref.watch(releaseStateProvider('cat:$albumId')) : null;
    final savedSongs = saves?.phase == ReleasePhase.saved
        ? saves!.refIds.toSet()
        : const <String>{};
    final firstPlayable =
        list.indexWhere((t) => instant || t.previewUrl != null);

    final meta = [
      if (album.year != null) '${album.year}',
      if (album.trackCount != null) plural(album.trackCount!, 'song'),
      if (recordTypeLabel(album.recordType) != null)
        recordTypeLabel(album.recordType)!,
    ].join(' • ');

    return CollectionScaffold(
      title: album.title,
      art: CoverArt(
        imageUrl: album.coverUrl,
        fallbackLabel: album.title,
        radius: Radii.hero,
      ),
      subtitleLines: [
        InkWell(
          onTap: () => _openArtist(context, ref, album),
          child: Text(
            album.artistName,
            style:
                context.text.titleMedium?.copyWith(fontWeight: FontWeight.w700),
          ),
        ),
        if (meta.isNotEmpty) Text(meta, style: context.text.bodyMedium),
      ],
      actions: Row(
        children: [
          if (instant) ...[
            // Spotify's words: add it to the library, download it. Asking for
            // the original files is rare and lives in the menu (ADR-067).
            _AddToLibraryButton(
                tracks: list,
                releaseId: 'cat:$albumId',
                encore: encore,
                title: album.title,
                artist: album.artistName),
            const SizedBox(width: Space.xs),
            _CatalogueDownloadButton(
                album: album,
                tracks: list,
                releaseId: 'cat:$albumId',
                encore: encore),
            CatalogueMoreMenu(artist: album.artistName, album: album.title),
          ] else if (portal)
            RequestChip(artist: album.artistName, album: album.title),
          const Spacer(),
          PlayButton(
            isPlaying: isPlaying,
            size: 56,
            onPressed: firstPlayable < 0
                ? null
                : () => isCurrent
                    ? facade.togglePlayPause()
                    : unawaited(tapPlayRun(ref, list,
                        startIndex: firstPlayable,
                        sourceName: album.title,
                        sourceId: sourceId)),
          ),
        ],
      ),
      slivers: [
        _explain(
          context,
          instant
              ? (encore
                  ? kEncorePlayLine
                  : 'Tap a song to play it. It is added to your library '
                      'first, which takes a few seconds.')
              : 'Previews are 30 seconds. Request the album and it is added '
                  'to your library in full.',
          instant: instant,
        ),
        tracks.when(
          loading: loadingSliver,
          error: (_, __) => retrySliver(
              () => ref.invalidate(catalogueAlbumTracksProvider(albumId))),
          data: (items) => items.isEmpty
              ? retrySliver(
                  () => ref.invalidate(catalogueAlbumTracksProvider(albumId)))
              : SliverList.builder(
                  itemCount: items.length,
                  itemBuilder: (context, i) {
                    final t = items[i];
                    final live = ref.watch(instantStatusProvider(t.id));
                    final playingId = snapshot?.track?.id;
                    final current = playingId == t.id ||
                        (live?.track != null && playingId == live!.track!.id);
                    // On an Encore server a resolved song is not a saved one: its green check shows only once the server confirmed the
                    // release (D-21). A spinner or a failure still shows.
                    final status = encore &&
                            (live?.isReady ?? false) &&
                            !savedSongs.contains(live!.track?.id)
                        ? null
                        : live;
                    void preview() => unawaited(playExplicitPreview(
                          facade,
                          items,
                          index: i,
                          sourceName: album.title,
                          sourceId: sourceId,
                        ));
                    return PreviewTrackTile(
                      track: t,
                      number: i + 1,
                      isCurrent: current,
                      isPlaying: current && (snapshot?.isPlaying ?? false),
                      instant: instant,
                      status: status,
                      onTap: () => unawaited(tapPlayRun(ref, items,
                          startIndex: i,
                          sourceName: album.title,
                          sourceId: sourceId)),
                      onLongPress:
                          instant && t.previewUrl != null ? preview : null,
                    );
                  },
                ),
        ),
      ],
    );
  }

  /// The library page when the user owns the artist, otherwise the
  /// catalogue page.
  Future<void> _openArtist(
      BuildContext context, WidgetRef ref, CatalogueAlbum album) async {
    final owned =
        await ref.read(libraryMatcherProvider)?.findArtist(album.artistName);
    if (!context.mounted) return;
    if (owned != null) {
      Nav.artist(context, owned.id);
    } else if (album.artistId != null) {
      Nav.catalogueArtist(context, album.artistId!);
    }
  }
}

// ------------------------------------------------------------------ artist

/// An artist that is not in the library: popular songs and releases.
class CatalogueArtistScreen extends ConsumerWidget {
  const CatalogueArtistScreen({
    super.key,
    required this.artistId,
    this.preloaded,
  });

  final String artistId;
  final CatalogueArtist? preloaded;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // A search hit already carries picture, fans and name: no extra request.
    final fetched =
        preloaded == null ? ref.watch(catalogueArtistProvider(artistId)) : null;
    final artist = preloaded ?? fetched?.value;
    if (artist == null) {
      return _Unavailable(
        loading: fetched?.isLoading ?? false,
        onRetry: () => ref.invalidate(catalogueArtistProvider(artistId)),
      );
    }

    final releasesKey = (artistId, artist.name);
    final top = ref.watch(catalogueArtistTopProvider(artistId));
    ref.watch(artistWarmupProvider(artistId));
    final releases = ref.watch(catalogueArtistReleasesProvider(releasesKey));
    final facade = ref.watch(playbackFacadeProvider);
    final snapshot = ref.watch(playbackSnapshotProvider).value;
    final sourceId = 'catalogue-artist:$artistId';
    final isCurrent = snapshot?.sourceId == sourceId;
    final isPlaying = isCurrent && (snapshot?.isPlaying ?? false);
    final topList = top.value ?? const <CatalogueTrack>[];
    final instant = ref.watch(instantAvailableProvider);
    final portal = ref.watch(requestPortalOfferedProvider);
    final encore = ref.watch(onEncoreServerProvider).value ?? false;
    final firstPlayable =
        topList.indexWhere((t) => instant || t.previewUrl != null);

    return CollectionScaffold(
      title: artist.name,
      circularArt: true,
      art: CoverArt(
        imageUrl: artist.imageUrl,
        circular: true,
        fallbackLabel: artist.name,
      ),
      subtitleLines: [
        if (artist.fans != null && artist.fans! > 0)
          Text(formatFans(artist.fans!), style: context.text.bodyMedium),
      ],
      actions: Row(
        children: [
          if (instant)
            CatalogueMoreMenu(artist: artist.name)
          else if (portal)
            RequestChip(artist: artist.name),
          const Spacer(),
          PlayButton(
            isPlaying: isPlaying,
            size: 56,
            onPressed: firstPlayable < 0
                ? null
                : () => isCurrent
                    ? facade.togglePlayPause()
                    : unawaited(tapPlayRun(ref, topList,
                        startIndex: firstPlayable,
                        sourceName: artist.name,
                        sourceId: sourceId)),
          ),
        ],
      ),
      slivers: [
        _explain(
          context,
          instant
              ? (encore
                  ? kEncorePlayLine
                  : 'Tap a song to play it. It is added to your library '
                      'first, which takes a few seconds.')
              : 'Previews are 30 seconds. Request an artist and their music '
                  'is added to your library in full.',
          instant: instant,
        ),
        ArtistPopularSection(artist: artist, sourceId: sourceId),
        releases.when(
          loading: loadingSliver,
          error: (_, __) => const SliverToBoxAdapter(child: SizedBox.shrink()),
          data: (items) => ArtistReleaseSections(releases: items),
        ),
      ],
    );
  }
}
