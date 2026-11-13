import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/connection.dart';
import '../../app/navigation.dart';
import '../../app/providers.dart';
import '../../app/share_out.dart';
import '../../data/db/app_database.dart';
import '../../design/tokens.dart';
import '../../domain/artwork_color.dart';
import '../../domain/lyrics.dart';
import '../common/artist_line.dart';
import '../common/artwork_color.dart';
import '../common/connection_banner.dart';
import '../common/cover_art.dart';
import '../common/open_artist.dart';
import '../common/track_menu.dart';
import '../common/widgets.dart';
import '../providers.dart';
import 'lyrics_screen.dart';
import 'output_row.dart';
import 'pending_likes.dart';
import 'playback_facade.dart';
import 'queue_sheet.dart';
import 'scrubber.dart';
import 'share_text.dart';
import 'sleep_timer_sheet.dart';
import 'streamed_song.dart';

/// Full-screen player (docs/06-ux-spec.md 4.6): artwork, like, scrubber,
/// transport, quality chip, lyrics preview.
class NowPlayingScreen extends ConsumerWidget {
  const NowPlayingScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final snapshot = ref.watch(playbackSnapshotProvider).value;
    final track = snapshot?.track;
    final c = context.colors;

    if (track == null) {
      return Scaffold(
        appBar: AppBar(
          leading: IconButton(
            tooltip: 'Close',
            icon: const Icon(Icons.keyboard_arrow_down_rounded),
            onPressed: () => context.pop(),
          ),
        ),
        body: const EmptyState(
          icon: Icons.music_note_rounded,
          title: 'Nothing is playing',
          message: 'Pick something from Home, Search or your Library.',
        ),
      );
    }

    final swatch = ref
        .watch(artworkSwatchProvider(
            (albumId: track.albumId, coverArtId: track.coverArt)))
        .value;
    final tint = swatch != null
        ? backdropFor(swatch)
        : tintFor(track.album ?? track.title);
    final facade = ref.watch(playbackFacadeProvider);
    // What like / playlists / "go to album" act on. A song the service is
    // still putting into the library has none for a few seconds (ADR-066).
    final libraryRow = ref.watch(playingLibraryRowProvider(track)).value;
    final fromService = ref.watch(isServiceSongProvider(track));
    final waiting = fromService && libraryRow == null;
    final serverAway = ref.watch(connectionProblemProvider).serverIsAway;

