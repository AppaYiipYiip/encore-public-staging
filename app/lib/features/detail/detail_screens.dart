import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/navigation.dart';
import '../../app/providers.dart';
import '../../core/perf.dart';
import '../../data/db/app_database.dart';
import '../../data/encore/encore_models.dart' show EncoreUnavailable;
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
import '../common/open_artist.dart';
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
import '../instant/song_marks.dart';
import '../instant/tap_play.dart';
import '../providers.dart';
import 'album_gap.dart';
import 'hero_header.dart';
import 'list_finder.dart';
import 'playlist_find.dart';

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
        ShufflePlayButtons(
          isPlaying: isPlaying,
          shuffleOn: shuffle,
          // Through the one place library rows are played from: a song the server already knows it cannot get is left out (N-13, B-128).
          onShuffle: tracks.isEmpty
              ? null
              : () => playLibraryTracks(ref, tracks,
                  sourceName: sourceName,
                  sourceId: sourceId,
                  shuffle: true,
                  skipUnavailable: true),
          onPlay: tracks.isEmpty
              ? null
              : () => isCurrent
                  ? facade.togglePlayPause()
                  : playLibraryTracks(ref, tracks,
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
    this.only,
  });

  /// The whole list: what a tap queues, whatever is shown.
  final List<TrackRow> tracks;
  final String sourceName;
  final String sourceId;
  final bool numbered;
  final bool showAlbum;

  /// The places in [tracks] that are shown, in the order shown ("Find in playlist" of a playlist and of Liked Songs, N-25 and N-32); null shows all of [tracks]. A row
  /// is still its place in the whole list: it plays from there with the whole list queued, and removes its own entry.
  final List<int>? only;

  /// The playlist this list shows, when the user may remove entries from it;
  /// [positions] are the entries' positions, parallel to [tracks].
  final PlaylistRow? editablePlaylist;
  final List<int>? positions;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final snapshot = ref.watch(playbackSnapshotProvider).value;
    final downloaded = ref.watch(downloadedIdsProvider).value ?? const {};
    final playable = ref.watch(playabilityProvider);

    // The songs the server already knows it cannot get are marked (N-13, B-128; drawn in S-15 and S-17): the rows with no file that are not on the phone
    // are asked about by ref id, one question for each stretch of [kSongMarksPerAsk] rows **that is built**, so a playlist of two thousand songs the
    // server never fetched is not twenty questions when it opens, only the ones for the rows a person scrolls to; a list whose songs all have files
    // asks nothing.
    final stretches = <int, TrackList>{};
    TrackList stretchOf(int place) =>
        stretches.putIfAbsent(place ~/ kSongMarksPerAsk, () {
          final from = (place ~/ kSongMarksPerAsk) * kSongMarksPerAsk;
          return TrackList(const [], refIds: [
            for (final t in tracks.skip(from).take(kSongMarksPerAsk))
              if (t.mayBeUnavailable && !downloaded.contains(t.id)) t.id,
          ]);
        });

    final shown = only;
    return SliverList.builder(
      itemCount: shown?.length ?? tracks.length,
      itemBuilder: (context, row) {
        final i = shown == null ? row : shown[row];
        final t = tracks[i];
        final current = snapshot?.track?.id == t.id;
        return _MarkedRow(
          track: t,
          stretch: stretchOf(i),
          builder: (mark) => TrackSwipe(
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
              mark: mark,
              onTap: () => playLibraryTracks(ref, tracks,
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
          ),
        );
      },
    );
  }
}

/// One row of a list of the library: it asks the server about its stretch of rows when it is built (`songMarksCheckProvider`, once per stretch,
/// however many of its rows are built) and draws with the mark the server's answer gives it, or none.
class _MarkedRow extends ConsumerWidget {
  const _MarkedRow({
    required this.track,
    required this.stretch,
    required this.builder,
  });

  final TrackRow track;
  final TrackList stretch;
  final Widget Function(EncoreUnavailable? mark) builder;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (!stretch.isEmpty) ref.watch(songMarksCheckProvider(stretch));
    return builder(ref.watch(libraryMarkProvider(track.markKey)));
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
    final albumAsync = ref.watch(albumProvider(albumId));
    final album = albumAsync.value;
    final tracks = ref.watch(albumTracksProvider(albumId)).value ?? const [];
    // What the catalogue says the album still lacks (B39): looked up in the
    // background, never waited for.
    final gap = ref.watch(albumGapProvider(albumId)).value;
    if (album == null) {
      return DetailPlaceholder(what: 'album', missing: albumAsync.hasValue);
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
  final snapshot = ref.watch(playbackSnapshotProvider).value;
  final sourceId = 'album-missing:${album.id}';
  // The songs the server already knows it cannot get are marked (N-13): one question for the whole list.
  ref.watch(songMarksCheckProvider(TrackList(gap.missing)));
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
        return CatalogueTrackTile(
          track: t,
          number: t.trackNumber ?? i + 1,
          isCurrent: current,
          isPlaying: current && (snapshot?.isPlaying ?? false),
          status: status,
          mark: ref.watch(songMarkProvider(t.id)),
          onTap: () => unawaited(tapPlayRun(ref, gap.missing,
              startIndex: i,
              sourceName: albumDisplayName(album.name),
              sourceId: sourceId)),
        );
      },
    ),
  ];
}

