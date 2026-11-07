import 'dart:async';

import 'package:encore_session/encore_session.dart';

import '../../data/db/app_database.dart';
import '../../domain/album_names.dart';
import '../../playback/queue_model.dart';
import '../player/playback_facade.dart';

/// The id a Jam's song has on a phone that has no row of it: named by the song,
/// not by its place in the queue (every Jam counts from 1, so a place names a
/// different song in the next Jam, and what is kept under the name, such as the
/// lyrics, belonged to another song). The prefix keeps it from being taken for
/// a row of this person's library.
String jamTrackId(QueueEntry entry) => 'jam:${entry.trackId}';

/// What the Jam-aware player needs of the Jam (the app's controller provides
/// it; tests use a fake).
abstract interface class JamLink {
  /// The person is in a Jam and its state is known.
  bool get inJam;

  /// This phone is the one that makes the sound.
  bool get iPlay;

  /// This phone is still getting the song the Jam is on (a song it does not
  /// have is fetched first); the player shows loading, not the old song.
  bool get loading;
  SessionState? get state;

  /// Fires whenever the Jam's state, or whether there is one, changes.
  Stream<void> get changes;

  /// Where the current song is right now, by the Jam's clock.
  int positionNowMs();

  /// Sends a command; `true` when the Jam accepted it.
  Future<bool> send(Command command);

  /// Tells the person something (a snackbar).
  void say(String message);
}

/// The person's player. Outside a Jam it is the ordinary player, untouched. In
/// a Jam it **is the Jam's**: the mini-player, the full player and the queue show
/// the shared queue and every button goes to the Jam; a song played from an
/// album, a playlist or a search plays in the Jam (right after the current
/// song, now) instead of starting a second, private player that disagrees
/// with it. The phone that makes the sound plays what the Jam says through the
/// real player ([engine]), driven by the Jam speaker, not by this class.
///
/// docs/39 F4, F5, F6: the first test on real phones, where a separate Jam
/// screen showed one song while the phone played another, and the Jam's song
/// cut in on what a person was listening to.
class JamPlaybackFacade implements PlaybackFacade {
  JamPlaybackFacade({required PlaybackFacade engine, required JamLink link})
      : _engine = engine,
        _link = link {
    _subscriptions
      ..add(_engine.snapshots.listen((_) => _emitSnapshot()))
      ..add(_engine.queueStream.listen((_) {
        if (!_jam) _queues.add(_engine.queue);
      }))
      ..add(_link.changes.listen((_) {
        _emitSnapshot();
        _queues.add(queue);
        _syncClock();
      }))
      ..add(_engine.positionStream.listen((p) {
        if (!_jam) _positions.add(p);
      }));
  }

  final PlaybackFacade _engine;
  final JamLink _link;
  final List<StreamSubscription<Object?>> _subscriptions = [];
  final _snapshots = StreamController<PlaybackSnapshot>.broadcast();
  final _queues = StreamController<QueueSnapshot>.broadcast();
  final _positions = StreamController<Duration>.broadcast();
  Timer? _clock;

  bool get _jam => _link.inJam && _link.state != null;

  Future<void> dispose() async {
    _clock?.cancel();
    for (final s in _subscriptions) {
      await s.cancel();
    }
    await _snapshots.close();
    await _queues.close();
    await _positions.close();
  }

  // ------------------------------------------------------------- what is on

  @override
  PlaybackSnapshot get snapshot => _jam ? _jamSnapshot() : _engine.snapshot;

  @override
  Stream<PlaybackSnapshot> get snapshots => _snapshots.stream;

  void _emitSnapshot() {
    if (!_snapshots.isClosed) _snapshots.add(snapshot);
  }

  /// While a Jam plays, the position comes from the Jam's clock (every phone
  /// shows the same); the rest of the time from the real player.
  void _syncClock() {
    final running = _jam && (_link.state?.playing ?? false);
    if (running && _clock == null) {
      _clock = Timer.periodic(const Duration(milliseconds: 250), (_) {
        if (_jam) {
          _positions.add(Duration(milliseconds: _link.positionNowMs()));
        }
      });
    } else if (!running) {
      _clock?.cancel();
      _clock = null;
      if (_jam) {
        _positions.add(Duration(milliseconds: _link.positionNowMs()));
      }
    }
  }

  @override
  Stream<Duration> get positionStream => _positions.stream;