    return GestureDetector(
      onVerticalDragEnd: (d) {
        if ((d.primaryVelocity ?? 0) > 500) context.pop();
      },
      child: Scaffold(
        body: AnimatedContainer(
          duration: Motion.colour,
          decoration: BoxDecoration(
            gradient: LinearGradient(
              begin: Alignment.topCenter,
              end: Alignment.bottomCenter,
              colors: [tint, c.bg],
              stops: const [0, 0.85],
            ),
          ),
          child: SafeArea(
            child: Column(
              children: [
                // The same thin strip as everywhere else (docs/31 CN-14): a song waiting for its server shows it here, at the top, because the
                // full player has no bottom bar to carry it.
                const ConnectionBanner(),
                Expanded(child: LayoutBuilder(
                  builder: (context, constraints) {
                    final compact = constraints.maxHeight < 640;
                    // Phones come in every shape (P1-22, D-63): the page is laid
                    // out from the room it is given, never from a fixed size.
                    // Turned on its side, or opened up (a foldable), the cover
                    // goes beside the controls instead of above them.
                    //
                    // The test is "is there room for a cover above the
                    // controls", not "is it wider than tall": a foldable
                    // opened up is nearly square (920 x 1104) and still has no
                    // room for a cover of its full width above the controls.
                    // A phone held upright is narrower than 560 and never goes
                    // beside.
                    final coverSide = constraints.maxWidth - 2 * Space.xl;
                    final roomAboveControls = constraints.maxHeight - 56 - 360;
                    final wide = constraints.maxWidth >= 560 &&
                        roomAboveControls < coverSide * 0.8;
                    final topBar = _TopBar(
                      source: snapshot!.sourceName,
                      // A song on its way into the library has a library entry
                      // to act on in a moment.
                      row: libraryRow,
                      waiting: waiting,
                    );
                    final artwork = _Artwork(track: track, facade: facade);
                    final controls = <Widget>[
                      _TitleRow(
                        track: track,
                        row: libraryRow,
                        waiting: waiting,
                      ),
                      const SizedBox(height: Space.sm),
                      Scrubber(waiting: serverAway && !snapshot.isPlaying),
                      const SizedBox(height: Space.xs),
                      _Transport(snapshot: snapshot, facade: facade),
                      const SizedBox(height: Space.md),
                      _BottomRow(track: track),
                      const SizedBox(height: Space.lg),
                      _LyricsPreview(track: track),
                      const SizedBox(height: Space.xl),
                    ];
                    const side = EdgeInsets.symmetric(horizontal: Space.xl);
                    if (wide) {
                      return Padding(
                        padding: side,
                        child: Column(
                          children: [
                            topBar,
                            Expanded(
                              child: Row(
                                children: [
                                  // The cover takes the height it can get
                                  // (an AspectRatio shrinks to fit).
                                  Expanded(child: Center(child: artwork)),
                                  const SizedBox(width: Space.xl),
                                  Expanded(
                                    child: Center(
                                      child: SingleChildScrollView(
                                        physics: const ClampingScrollPhysics(),
                                        child: Column(
                                          mainAxisSize: MainAxisSize.min,
                                          children: controls,
                                        ),
                                      ),
                                    ),
                                  ),
                                ],
                              ),
                            ),
                          ],
                        ),
                      );
                    }
                    // Upright: the page fills the screen and scrolls only when
                    // it is too tall. The spare height goes BETWEEN the sections
                    // (above the cover and below it), so the title, the
                    // controls and the bottom row stay together at the bottom
                    // of a tall phone, as on Spotify, and never leave a dead
                    // area under the controls (the owner, 6 Nov 2026).
                    return SingleChildScrollView(
                      physics: const ClampingScrollPhysics(),
                      child: ConstrainedBox(
                        constraints:
                            BoxConstraints(minHeight: constraints.maxHeight),
                        // As tall as the screen when the content is shorter
                        // (so the spacers have room to spread), and as tall as
                        // the content when it is longer (the page scrolls).
                        child: IntrinsicHeight(
                          child: Padding(
                            padding: side,
                            child: Column(
                              children: [
                                topBar,
                                SizedBox(height: compact ? Space.sm : Space.xl),
                                const Spacer(),
                                artwork,
                                SizedBox(height: compact ? Space.md : Space.xl),
                                const Spacer(),
                                ...controls,
                              ],
                            ),
                          ),
                        ),
                      ),
                    );
                  },
                )),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// Shown when a person acts on a song the service is still putting into the
/// library: it can be liked and added to playlists a moment later.
const String kWaitingForLibrary = 'Still being added to your library - you '
    'can like it and add it to a playlist in a moment.';

class _TopBar extends ConsumerWidget {
  const _TopBar({this.source, this.row, this.waiting = false});

  final String? source;

  /// The library track the menu acts on; `null` hides the menu (unless the
  /// song is [waiting] to arrive).
  final TrackRow? row;
  final bool waiting;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Row(
      children: [
        IconButton(
          tooltip: 'Close player',
          icon: const Icon(Icons.keyboard_arrow_down_rounded, size: 32),
          onPressed: () => context.pop(),
        ),
        Expanded(
          child: Column(
            children: [
              Text('PLAYING FROM',
                  style: context.text.labelSmall
                      ?.copyWith(color: context.colors.onBgMuted)),
              Text(
                source ?? 'Your library',
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: context.text.titleSmall,
              ),
            ],
          ),
        ),
        IconButton(
          tooltip: 'More options',
          icon: const Icon(Icons.more_horiz_rounded),
          onPressed: () async {
            final extra = _playerActions(context, ref);
            final found = row;
            if (found == null) {
              // A song still being added: no library row to act on, but the player's own options are there.
              await showActionsMenu(context, extra,
                  note: waiting ? kWaitingForLibrary : null);
              return;
            }
            await showTrackMenu(context, found, extraActions: extra);
          },
        ),
      ],
    );
  }
}

class _Artwork extends StatelessWidget {
  const _Artwork({required this.track, required this.facade});

  final NowPlayingTrack track;
  final PlaybackFacade facade;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onHorizontalDragEnd: (d) {
        final v = d.primaryVelocity ?? 0;
        if (v < -300) {
          HapticFeedback.lightImpact();
          facade.skipNext();
        } else if (v > 300) {
          HapticFeedback.lightImpact();
          facade.skipPrevious();
        }
      },
      child: AspectRatio(
        aspectRatio: 1,
        // No blur shadow: costly to rasterise every frame, and Spotify-style
        // player art sits flat on the gradient.
        child: CoverArt(
          coverArtId: track.coverArt,
          imageUrl: track.imageUrl,
          fallbackArtist: track.album == null ? null : track.artist,
          fallbackLabel: track.album ?? track.title,
          radius: Radii.hero,
        ),
      ),
    );
  }
}

class _TitleRow extends ConsumerWidget {
  const _TitleRow({
    required this.track,
    required this.row,
    this.waiting = false,
  });

  final NowPlayingTrack track;

  /// The library copy, once there is one.
  final TrackRow? row;

  /// A song the service is still adding to the library.
  final bool waiting;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // A like waiting for its song to be listed counts as liked: the heart
    // answers the tap now, whatever the music server is doing.
    final waitingLike = ref.watch(
        pendingLikesProvider.select((s) => s.waiting.containsKey(track.id)));
    final liked = row?.starredAtMs != null || waitingLike;
    final session = ref.watch(sessionProvider).value;
    final c = context.colors;
    // The artists of the song, each on its own, when the phone knows them (a song by several artists): each name is a tap of its own.
    final artists = ref.watch(songArtistsProvider(track.id)).value ?? const [];

    return Row(
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                track.title,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: context.text.headlineSmall,
              ),
              if (artists.length > 1)
                ArtistLine(
                  names: artists,
                  style: context.text.bodyLarge?.copyWith(
                      color: c.onBgMuted, fontWeight: FontWeight.w400),
                  onTap: (name) => openArtistByName(context, ref, name,
                      beforeOpen: context.pop),
                )
              else
                InkWell(
                  // A library song opens its library artist; a song that only the
                  // catalogue knows (a song the service plays) opens the
                  // catalogue's page of the artist.
                  onTap: track.artistId != null
                      ? () {
                          context.pop();
                          Nav.artist(context, track.artistId!);
                        }
                      : track.catalogueArtistId != null
                          ? () {
                              context.pop();
                              Nav.catalogueArtist(
                                  context, track.catalogueArtistId!);
                            }
                          // A song with no id to open: the name is looked up, so
                          // every artist can be tapped.
                          : (track.artist ?? '').trim().isEmpty
                              ? null
                              : () => openArtistByName(
                                    context,
                                    ref,
                                    track.artist!,
                                    beforeOpen: context.pop,
                                  ),
                  child: Text(
                    track.artist ?? '',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: context.text.bodyLarge?.copyWith(
                        color: c.onBgMuted, fontWeight: FontWeight.w400),
                  ),
                ),
            ],
          ),
        ),
        IconButton(
          tooltip: liked ? 'Remove from Liked Songs' : 'Add to Liked Songs',
          iconSize: 28,
          icon: Icon(
            liked ? Icons.favorite_rounded : Icons.favorite_border_rounded,
            color: liked ? c.accent : c.onBg,
          ),
          onPressed: session == null
              ? null
              : () {
                  final target = row;
                  // Waiting to be delivered: a press takes it back.
                  if (waitingLike || (target == null && waiting)) {
                    HapticFeedback.mediumImpact();
                    ref.read(pendingLikesProvider.notifier).toggle(track);
                    return;
                  }
                  if (target == null) return;
                  HapticFeedback.mediumImpact();
                  session.mutations.setTrackStarred(target.id, !liked);
                },
        ),
      ],
    );
  }
}

