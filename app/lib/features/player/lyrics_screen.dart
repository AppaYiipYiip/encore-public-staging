import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart' show ScrollDirection;
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:wakelock_plus/wakelock_plus.dart';

import '../../core/perf.dart';
import '../../design/theme.dart' show kFontFamily;
import '../../design/tokens.dart';
import '../../domain/artwork_color.dart';
import '../../domain/lyrics.dart';
import '../common/artwork_color.dart';
import '../common/widgets.dart';
import '../instant/instant_controller.dart';
import '../providers.dart';
import '../settings/settings_controller.dart';
import 'scrubber.dart';

/// How long the page waits for lyrics before it says there are none: a lookup that hangs (no data on a phone that has a network) must not
/// turn for ever (owner, 2026-10-31).
final lyricsDeadlineProvider =
    Provider<Duration>((ref) => const Duration(seconds: 12));

/// Lyrics for the track being played (cache -> server -> LRCLIB).
final currentLyricsProvider = FutureProvider.autoDispose
    .family<TrackLyrics?, String>((ref, trackId) async {
  final repo = ref.watch(lyricsRepositoryProvider);
  final snapshot = ref.read(playbackSnapshotProvider).value;
  final track = snapshot?.track;
  if (repo == null || track == null || track.id != trackId) return null;
  // A 30-second catalogue clip has no lyrics of its own: the whole song's
  // would not match what is heard, and nothing should be fetched for it
  // (docs/23, B34). A song the service is fetching is a real song.
  final isClip = track.imageUrl != null &&
      !track.fullSong &&
      ref.read(instantStatusProvider(trackId)) == null;
  if (isClip) return null;
  return repo
      .load(
        trackId: trackId,
        title: track.title,
        artist: track.artist,
        album: track.album,
        durationSec: track.duration?.inSeconds,
      )
      .timeout(ref.read(lyricsDeadlineProvider), onTimeout: () => null);
});

/// Full-screen, immersive lyrics (R-02, docs/06-ux-spec.md 4.7).
class LyricsScreen extends ConsumerStatefulWidget {
  const LyricsScreen({super.key});

  @override
  ConsumerState<LyricsScreen> createState() => _LyricsScreenState();
}

class _LyricsScreenState extends ConsumerState<LyricsScreen> {
  final Map<int, GlobalKey> _keys = {};
  final ScrollController _scroll = ScrollController();
  Timer? _resumeFollow;
  bool _following = true;
  int _lastScrolledIndex = -2;
  bool _wakelockOn = false;