  PlaybackSnapshot _jamSnapshot() {
    final s = _link.state!;
    final entry = s.current;
    const label = 'Jam';
    if (entry == null) {
      return const PlaybackSnapshot(sourceName: label, sourceId: 'jam');
    }
    // The phone that plays knows the real song (its own library id, its own
    // cover); everybody else shows what the entry says.
    final mine = _link.iPlay ? _engineTrackFor(entry) : null;
    final engine = _engine.snapshot;
    final duration = Duration(seconds: entry.durationSec ?? 0);
    return PlaybackSnapshot(
      track: mine ??
          NowPlayingTrack(
            id: jamTrackId(entry),
            title: entry.title ?? 'A song',
            artist: entry.artist,
            album: entry.album,
            catalogueArtistId: entry.artistRef,
            imageUrl: entry.imageUrl,
            duration: entry.durationSec == null ? null : duration,
          ),
      isPlaying: s.playing,
      isLoading: _link.iPlay && (engine.isLoading || _link.loading),
      position: Duration(milliseconds: _link.positionNowMs()),
      // The real length only when the real player has THIS song: while the
      // phone is still getting it, the player's length is the old song's.
      duration: mine != null && engine.duration > Duration.zero
          ? engine.duration
          : duration,
      queueIndex: s.index,
      queueLength: s.queue.length,
      repeat: switch (s.repeat) {
        Repeat.off => RepeatKind.off,
        Repeat.all => RepeatKind.all,
        Repeat.one => RepeatKind.one,
      },
      hasNext: s.index + 1 < s.queue.length || s.repeat == Repeat.all,
      hasPrevious: s.index > 0,
      sourceName: label,
      sourceId: 'jam',
    );
  }

  NowPlayingTrack? _engineTrackFor(QueueEntry entry) {
    final track = _engine.snapshot.track;
    if (track == null) return null;
    bool same(String? a, String? b) =>
        (a ?? '').trim().toLowerCase() == (b ?? '').trim().toLowerCase();
    return same(track.title, entry.title) && same(track.artist, entry.artist)
        ? track
        : null;
  }

  // ------------------------------------------------------------- transport

  Future<void> _send(Command command) async {
    await _link.send(command);
  }

  @override
  Future<void> play() => _jam ? _send(const Play()) : _engine.play();

  @override
  Future<void> pause() => _jam ? _send(const Pause()) : _engine.pause();

  @override
  Future<void> togglePlayPause() {
    if (!_jam) return _engine.togglePlayPause();
    return _send(_link.state!.playing ? const Pause() : const Play());
  }

  @override
  Future<void> seek(Duration position) => _jam
      ? _send(Seek(position.inMilliseconds.clamp(0, 86400000)))
      : _engine.seek(position);

  @override
  Future<void> skipNext() => _jam ? _send(const Next()) : _engine.skipNext();

  @override
  Future<void> skipPrevious() =>
      _jam ? _send(const Previous()) : _engine.skipPrevious();

  @override
  void toggleShuffle() {
    if (!_jam) return _engine.toggleShuffle();
    _link.say('Shuffle is not available in a Jam yet.');
  }

  @override
  void cycleRepeat() {
    if (!_jam) return _engine.cycleRepeat();
    final next = switch (_link.state!.repeat) {
      Repeat.off => Repeat.all,
      Repeat.all => Repeat.one,
      Repeat.one => Repeat.off,
    };
    unawaited(_send(SetRepeat(next)));
  }

  @override
  void setRepeat(RepeatKind kind) {
    if (!_jam) return _engine.setRepeat(kind);
    unawaited(_send(SetRepeat(switch (kind) {
      RepeatKind.off => Repeat.off,
      RepeatKind.all => Repeat.all,
      RepeatKind.one => Repeat.one,
    })));
  }

  // -------------------------------------------------- songs played from anywhere

  Add _addTrack(TrackRow t, AddAt at) => Add(
        t.id,
        at: at,
        title: t.title,
        artist: t.artist,
        album: realAlbumName(t.album),
        durationSec: t.durationSec,
      );

  Add _addStreamed(StreamedTrack t, AddAt at) => Add(
        'cat:${t.id}',
        at: at,
        title: t.title,
        artist: t.artist,
        album: t.album,
        durationSec: t.duration?.inSeconds,
        imageUrl: t.imageUrl,
        artistRef: t.catalogueArtistId,
      );

