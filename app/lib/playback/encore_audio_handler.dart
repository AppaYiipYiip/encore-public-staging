import 'dart:async';

import 'package:audio_service/audio_service.dart';
import 'package:flutter/foundation.dart';
import 'package:rxdart/rxdart.dart';

import '../core/logger.dart';
import '../domain/album_names.dart';
import '../features/player/playback_facade.dart';
import 'library_browser.dart';

/// Android media session / notification / Android Auto bridge (ADR-035).
///
/// It owns no playback logic: every command is forwarded to the
/// [PlaybackFacade], every facade change is mirrored into `playbackState`
/// and `mediaItem`. The browse tree comes from the local database through
/// [LibraryBrowser], so a car works with no network.
class EncoreAudioHandler extends BaseAudioHandler with SeekHandler {
  /// [browseWait] is how long a request from the car waits for the library and
  /// the engine to come up (a cold start from the car answers before either
  /// exists); [onChildrenChanged] tells the car a list changed (tests record it).
  EncoreAudioHandler({
    this.browseWait = const Duration(seconds: 10),
    void Function(String parentId)? onChildrenChanged,
  }) : _onChildrenChanged = onChildrenChanged;

  final Duration browseWait;

  /// Only for tests: sees every "this list changed" announcement.
  final void Function(String parentId)? _onChildrenChanged;

  /// audio_service turns each value pushed here into a "children changed"
  /// notice for the car (the supported replacement of the deprecated static
  /// call).
  final Map<String, BehaviorSubject<Map<String, dynamic>>> _children = {};

  @override
  ValueStream<Map<String, dynamic>> subscribeToChildren(String parentMediaId) =>
      _children.putIfAbsent(
          parentMediaId, () => BehaviorSubject.seeded(<String, dynamic>{}));

  void _announceChildrenChanged(String parentMediaId) {
    _onChildrenChanged?.call(parentMediaId);
    _children[parentMediaId]?.add(<String, dynamic>{
      'changedAt': DateTime.now().microsecondsSinceEpoch,
    });
  }

  PlaybackFacade? _facade;
  LibraryBrowser? _browser;
  Completer<void> _browserReady = Completer<void>();
  final Completer<void> _facadeReady = Completer<void>();

  /// Resolves a server cover id to something Android can load: a cached
  /// file when available (works offline), else the network URL.
  Future<Uri?> Function(String coverArtId)? _coverArt;
  final List<StreamSubscription<Object?>> _subs = [];

  // The queue the car sees is a window of the real one (see _publishQueue);
  // the highlighted entry must be counted inside that window (B16).
  int _windowStart = 0;
  int _windowLength = 0;

  int? _inWindow(int absolute) {
    // No queue published yet (just attached): report the plain index.
    if (_windowLength == 0) return absolute < 0 ? null : absolute;
    final relative = absolute - _windowStart;
    return absolute >= 0 && relative >= 0 && relative < _windowLength
        ? relative
        : null;
  }

  // For detecting seeks/drift without a 5 Hz stream of playback states.
  Duration _reportedPosition = Duration.zero;
  DateTime _reportedAt = DateTime.now();

  /// Connects the handler to the (possibly re-created) engine.
  void attach(
    PlaybackFacade facade, {
    LibraryBrowser? browser,
    Future<Uri?> Function(String coverArtId)? coverArt,
  }) {
    detach();
    _facade = facade;
    if (!_facadeReady.isCompleted) _facadeReady.complete();
    _coverArt = coverArt;
    _setBrowser(browser);
    _subs
      ..add(facade.snapshots.listen(_publish))
      ..add(facade.queueStream.listen(_publishQueue))
      ..add(facade.positionStream.listen(_maybeResync));
    _publish(facade.snapshot);
    _publishQueue(facade.queue);
  }

  void detach() {
    for (final s in _subs) {
      unawaited(s.cancel());
    }
    _subs.clear();
    _facade = null;
  }

  /// Updates browsing without touching playback (server switched, or the
  /// library came up before the engine did).
  void setBrowser(
    LibraryBrowser? browser, {
    Future<Uri?> Function(String coverArtId)? coverArt,
  }) {
    if (coverArt != null) _coverArt = coverArt;
    _setBrowser(browser);
  }

  void _setBrowser(LibraryBrowser? browser) {
    final wasThere = _browser != null;
    _browser = browser;
    if (browser == null) {
      if (_browserReady.isCompleted) _browserReady = Completer<void>();
      return;
    }
    if (!_browserReady.isCompleted) _browserReady.complete();
    // A car that asked before the library was ready got a short or empty list.
    if (!wasThere) _announceChildrenChanged(AudioService.browsableRootId);
  }

  /// The library, waiting for it (bounded) if the car asked before it was up.
  Future<LibraryBrowser?> _waitForBrowser() async {
    final now = _browser;
    if (now != null) return now;
    try {
      await _browserReady.future.timeout(browseWait);
    } on TimeoutException {
      return null;
    }
    return _browser;
  }