  @override
  void initState() {
    super.initState();
    PerfMonitor.instance.begin('lyrics.open->visible');
    SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);
  }

  @override
  void dispose() {
    _resumeFollow?.cancel();
    _scroll.dispose();
    if (_wakelockOn) unawaited(_setWakelock(false));
    super.dispose();
  }

  /// Keeping the screen on is a nicety; a missing/failed plugin must never
  /// break the lyrics view (or surface as an unhandled error).
  Future<void> _setWakelock(bool on) async {
    try {
      await (on ? WakelockPlus.enable() : WakelockPlus.disable());
    } on Object {
      // ignore: the screen simply follows the system timeout
    }
  }

  void _userScrolled() {
    _following = false;
    _resumeFollow?.cancel();
    _resumeFollow = Timer(const Duration(seconds: 3), () {
      _following = true;
      _lastScrolledIndex = -2; // force re-centre on next tick
      if (mounted) setState(() {});
    });
  }

  void _followLine(int index) {
    if (!_following || index == _lastScrolledIndex || index < 0) return;
    _lastScrolledIndex = index;
    // Called from build: the scrolling itself waits for the frame.
    WidgetsBinding.instance.addPostFrameCallback((_) => _centre(index, 0));
  }

  /// Centres [index]. The list is lazy, so after a big seek the line has no
  /// widget yet (B19): jump to where it should be, let the list build it, then
  /// centre it for real. A few attempts at most; the next line retries anyway.
  void _centre(int index, int attempt) {
    if (!mounted || !_following || _lastScrolledIndex != index) return;
    final ctx = _keys[index]?.currentContext;
    if (ctx != null && ctx.mounted) {
      Scrollable.ensureVisible(
        ctx,
        alignment: 0.36,
        duration: Motion.emphasized,
        curve: Motion.curve,
      );
      return;
    }
    if (attempt >= 3 || !_scroll.hasClients) return;
    final position = _scroll.position;
    _scroll.jumpTo((index * _lineExtent()).clamp(
      position.minScrollExtent,
      position.maxScrollExtent,
    ));
    WidgetsBinding.instance
        .addPostFrameCallback((_) => _centre(index, attempt + 1));
  }

  /// Average height of the lines that are built right now.
  double _lineExtent() {
    var total = 0.0;
    var count = 0;
    for (final key in _keys.values) {
      final box = key.currentContext?.findRenderObject();
      if (box is RenderBox && box.hasSize) {
        total += box.size.height;
        count++;
      }
    }
    return count == 0 ? 64.0 : total / count;
  }

  @override
  Widget build(BuildContext context) {
    final snapshot = ref.watch(playbackSnapshotProvider).value;
    final track = snapshot?.track;
    final settings = ref.watch(settingsProvider);
    final c = context.colors;

    if (settings.keepScreenOnInLyrics && !_wakelockOn) {
      _wakelockOn = true;
      unawaited(_setWakelock(true));
    }

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
          icon: Icons.lyrics_outlined,
          title: 'Nothing is playing',
        ),
      );
    }

    final lyricsAsync = ref.watch(currentLyricsProvider(track.id));
    final swatch = ref
        .watch(artworkSwatchProvider(
            (albumId: track.albumId, coverArtId: track.coverArt)))
        .value;
    final tint = swatch != null
        ? backdropFor(swatch)
        : tintFor(track.album ?? track.title, lightness: 0.30);
    final facade = ref.watch(playbackFacadeProvider);

    return Scaffold(
      backgroundColor: tint,
      body: GestureDetector(
        behavior: HitTestBehavior.translucent,
        onVerticalDragEnd: (d) {
          if ((d.primaryVelocity ?? 0) > 600) context.pop();
        },
        child: DecoratedBox(
          decoration: BoxDecoration(
            gradient: LinearGradient(
              begin: Alignment.topCenter,
              end: Alignment.bottomCenter,
              colors: [tint, Color.lerp(tint, c.bg, 0.65)!],
            ),
          ),
          child: SafeArea(
            // Header, lyrics, controls: one under the other, all of them always
            // there (as in Spotify: when they faded away the page looked
            // empty, "hella empty", the owner said). The lyrics used to run
            // under the controls and the bar could not be dragged.
            child: Column(
              children: [
                _Header(
                  title: track.title,
                  artist: track.artist ?? '',
                  onClose: () => context.pop(),
                ),
                Expanded(
                  child: Stack(
                    children: [
                      Positioned.fill(
                        child: lyricsAsync.when(
                          loading: () =>
                              const Center(child: CircularProgressIndicator()),
                          error: (e, _) => const _NoLyrics(),
                          data: (lyrics) {
                            PerfMonitor.instance.end('lyrics.open->visible',
                                detail:
                                    lyrics == null ? 'none' : lyrics.source);
                            if (lyrics == null || lyrics.isEmpty) {
                              return const _NoLyrics();
                            }
                            return _LyricsBody(
                              lyrics: lyrics,
                              scroll: _scroll,
                              keys: _keys,
                              textScale: settings.lyricsTextScale,
                              onActive: _followLine,
                              onUserScroll: _userScrolled,
                              onSeek: (ms) {
                                HapticFeedback.selectionClick();
                                facade.seek(Duration(milliseconds: ms));
                              },
                            );
                          },
                        ),
                      ),
                      // Lines that scroll up under the header fade into the
                      // background (cheaper than a ShaderMask/saveLayer).
                      Positioned(
                        top: 0,
                        left: 0,
                        right: 0,
                        height: 48,
                        child: IgnorePointer(
                          child: DecoratedBox(
                            decoration: BoxDecoration(
                              gradient: LinearGradient(
                                begin: Alignment.topCenter,
                                end: Alignment.bottomCenter,
                                colors: [tint, tint.withValues(alpha: 0)],
                              ),
                            ),
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
                _Controls(
                  isPlaying: snapshot!.isPlaying,
                  onToggle: facade.togglePlayPause,
                  onNext: facade.skipNext,
                  onPrevious: facade.skipPrevious,
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _Header extends StatelessWidget {
  const _Header({
    required this.title,
    required this.artist,
    required this.onClose,
  });

  final String title;
  final String artist;
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding:
          const EdgeInsets.fromLTRB(Space.sm, Space.sm, Space.lg, Space.lg),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [
            Colors.black.withValues(alpha: 0.35),
            Colors.transparent,
          ],
        ),
      ),
      child: Row(
        children: [
          IconButton(
            tooltip: 'Close lyrics',
            icon: const Icon(Icons.keyboard_arrow_down_rounded, size: 32),
            onPressed: onClose,
          ),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: context.text.titleMedium),
                Text(artist,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: context.text.bodyMedium),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _Controls extends ConsumerWidget {
  const _Controls({
    required this.isPlaying,
    required this.onToggle,
    required this.onNext,
    required this.onPrevious,
  });

  final bool isPlaying;
  final VoidCallback onToggle;
  final VoidCallback onNext;
  final VoidCallback onPrevious;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Container(
      padding:
          const EdgeInsets.fromLTRB(Space.md, Space.sm, Space.md, Space.lg),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Scrubber(),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              IconButton(
                tooltip: 'Previous',
                iconSize: 40,
                icon: const Icon(Icons.skip_previous_rounded),
                onPressed: onPrevious,
              ),
              const SizedBox(width: Space.lg),
              PlayButton(
                isPlaying: isPlaying,
                size: 64,
                onPressed: onToggle,
              ),
              const SizedBox(width: Space.lg),
              IconButton(
                tooltip: 'Next',
                iconSize: 40,
                icon: const Icon(Icons.skip_next_rounded),
                onPressed: onNext,
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _LyricsBody extends ConsumerWidget {
  const _LyricsBody({
    required this.lyrics,
    required this.scroll,
    required this.keys,
    required this.textScale,
    required this.onActive,
    required this.onUserScroll,
    required this.onSeek,
  });

  final TrackLyrics lyrics;
  final ScrollController scroll;
  final Map<int, GlobalKey> keys;
  final double textScale;
  final ValueChanged<int> onActive;
  final VoidCallback onUserScroll;
  final ValueChanged<int> onSeek;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Only rebuild when the *active line* changes, not on every position tick.
    final active = ref.watch(
      playbackPositionProvider.select(
        (p) => lyrics.activeIndex(p.value?.inMilliseconds ?? 0),
      ),
    );
    if (lyrics.synced) onActive(active);

    final size = 28.0 * textScale;
    final top = MediaQuery.paddingOf(context).top;

    return NotificationListener<UserScrollNotification>(
      onNotification: (n) {
        if (n.direction != ScrollDirection.idle) onUserScroll();
        return false;
      },
      child: ListView.builder(
        controller: scroll,
        // First line starts in the upper third (clear of the header); the
        // active line is later centred at ~36% of the viewport.
        padding: EdgeInsets.fromLTRB(
          Space.xl,
          top + MediaQuery.sizeOf(context).height * 0.20,
          Space.xl,
          MediaQuery.sizeOf(context).height * 0.55,
        ),
        itemCount: lyrics.lines.length + 1,
        itemBuilder: (context, i) {
          if (i == lyrics.lines.length) {
            return Padding(
              padding: const EdgeInsets.only(top: Space.xl),
              child: Text(
                lyrics.source == null ? '' : 'Lyrics: ${lyrics.source}',
                style: context.text.bodySmall,
              ),
            );
          }
          final line = lyrics.lines[i];
          final isActive = lyrics.synced && i == active;
          final isPast = lyrics.synced && i < active;
          final key = keys.putIfAbsent(i, GlobalKey.new);
          final opacity = !lyrics.synced
              ? 0.92
              : isActive
                  ? 1.0
                  : isPast
                      ? 0.42
                      : 0.62;
          if (line.isBlank) {
            return SizedBox(
              key: key,
              height: size * 1.1,
              child: Align(
                alignment: Alignment.centerLeft,
                child: Opacity(
                  opacity: isActive ? 1 : 0.4,
                  child: Text('• • •',
                      style: TextStyle(
                          fontSize: size * 0.7,
                          color: Colors.white,
                          letterSpacing: 4)),
                ),
              ),
            );
          }
          return GestureDetector(
            key: key,
            behavior: HitTestBehavior.opaque,
            onTap: lyrics.synced && line.startMs != null
                ? () => onSeek(line.startMs!)
                : null,
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: Space.sm + 2),
              child: AnimatedDefaultTextStyle(
                duration: Motion.standard,
                style: TextStyle(
                  fontFamily: kFontFamily,
                  fontWeight: FontWeight.w800,
                  fontSize: size,
                  height: 1.18,
                  color: Colors.white.withValues(alpha: opacity),
                ),
                child: Text(line.text),
              ),
            ),
          );
        },
      ),
    );
  }
}

class _NoLyrics extends StatelessWidget {
  const _NoLyrics();

  @override
  Widget build(BuildContext context) {
    return const EmptyState(
      icon: Icons.lyrics_outlined,
      title: 'No lyrics for this song',
      message: 'We looked on your server and online. Enjoy the music.',
    );
  }
}