  @override
  Future<void> playTracks(
    List<TrackRow> tracks, {
    int startIndex = 0,
    String? sourceName,
    String? sourceId,
    bool shuffle = false,
    bool skipUnavailable = false,
  }) {
    if (!_jam) {
      return _engine.playTracks(tracks,
          startIndex: startIndex,
          sourceName: sourceName,
          sourceId: sourceId,
          shuffle: shuffle,
          skipUnavailable: skipUnavailable);
    }
    if (tracks.isEmpty) return Future<void>.value();
    // The song that was tapped plays now, in the Jam. The rest of the album is
    // not queued for everybody: that is a decision for whoever adds songs.
    return _send(
        _addTrack(tracks[startIndex.clamp(0, tracks.length - 1)], AddAt.now));
  }

  @override
  Future<void> playStreamed(
    List<StreamedTrack> tracks, {
    int startIndex = 0,
    String? sourceName,
    String? sourceId,
  }) {
    if (!_jam) {
      return _engine.playStreamed(tracks,
          startIndex: startIndex, sourceName: sourceName, sourceId: sourceId);
    }
    if (tracks.isEmpty) return Future<void>.value();
    return _send(_addStreamed(
        tracks[startIndex.clamp(0, tracks.length - 1)], AddAt.now));
  }

  @override
  Future<void> addToQueue(TrackRow track) =>
      _jam ? _send(_addTrack(track, AddAt.end)) : _engine.addToQueue(track);

  @override
  Future<void> playNext(TrackRow track) =>
      _jam ? _send(_addTrack(track, AddAt.next)) : _engine.playNext(track);

  @override
  Future<void> addStreamToQueue(StreamedTrack track) => _jam
      ? _send(_addStreamed(track, AddAt.end))
      : _engine.addStreamToQueue(track);

  // ---------------------------------------------------------------- queue

  @override
  QueueSnapshot get queue {
    if (!_jam) return _engine.queue;
    final s = _link.state!;
    return QueueSnapshot(
      items: [
        for (final e in s.queue)
          QueueItem.streamed(
            uid: e.uid,
            id: e.trackId,
            title: e.title ?? 'A song',
            // These are the Jam's songs, not rows of this phone's library.
            uri: Uri.parse('jam:${e.uid}'),
            artist: e.artist,
            catalogueArtistId: e.artistRef,
            album: e.album,
            imageUrl: e.imageUrl,
            durationSec: e.durationSec,
          ),
      ],
      currentIndex: s.queue.isEmpty ? -1 : s.index,
    );
  }

  @override
  Stream<QueueSnapshot> get queueStream => _queues.stream;

  int? _uidAt(int index) {
    final q = _link.state?.queue;
    if (q == null || index < 0 || index >= q.length) return null;
    return q[index].uid;
  }

  @override
  Future<void> jumpToQueueIndex(int index) {
    if (!_jam) return _engine.jumpToQueueIndex(index);
    final uid = _uidAt(index);
    return uid == null ? Future<void>.value() : _send(Jump(uid));
  }

  @override
  Future<void> removeFromQueue(int index) {
    if (!_jam) return _engine.removeFromQueue(index);
    final uid = _uidAt(index);
    return uid == null ? Future<void>.value() : _send(Remove(uid));
  }

  @override
  Future<void> moveInQueue(int from, int to) {
    if (!_jam) return _engine.moveInQueue(from, to);
    final uid = _uidAt(from);
    return uid == null ? Future<void>.value() : _send(Move(uid, to));
  }

  @override
  Future<void> clearUpNext() async {
    if (!_jam) return _engine.clearUpNext();
    final s = _link.state!;
    for (final e in s.queue.skip(s.index + 1).toList()) {
      await _send(Remove(e.uid));
    }
  }

  // --------------------------------- the real player's own business (the speaker)

  @override
  Future<void> stopAndClear() => _engine.stopAndClear();

  @override
  SleepTimerStatus get sleepTimer => _engine.sleepTimer;

  @override
  Stream<SleepTimerStatus> get sleepTimerStream => _engine.sleepTimerStream;

  @override
  Future<void> setSleepTimer(Duration? duration) =>
      _engine.setSleepTimer(duration);

  @override
  Future<void> setSleepAtEndOfTrack(bool enabled) =>
      _engine.setSleepAtEndOfTrack(enabled);

  @override
  double get speed => _engine.speed;

  @override
  Future<void> setSpeed(double speed) => _engine.setSpeed(speed);

  @override
  Stream<PlaybackNotice> get notices => _engine.notices;
}