  Future<PlaybackFacade?> _waitForFacade() async {
    final now = _facade;
    if (now != null) return now;
    try {
      await _facadeReady.future.timeout(browseWait);
    } on TimeoutException {
      return null;
    }
    return _facade;
  }

  // ----------------------------------------------------------- mirroring

  void _publish(PlaybackSnapshot s) {
    final track = s.track;
    if (track == null) {
      mediaItem.add(null);
      playbackState.add(PlaybackState(
        processingState: AudioProcessingState.idle,
        playing: false,
      ));
      return;
    }
    final direct =
        track.imageUrl == null ? null : Uri.tryParse(track.imageUrl!);
    final cover = track.coverArt == null ? direct : null;
    final duration = s.duration > Duration.zero ? s.duration : track.duration;
    final item = MediaItem(
      id: track.id,
      title: track.title,
      artist: track.artist,
      album: track.album,
      duration: duration,
      artUri: cover,
      extras: {
        'albumId': track.albumId,
        'artistId': track.artistId,
      },
    );
    final previous = mediaItem.valueOrNull;
    if (previous?.id != item.id || previous?.duration != item.duration) {
      // Keep the artwork we already resolved for the same track.
      mediaItem.add(previous?.id == item.id && previous?.artUri != null
          ? item.copyWith(artUri: previous!.artUri)
          : item);
    }
    final artId = track.coverArt;
    if (artId != null && (mediaItem.valueOrNull?.artUri == null)) {
      unawaited(_attachArt(track.id, artId));
    }
    _reportedPosition = s.position;
    _reportedAt = DateTime.now();
    playbackState.add(PlaybackState(
      controls: [
        MediaControl.skipToPrevious,
        s.isPlaying ? MediaControl.pause : MediaControl.play,
        MediaControl.skipToNext,
      ],
      systemActions: const {
        MediaAction.seek,
        MediaAction.skipToPrevious,
        MediaAction.skipToNext,
        MediaAction.playPause,
      },
      androidCompactActionIndices: const [0, 1, 2],
      processingState: s.isLoading
          ? AudioProcessingState.buffering
          : AudioProcessingState.ready,
      playing: s.isPlaying,
      updatePosition: s.position,
      bufferedPosition: s.position,
      speed: _facade?.speed ?? 1,
      queueIndex: _inWindow(s.queueIndex),
    ));
  }

  Future<void> _attachArt(String trackId, String coverArtId) async {
    final resolve = _coverArt;
    if (resolve == null) return;
    final uri = await resolve(coverArtId);
    final current = mediaItem.valueOrNull;
    if (uri == null || current == null || current.id != trackId) return;
    if (current.artUri == uri) return;
    mediaItem.add(current.copyWith(artUri: uri));
  }

  void _publishQueue(QueueSnapshot q) {
    // Android Auto shows the queue; cap it (binder payload, UI usefulness).
    const window = 60;
    final start = q.currentIndex < 0 ? 0 : q.currentIndex;
    final items = q.items.skip(start).take(window).toList();
    _windowStart = start;
    _windowLength = items.length;
    queue.add([
      for (final i in items)
        MediaItem(
          id: i.id,
          title: i.title,
          artist: i.artist,
          album: i.album,
          duration: i.duration,
          artUri: i.imageUrl == null ? null : Uri.tryParse(i.imageUrl!),
        ),
    ]);
    // The window moved: point the highlight at the same song inside it.
    final facade = _facade;
    final shown = facade == null ? null : _inWindow(facade.snapshot.queueIndex);
    if (shown != null && playbackState.value.queueIndex != shown) {
      playbackState.add(playbackState.value.copyWith(queueIndex: shown));
    }
  }

  /// Re-publishes the playback state when the position jumped (a seek) so
  /// the lock screen scrubber follows; normal playback is extrapolated by
  /// the system from the last update.
  void _maybeResync(Duration position) {
    final facade = _facade;
    if (facade == null) return;
    final s = facade.snapshot;
    if (!s.isPlaying) {
      if ((position - _reportedPosition).abs() > const Duration(seconds: 1)) {
        _publish(PlaybackSnapshot(
          track: s.track,
          isPlaying: s.isPlaying,
          isLoading: s.isLoading,
          position: position,
          duration: s.duration,
          queueIndex: s.queueIndex,
          queueLength: s.queueLength,
          shuffle: s.shuffle,
          repeat: s.repeat,
          hasNext: s.hasNext,
          hasPrevious: s.hasPrevious,
          sourceName: s.sourceName,
          sourceId: s.sourceId,
        ));
      }
      return;
    }
    final elapsed = DateTime.now().difference(_reportedAt);
    final expected = _reportedPosition + elapsed * (facade.speed);
    if ((position - expected).abs() > const Duration(milliseconds: 1500)) {
      _publish(PlaybackSnapshot(
        track: s.track,
        isPlaying: s.isPlaying,
        isLoading: s.isLoading,
        position: position,
        duration: s.duration,
        queueIndex: s.queueIndex,
        queueLength: s.queueLength,
        shuffle: s.shuffle,
        repeat: s.repeat,
        hasNext: s.hasNext,
        hasPrevious: s.hasPrevious,
        sourceName: s.sourceName,
        sourceId: s.sourceId,
      ));
    }
  }