class _Transport extends StatelessWidget {
  const _Transport({required this.snapshot, required this.facade});

  final PlaybackSnapshot snapshot;
  final PlaybackFacade facade;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final repeatIcon = snapshot.repeat == RepeatKind.one
        ? Icons.repeat_one_rounded
        : Icons.repeat_rounded;
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        IconButton(
          tooltip: snapshot.shuffle ? 'Shuffle on' : 'Shuffle off',
          iconSize: 26,
          icon: Icon(Icons.shuffle_rounded,
              color: snapshot.shuffle ? c.accent : c.onBg),
          onPressed: facade.toggleShuffle,
        ),
        IconButton(
          tooltip: 'Previous',
          iconSize: 44,
          icon: const Icon(Icons.skip_previous_rounded),
          // Always available: restarts the song, or goes to the previous one.
          onPressed: facade.skipPrevious,
        ),
        snapshot.isLoading
            ? const SizedBox.square(
                dimension: 72,
                child: Padding(
                  padding: EdgeInsets.all(22),
                  child: CircularProgressIndicator(strokeWidth: 3),
                ),
              )
            : Semantics(
                button: true,
                label: snapshot.isPlaying ? 'Pause' : 'Play',
                excludeSemantics: true,
                child: Material(
                  color: c.onBg,
                  shape: const CircleBorder(),
                  child: InkWell(
                    customBorder: const CircleBorder(),
                    onTap: () {
                      HapticFeedback.selectionClick();
                      facade.togglePlayPause();
                    },
                    child: SizedBox.square(
                      dimension: 72,
                      child: Icon(
                        snapshot.isPlaying
                            ? Icons.pause_rounded
                            : Icons.play_arrow_rounded,
                        size: 46,
                        color: c.bg,
                      ),
                    ),
                  ),
                ),
              ),
        IconButton(
          tooltip: 'Next',
          iconSize: 44,
          icon: const Icon(Icons.skip_next_rounded),
          onPressed: snapshot.hasNext ? facade.skipNext : null,
        ),
        IconButton(
          tooltip: switch (snapshot.repeat) {
            RepeatKind.off => 'Repeat off',
            RepeatKind.all => 'Repeat all',
            RepeatKind.one => 'Repeat one',
          },
          iconSize: 26,
          icon: Icon(repeatIcon,
              color: snapshot.repeat == RepeatKind.off ? c.onBg : c.accent),
          onPressed: facade.cycleRepeat,
        ),
      ],
    );
  }
}