// ---------------------------------------------------------------- playlist

class PlaylistScreen extends ConsumerStatefulWidget {
  const PlaylistScreen({super.key, required this.playlistId});

  final String playlistId;

  @override
  ConsumerState<PlaylistScreen> createState() => _PlaylistScreenState();
}

class _PlaylistScreenState extends ConsumerState<PlaylistScreen> {
  // "Find in playlist" (N-25, docs/design S-17): whether the finding page is open, the words typed and the positions the last answer named;
  // the same state as Liked Songs' finding keeps (N-32), so it lives in one place.
  late final _finder = ListFinder<List<int>>(onChanged: () {
    if (mounted) setState(() {});
  });

  @override
  void didUpdateWidget(PlaylistScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    // The page now shows another playlist: what was typed was about the first.
    if (oldWidget.playlistId != widget.playlistId) _finder.reset();
  }

  @override
  void dispose() {
    _finder.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final playlistId = widget.playlistId;
    final playlistAsync = ref.watch(playlistProvider(playlistId));
    final playlist = playlistAsync.value;
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
      return DetailPlaceholder(
          what: 'playlist', missing: playlistAsync.hasValue);
    }
    PerfMonitor.instance.pageShell('playlist');
    if (entries.isNotEmpty) {
      PerfMonitor.instance
          .pageFull('playlist', detail: '${entries.length} songs');
    }
    if (_finder.open && entries.isNotEmpty) {
      return _findingPage(playlist, entries, editable);
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
      // The finding page replaces this one for a moment: the page comes back where it was.
      scrollKey: PageStorageKey<String>('playlist-${playlist.id}'),
      find: entries.isEmpty
          ? null
          : PlaylistFindField(onTap: _finder.openFinding),
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
            showNames: true,
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

  /// The page while the person is finding a song: the field at the top, and under it the playlist's songs, all of them or the ones the
  /// words match. A row is still its place in the whole playlist: a tap queues the whole playlist from there (the filter narrows what is
  /// shown, not what plays), by the entry's place and not by the song, so a song that is in the playlist twice plays from the right one.
  Widget _findingPage(
    PlaylistRow playlist,
    List<({int position, TrackRow track})> entries,
    PlaylistRow? editable,
  ) {
    final query = _finder.query;
    final held = query.isEmpty
        ? null
        : _finder.hold(ref.watch(
            playlistFindProvider((playlistId: playlist.id, query: query))));
    // Positions to places in the list, now: an edit can land between two answers.
    List<int>? shown;
    if (held != null) {
      final placeOf = {for (final (i, e) in entries.indexed) e.position: i};
      shown = [
        for (final position in held)
          if (placeOf[position] != null) placeOf[position]!,
      ];
    }

    return _FindingPage(
      finder: _finder,
      noResultsFor: shown != null && shown.isEmpty ? query : null,
      list: _TrackList(
        tracks: [for (final e in entries) e.track],
        sourceName: playlist.name,
        sourceId: 'playlist:${playlist.id}',
        showAlbum: true,
        editablePlaylist: editable,
        positions: [for (final e in entries) e.position],
        only: shown,
      ),
    );
  }
}

/// The page while the person finds a song inside a list (S-15 and S-17): the field at the top of the page, built like Search's own, and under it
/// [list] (a sliver: the whole list, or the songs the words match) or, when nothing matches, the words saying so. The arrow and Back close it.
class _FindingPage extends StatelessWidget {
  const _FindingPage({
    required this.finder,
    required this.noResultsFor,
    required this.list,
  });

  final ListFinder<Object> finder;