  // -------------------------------------------------------------- commands

  @override
  Future<void> play() async => _facade?.play();

  @override
  Future<void> pause() async => _facade?.pause();

  @override
  Future<void> stop() async {
    await _facade?.pause();
    await super.stop();
  }

  @override
  Future<void> seek(Duration position) async => _facade?.seek(position);

  @override
  Future<void> skipToNext() async => _facade?.skipNext();

  @override
  Future<void> skipToPrevious() async => _facade?.skipPrevious();

  @override
  Future<void> skipToQueueItem(int index) async {
    final f = _facade;
    if (f == null) return;
    // `index` is relative to the capped window we published.
    final base = f.queue.currentIndex < 0 ? 0 : f.queue.currentIndex;
    await f.jumpToQueueIndex(base + index);
  }

  @override
  Future<void> setShuffleMode(AudioServiceShuffleMode shuffleMode) async {
    final f = _facade;
    if (f == null) return;
    final want = shuffleMode != AudioServiceShuffleMode.none;
    if (f.snapshot.shuffle != want) f.toggleShuffle();
  }

  @override
  Future<void> setRepeatMode(AudioServiceRepeatMode repeatMode) async {
    final f = _facade;
    if (f == null) return;
    final want = switch (repeatMode) {
      AudioServiceRepeatMode.none => RepeatKind.off,
      AudioServiceRepeatMode.one => RepeatKind.one,
      AudioServiceRepeatMode.all ||
      AudioServiceRepeatMode.group =>
        RepeatKind.all,
    };
    if (f.snapshot.repeat != want) f.setRepeat(want);
  }

  @override
  Future<void> setSpeed(double speed) async => _facade?.setSpeed(speed);

  @override
  Future<void> onTaskRemoved() async {
    // The user swiped the app away: keep playing if music is on, otherwise
    // let the service end so the process can be reclaimed.
    if (!(_facade?.snapshot.isPlaying ?? false)) await stop();
  }

  // --------------------------------------------------------------- browsing

  @override
  Future<List<MediaItem>> getChildren(
    String parentMediaId, [
    Map<String, dynamic>? options,
  ]) async {
    final id = parentMediaId == AudioService.browsableRootId
        ? BrowseIds.root
        : parentMediaId;
    // The top level is fixed: show it even before the library exists.
    final browser = id == BrowseIds.root ? _browser : await _waitForBrowser();
    if (browser == null && id != BrowseIds.root) return const [];
    try {
      final nodes = await (browser?.children(id) ?? Future.value(kBrowseRoot));
      return await Future.wait([for (final n in nodes) _toItem(n)]);
    } on Object catch (error, stack) {
      Log.error('auto', 'getChildren($parentMediaId) failed', error, stack);
      return const [];
    }
  }

  Future<MediaItem> _toItem(BrowseNode n) async => MediaItem(
        id: n.id,
        title: n.title,
        artist: n.subtitle,
        artUri:
            n.coverArtId == null ? null : await _coverArt?.call(n.coverArtId!),
        playable: n.playable,
        extras: {
          if (n.browsable)
            'android.media.browse.CONTENT_STYLE_PLAYABLE_HINT': 1,
        },
      );

  @override
  Future<void> playFromMediaId(String mediaId,
      [Map<String, dynamic>? extras]) async {
    final request = await (await _waitForBrowser())?.resolvePlay(mediaId);
    final facade = await _waitForFacade();
    if (request == null || facade == null) return;
    await facade.playTracks(
      request.tracks,
      startIndex: request.startIndex,
      sourceName: request.sourceName,
      sourceId: request.sourceId,
    );
  }

  @override
  Future<List<MediaItem>> search(String query,
      [Map<String, dynamic>? extras]) async {
    final request = await (await _waitForBrowser())?.search(query);
    if (request == null) return const [];
    return [
      for (final t in request.tracks.take(30))
        MediaItem(
          id: BrowseIds.track(t.id, request.sourceId),
          title: t.title,
          artist: t.artist,
          album: realAlbumName(t.album),
          artUri:
              t.coverArt == null ? null : await _coverArt?.call(t.coverArt!),
          playable: true,
        ),
    ];
  }

  @override
  Future<void> playFromSearch(String query,
      [Map<String, dynamic>? extras]) async {
    final request = await (await _waitForBrowser())?.search(query);
    final facade = await _waitForFacade();
    if (request == null || facade == null) return;
    await facade.playTracks(
      request.tracks,
      sourceName: request.sourceName,
      sourceId: request.sourceId,
    );
  }

  @override
  Future<MediaItem?> getMediaItem(String mediaId) async {
    final current = mediaItem.valueOrNull;
    return current?.id == mediaId ? current : null;
  }

  @visibleForTesting
  PlaybackFacade? get debugFacade => _facade;
}
