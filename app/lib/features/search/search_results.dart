import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/navigation.dart';
import '../../data/catalogue/catalogue_models.dart';
import '../../data/db/app_database.dart' show TrackRow;
import '../../data/repos/downloads_repository.dart' show PinTargetType;
import '../../design/tokens.dart';
import '../catalogue/catalogue_widgets.dart' show formatFans;
import '../common/away_words.dart';
import '../common/cover_art.dart';
import '../common/format.dart';
import '../common/playability.dart';
import '../common/track_menu.dart';
import '../common/track_swipe.dart';
import '../common/widgets.dart';
import '../instant/instant_controller.dart';
import '../instant/song_marks.dart';
import '../instant/tap_play.dart';
import '../providers.dart';
import '../requests/request_providers.dart';
import '../requests/request_ui.dart';
import 'search_assembly.dart';

/// What a typed search shows (P1-07): the **Top result**, then songs, artists and albums, each list ranked, the library's and the
/// catalogue's mixed and looking the same. Whether the library has a song is never a header or a sentence; it is only a tie-break.
///
/// The library answers at once; the catalogue joins when it arrives, and the order is worked out again with both. While the server is away
/// (P1-16, S-12 offline) the catalogue is not asked and not waited for: the library's rows are the page, what is not on the phone is grey,
/// and one quiet last line says what more cannot be done, in the words of its cause.
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
    final cause = ref.watch(awayCauseProvider);

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
    // The songs the server already knows it cannot get are marked (N-13): one question for the whole list, once the rows are drawn. A catalogue song has no
    // ref on the phone, so it is described; a row of the phone's own library (the song somebody tapped is one from then on) is asked about by its ref id,
    // the exact identity (B-128). A row with a file or on the phone is never asked about: it plays.
    final downloaded = ref.watch(downloadedIdsProvider).value ?? const {};
    final songHits = [
      if (found.top is SongHit) found.top! as SongHit,
      ...found.songs,
    ];
    ref.watch(songMarksCheckProvider(TrackList(
      [
        for (final track in {
          for (final hit in songHits)
            if (hit.catalogue != null) hit.catalogue!.id: hit.catalogue!,
        }.values)
          track,
      ],
      refIds: [
        for (final hit in songHits)
          if (hit.local != null &&
              hit.local!.mayBeUnavailable &&
              !downloaded.contains(hit.local!.id))
            hit.local!.id,
      ],
    )));

    if (found.isEmpty) {
      // Offline the question is not "is the catalogue slow" but "what cannot be done": never a spinner for a line that is not there, and
      // never "No results" for what the phone simply cannot look for.
      if (cause != null) {
        return EmptyState(
          icon: Icons.search_off_rounded,
          title: nothingInYourMusic(query),
          message: onlyYourMusicSearched(cause),
        );
      }
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
        if (cause != null) _MoreNeed(cause: cause),
      ],
    );
  }

  void _opened() => widget.onOpen(widget.query);
}

/// The one quiet last line of the results while the server is away (S-12 offline): it takes no room above the list, has no cross, never
/// repeats the strip, and goes by itself.
class _MoreNeed extends StatelessWidget {
  const _MoreNeed({required this.cause});

  final AwayCause cause;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(Space.gutter, 14, Space.gutter, 10),
      child: Text(
        moreResultsNeed(cause),
        style:
            context.text.bodySmall?.copyWith(color: context.colors.onBgMuted),
      ),
    );
  }
}

// ----------------------------------------------------------------- the top

class _TopResult extends ConsumerWidget {
  const _TopResult({required this.hit, required this.onOpen});