/// Spotify's last row of the player (D-63, D-66): where the sound goes on the left (a tap opens Encore's own Devices sheet), Share and the queue on
/// the right. Everything else it used to carry (the speed, the sleep timer, private listening) is in the "..." menu, and the quality label is in the
/// track menu's header (docs/design/03 row 9).
class _BottomRow extends ConsumerWidget {
  const _BottomRow({required this.track});

  final NowPlayingTrack track;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Row(
      children: [
        const Expanded(
            child: Align(alignment: Alignment.centerLeft, child: OutputChip())),
        IconButton(
          tooltip: 'Share',
          icon: const Icon(Icons.ios_share_rounded),
          onPressed: () => unawaited(_share(context, ref, shareTextFor(track))),
        ),
        IconButton(
          tooltip: 'Queue',
          icon: const Icon(Icons.queue_music_rounded),
          onPressed: () => showQueueSheet(context),
        ),
      ],
    );
  }
}

/// Hands [text] to the phone's own share sheet; says so when there is none.
Future<void> _share(BuildContext context, WidgetRef ref, String text) async {
  final messenger = ScaffoldMessenger.maybeOf(context);
  final opened = await ref.read(shareOutProvider).text(text);
  if (opened || !context.mounted) return;
  messenger?.showSnackBar(
      const SnackBar(content: Text('This phone could not open sharing.')));
}