  /// The words typed when nothing matches them; null when something does (or nothing is typed).
  final String? noResultsFor;
  final Widget list;

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) finder.close();
      },
      child: Scaffold(
        body: SafeArea(
          bottom: false,
          child: Column(
            children: [
              PlaylistFindBar(
                controller: finder.controller,
                focusNode: finder.focus,
                onChanged: finder.typed,
                onClear: finder.clear,
                onClose: finder.close,
              ),
              const SizedBox(height: Space.sm),
              Expanded(
                child: CustomScrollView(
                  // The keyboard goes when the person scrolls, so the rest of the list can be read.
                  keyboardDismissBehavior:
                      ScrollViewKeyboardDismissBehavior.onDrag,
                  slivers: [
                    if (noResultsFor != null)
                      SliverFillRemaining(
                        hasScrollBody: false,
                        child: EmptyState(
                          icon: Icons.search_off_rounded,
                          title:
                              'No results for "$noResultsFor" in this playlist',
                          message: 'Check the spelling, or try fewer words.',
                        ),
                      )
                    else
                      list,
                    const SliverToBoxAdapter(
                        child: SizedBox(height: Space.xxl)),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

// ------------------------------------------------------------------ artist

class ArtistScreen extends ConsumerWidget {
  const ArtistScreen({super.key, required this.artistId});

  final String artistId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final artistAsync = ref.watch(artistProvider(artistId));
    final artist = artistAsync.value;
    final albums = ref.watch(artistAlbumsProvider(artistId)).value ?? const [];
    // Every song of the artist the library holds: what Play and Shuffle play (N-24).
    final tracks = ref.watch(artistTracksProvider(artistId)).value ?? const [];
    if (artist == null) {
      // Looked at and not there: the artist of a song tagged "A, B" is an artist of that whole name that the phone never receives; its page is
      // the page of the artist of its albums (or, failing that, of the artist of that name), not a spinner for ever.
      return artistAsync.hasValue
          ? _ArtistNotOnThisPhone(artistId: artistId)
          : const DetailPlaceholder(what: 'artist');
    }
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
    PerfMonitor.instance.pageShell('artist');
    if (releases != null) {
      PerfMonitor.instance
          .pageFull('artist', detail: '${releases.length} releases');
    }
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
      // Play and Shuffle are every song of the artist that the server holds, as an album's are its songs (N-24). What the catalogue lists
      // beyond that (the Popular rows, releases the server does not have) is one tap away on the page, where a tap fetches the song first.
      actions: _ActionRow(
        tracks: tracks,
        sourceName: artist.name,
        sourceId: 'artist:${artist.id}',
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

/// The page of an artist the phone has no row for: it finds the artist that stands for it and opens that page in its place, or says the artist is
/// not here (with the way back).
class _ArtistNotOnThisPhone extends ConsumerStatefulWidget {
  const _ArtistNotOnThisPhone({required this.artistId});

  final String artistId;

  @override
  ConsumerState<_ArtistNotOnThisPhone> createState() =>
      _ArtistNotOnThisPhoneState();
}

class _ArtistNotOnThisPhoneState extends ConsumerState<_ArtistNotOnThisPhone> {
  bool _missing = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => unawaited(_resolve()));
  }

  Future<void> _resolve() async {
    final repo = ref.read(libraryRepositoryProvider);
    final standIn = await repo?.artistStandIn(widget.artistId);
    if (!mounted) return;
    if (standIn != null) {
      Nav.artist(context, standIn, replace: true);
      return;
    }
    // No album artist to stand in: the name the songs carry, whole and exact, in the library and then in the public catalogue.
    final name = await repo?.artistNameOf(widget.artistId);
    if (!mounted) return;
    if (name != null &&
        await openArtistByName(context, ref, name,
            replace: true, quiet: true)) {
      return;
    }
    if (mounted) setState(() => _missing = true);
  }

  @override
  Widget build(BuildContext context) =>
      DetailPlaceholder(what: 'artist', missing: _missing);
}

// ------------------------------------------------------------------- liked

class LikedScreen extends ConsumerStatefulWidget {
  const LikedScreen({super.key});

  @override
  ConsumerState<LikedScreen> createState() => _LikedScreenState();
}

class _LikedScreenState extends ConsumerState<LikedScreen> {
  // "Find in playlist" on Liked Songs (N-32, docs/design S-15): the same finding as a playlist's (S-17), the same state in `ListFinder`, the
  // same finding page; only its answer differs (the ids of the liked songs that match).
  late final _finder = ListFinder<List<String>>(onChanged: () {
    if (mounted) setState(() {});
  });

  @override
  void dispose() {
    _finder.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final tracks = ref.watch(likedTracksProvider).value ?? const [];
    if (_finder.open && tracks.isNotEmpty) return _findingPage(tracks);
    final c = context.colors;
    return CollectionScaffold(
      title: 'Liked Songs',
      tint: c.accent.withValues(alpha: 0.55),
      // The finding page replaces this one for a moment: the page comes back where it was.
      scrollKey: const PageStorageKey<String>('liked'),
      find:
          tracks.isEmpty ? null : PlaylistFindField(onTap: _finder.openFinding),
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

  /// The page while the person is finding a song among the ones they liked: the field at the top, and under it the liked songs, all of them
  /// or the ones the words match, in the order of Liked Songs. A row is still its place in the whole of Liked Songs: a tap queues all of
  /// them from there (the filter narrows what is shown, not what plays), as in a playlist.
  Widget _findingPage(List<TrackRow> tracks) {
    final query = _finder.query;
    final held = query.isEmpty
        ? null
        : _finder.hold(ref.watch(likedFindProvider(query)));
    // Ids to places in the list as it is now: a like or an unlike can land between two answers, and the page's own list is what is shown.
    List<int>? shown;
    if (held != null) {
      final ids = held.toSet();
      shown = [
        for (final (i, t) in tracks.indexed)
          if (ids.contains(t.id)) i,
      ];
    }

    return _FindingPage(
      finder: _finder,
      noResultsFor: shown != null && shown.isEmpty ? query : null,
      list: _TrackList(
        tracks: tracks,
        sourceName: 'Liked Songs',
        sourceId: 'liked',
        showAlbum: true,
        only: shown,
      ),
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