  final SearchHit hit;
  final VoidCallback onOpen;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final h = hit;
    // A song of the library has what every song has: the swipes and the "..." menu (N-21), from the one place that gives them.
    final local = h is SongHit ? h.local : null;
    return Padding(
      padding: const EdgeInsets.fromLTRB(
          Space.gutter, Space.sm, Space.gutter, Space.sm),
      // The swipe's colour shows only inside the card's rounded corners.
      child: ClipRRect(
        borderRadius: BorderRadius.circular(Radii.card),
        child: local == null
            ? _card(context, ref, onMore: null)
            : _SongActions(
                track: local,
                index: -1,
                builder: (onMore) => _card(context, ref, onMore: onMore),
              ),
      ),
    );
  }

  /// [onMore] is the song's menu, also opened by a long press (D-26); an artist, an album or a song of the catalogue has none.
  Widget _card(BuildContext context, WidgetRef ref,
      {required VoidCallback? onMore}) {
    final c = context.colors;
    final playable = ref.watch(playabilityProvider);
    final h = hit;
    // A song of the library that is not on the phone cannot be played without a connection.
    final unavailable =
        h is SongHit && h.local != null && !playable(h.local!.id);
    // A song the server already knows it cannot get (N-13): the card greys, its Play circle is a quiet one, and a tap says why. A song of the library is
    // marked by its ref id, a catalogue song by its catalogue id (B-128: the song somebody tapped is both, and the library row is the one that is shown).
    final mark = h is! SongHit
        ? null
        : h.local != null
            ? ref.watch(libraryMarkProvider(h.local!.markKey))
            : h.catalogue != null
                ? ref.watch(songMarkProvider(h.catalogue!.id))
                : null;
    // An album of the library with nothing on the phone says so while the server is away, as its row does (S-12, S-14 offline).
    final albumGone = h is AlbumHit &&
        h.local != null &&
        ref.watch(notDownloadedNowProvider((PinTargetType.album, h.local!.id)));
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
    return Semantics(
      button: true,
      label: 'Top result: $kind, $title${artist == null ? '' : ', $artist'}'
          '${mark == null ? '' : ', $kNotAvailableWords'}',
      excludeSemantics: true,
      child: Material(
        color: c.surfaceHigh,
        child: InkWell(
          key: const Key('top-result'),
          onTap: () => _open(context, ref, hit, onOpen),
          onLongPress: onMore,
          child: Padding(
            padding: const EdgeInsets.all(Space.md),
            child: Row(
              children: [
                SizedBox.square(
                    dimension: 92,
                    child:
                        mark == null ? art : Opacity(opacity: .6, child: art)),
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
                          style: context.text.titleLarge?.copyWith(
                              fontWeight: FontWeight.w800,
                              color: mark == null ? null : c.onBgMuted)),
                      Text(
                        [
                          kind,
                          if (albumGone)
                            kNotDownloadedWords
                          else if (artist != null)
                            artist,
                        ].join(' • '),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: context.text.bodyMedium
                            ?.copyWith(color: c.onBgMuted),
                      ),
                      if (mark != null)
                        Text(kNotAvailableWords,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: context.text.bodyMedium?.copyWith(
                                color: c.onBgMuted,
                                fontWeight: FontWeight.w600)),
                    ],
                  ),
                ),
                if (hit is SongHit)
                  Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      if (onMore != null) TrackMoreButton(onPressed: onMore),
                      mark != null
                          ? Icon(Icons.remove_circle_outline_rounded,
                              size: 44, color: c.onBgFaint)
                          : unavailable
                              ? Icon(Icons.cloud_off_rounded,
                                  size: 28, color: c.onBgFaint)
                              : Icon(Icons.play_circle_fill_rounded,
                                  size: 44, color: c.accent),
                    ],
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// What a song of the library can do besides playing, wherever the results draw it (a row, the Top result): swipe right adds it to the
/// queue, swipe left likes it ([TrackSwipe]), and its "..." menu ([showTrackMenu]) opens from the button or a long press. [builder] draws
/// the song and puts the button where it belongs.
class _SongActions extends StatelessWidget {
  const _SongActions({
    required this.track,
    required this.index,
    required this.builder,
  });

  final TrackRow track;
  final int index;
  final Widget Function(VoidCallback onMore) builder;

  @override
  Widget build(BuildContext context) {
    return TrackSwipe(
      track: track,
      index: index,
      child: builder(() => showTrackMenu(context, track)),
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
  final local = hit.local;
  if (local != null) {
    // The library's songs of this list play on from the one that was tapped.
    final owned = [
      for (final s in songs)
        if (s.local != null) s.local!,
    ];
    final tracks = owned.isEmpty ? [local] : owned;
    // Through the one place library rows are played from: a song the server cannot get is never tried (B-128).
    unawaited(playLibraryTracks(ref, tracks,
        startIndex: math.max(0, tracks.indexWhere((t) => t.id == local.id)),
        sourceName: 'Search'));
    return;
  }
  final track = hit.catalogue!;
  // The full song; the tap waits for the backend and, if there is none, says so (D-24, D-64).
  unawaited(tapPlayOne(ref, track));
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
      return _SongActions(
        track: local,
        index: index,
        builder: (onMore) => TrackTile(
          track: local,
          showAlbum: true,
          available: playable(local.id),
          mark: ref.watch(libraryMarkProvider(local.markKey)),
          isCurrent: playing?.track?.id == local.id,
          isPlaying: playing?.isPlaying ?? false,
          onTap: () {
            onOpen();
            _play(ref, hit, songs: songs);
          },
          onMore: onMore,
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
    final portal = ref.watch(requestPortalOfferedProvider);
    final status = ref.watch(instantStatusProvider(track.id));
    // The server already knows it cannot get this song (N-13): grey, in the words of the drawing; a tap says why.
    final mark = ref.watch(songMarkProvider(track.id));
    final isThis = playing?.track?.id == track.id ||
        (status?.track != null && playing?.track?.id == status!.track!.id);
    final working = status?.isWorking ?? false;
    final failed = status?.isFailed ?? false;

    final subtitle = working
        ? status!.label
        : failed
            ? (status!.message ?? 'Could not get it')
            : mark != null
                ? kNotAvailableWords
                : [
                    track.artistName,
                    if (track.albumTitle != null) track.albumTitle!,
                  ].join(' • ');

    return InkWell(
      onTap: () {
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
              child: Opacity(
                opacity: mark == null ? 1 : .6,
                child: CoverArt(
                  imageUrl: track.coverUrl,
                  fallbackLabel: track.albumTitle ?? track.title,
                ),
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
                      color: mark != null
                          ? c.onBgMuted
                          : isThis
                              ? c.accent
                              : c.onBg,
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
            else if (portal)
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
          : (catalogue != null && ref.watch(requestPortalOfferedProvider)
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
    // While the server is away an album with nothing on the phone is grey and says so in words (S-12 and S-14 offline), as in the Library.
    final gone = local != null &&
        ref.watch(notDownloadedNowProvider((PinTargetType.album, local.id)));
    final parts = [
      if (hit.artist != null) hit.artist!,
      if ((local?.year ?? catalogue?.year) != null)
        '${local?.year ?? catalogue?.year}',
      if ((local?.songCount ?? catalogue?.trackCount ?? 0) > 0)
        plural((local?.songCount ?? catalogue?.trackCount)!, 'song'),
    ];
    final row = _Row(
      leading: CoverArt(
        coverArtId: local?.coverArt,
        imageUrl: catalogue?.coverUrl,
        fallbackLabel: hit.title,
        fallbackArtist: local == null ? null : hit.artist,
        radius: Radii.art,
      ),
      title: hit.title,
      subtitle: gone ? kNotDownloadedWords : parts.join(' - '),
      onTap: () => _open(context, ref, hit, onOpen),
      // With the instant-play service a row is just a row; asking for the original files is on the release page (ADR-067).
      trailing: catalogue != null && ref.watch(requestPortalOfferedProvider)
          ? RequestChip(artist: catalogue.artistName, album: catalogue.title)
          : const SizedBox.shrink(),
    );
    return gone ? Opacity(opacity: 0.45, child: row) : row;
  }
}