/// What the "..." menu of the player adds to a track's own menu.
List<MenuAction> _playerActions(BuildContext context, WidgetRef ref) {
  final sleep = ref.read(sleepTimerProvider).value;
  final sleeping = sleep != null && sleep.mode != SleepTimerMode.off;
  // D-23 (AUDIT F35): no "Playback speed" for music and no "Private listening" here (it stays in Settings > Privacy & your music).
  return [
    MenuAction(
      Icons.bedtime_outlined,
      sleeping ? 'Sleep timer (${sleepRemainingLabel(sleep)})' : 'Sleep timer',
      () => showSleepTimerSheet(context),
    ),
  ];
}

/// The height of the Lyrics card, the same in every state (P1-23, the owner, 7 Nov 2026: going from a song without lyrics to one with lyrics must not
/// make the screen jump). It peeks under the bottom row; on a short phone the page scrolls up to it.
const double kLyricsCardHeight = 188;

/// Spotify-style Lyrics card: a few lines around the current one; tap opens the full-screen lyrics. It is always there, in the same place and the same
/// size: the lyrics, "Looking for lyrics..." while they load, "No lyrics for this song" when there are none.
class _LyricsPreview extends ConsumerWidget {
  const _LyricsPreview({required this.track});

  final NowPlayingTrack track;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(currentLyricsProvider(track.id));
    final lyrics = async.value;
    final c = context.colors;
    final has = lyrics != null && !lyrics.isEmpty;

    var shown = const <LyricLine>[];
    if (has) {
      final active = lyrics.synced
          ? ref.watch(playbackPositionProvider
              .select((p) => lyrics.activeIndex(p.value?.inMilliseconds ?? 0)))
          : -1;
      final start = lyrics.synced ? (active < 0 ? 0 : active) : 0;
      shown =
          lyrics.lines.skip(start).where((l) => !l.isBlank).take(4).toList();
    }

    final Widget body;
    if (has) {
      body = Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (var i = 0; i < shown.length; i++)
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Text(
                shown[i].text,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: context.text.titleMedium?.copyWith(
                  fontWeight: FontWeight.w800,
                  color: i == 0 && lyrics.synced
                      ? c.onBg
                      : c.onBg.withValues(alpha: 0.65),
                ),
              ),
            ),
        ],
      );
    } else {
      body = Text(
        async.isLoading ? 'Looking for lyrics...' : 'No lyrics for this song',
        style: context.text.titleMedium?.copyWith(color: c.onBgMuted),
      );
    }

    return Semantics(
      button: has,
      label: has ? 'Lyrics preview. Open full screen lyrics' : 'Lyrics',
      child: Material(
        color: c.onBg.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(Radii.card),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: has ? () => Nav.lyrics(context) : null,
          child: SizedBox(
            height: kLyricsCardHeight,
            child: Padding(
              padding: const EdgeInsets.all(Space.lg),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  SizedBox(
                    height:
                        28, // the same in every state: the buttons of a card with lyrics must not push its title down
                    child: Row(
                      children: [
                        Expanded(
                          child: Text(
                            has && !lyrics.synced
                                ? 'Lyrics (not synced)'
                                : 'Lyrics',
                            style: context.text.titleSmall,
                          ),
                        ),
                        if (has) ...[
                          InkResponse(
                            onTap: () => unawaited(_share(
                                context,
                                ref,
                                shareLyricsTextFor(
                                    track, [for (final l in shown) l.text]))),
                            radius: 20,
                            child: Padding(
                              padding: const EdgeInsets.all(4),
                              child: Icon(Icons.ios_share_rounded,
                                  size: 18,
                                  color: c.onBgMuted,
                                  semanticLabel: 'Share these lyrics'),
                            ),
                          ),
                          const SizedBox(width: Space.xs),
                          Icon(Icons.open_in_full_rounded,
                              size: 18, color: c.onBgMuted),
                        ],
                      ],
                    ),
                  ),
                  const SizedBox(height: Space.sm),
                  // What does not fit is cut off, never an overflow stripe: the card keeps its size.
                  Expanded(
                    child: ClipRect(
                      child: SingleChildScrollView(
                        physics: const NeverScrollableScrollPhysics(),
                        child: body,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
