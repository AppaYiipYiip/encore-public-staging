import 'dart:async';
import 'dart:math';

import 'package:encore/core/clock.dart';
import 'package:encore/core/perf.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/features/player/playback_facade.dart';
import 'package:encore/playback/audio_backend.dart';
import 'package:encore/playback/playback_engine.dart';
import 'package:encore/playback/playback_state_store.dart';
import 'package:encore/playback/queue_model.dart';
import 'package:encore/playback/replay_gain.dart';
import 'package:encore/playback/source_resolver.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/factories.dart';
import '../support/fake_audio_backend.dart';

class FakeResolver implements SourceResolver {
  final Set<String> local = {};
  int resolveCount = 0;

  /// The server does not answer: the address of a song that is not a file cannot be made (the real resolver throws this).
  bool serverAway = false;

  @override
  Future<AudioSourceSpec> resolve(QueueItem item) async {
    resolveCount++;
    final direct = item.directUri;
    if (direct != null) return AudioSourceSpec(uid: item.uid, uri: direct);
    final isLocal = local.contains(item.id);
    if (serverAway && !isLocal) throw const ServerNotAnswering();
    return AudioSourceSpec(
      uid: item.uid,
      uri: isLocal
          ? Uri.file('/data/${item.id}.opus')
          : Uri.parse('https://srv/stream?id=${item.id}'),
      isLocal: isLocal,
    );
  }
}

class FakeRecorder implements PlayRecorder {
  final List<String> nowPlayingIds = [];
  final List<({String id, Duration listened})> plays = [];

  @override
  Future<void> nowPlaying(QueueItem item) async => nowPlayingIds.add(item.id);

  @override
  Future<void> played(QueueItem item,
      {required Duration listened, String? source}) async {
    plays.add((id: item.id, listened: listened));
  }
}

class FakeEffects implements AudioEffects {
  final List<double> boosts = [];

  @override
  Future<void> setLoudnessBoost(double db) async => boosts.add(db);
}

class FakeTimer implements Timer {
  FakeTimer(this.callback);

  final void Function(Timer) callback;
  bool cancelled = false;

  @override
  void cancel() => cancelled = true;

  @override
  bool get isActive => !cancelled;

  @override
  int get tick => 0;

  void fire() => callback(this);
}

class Harness {
  Harness._();

  late FakeAudioBackend backend;
  late FakeResolver resolver;
  late FakeRecorder recorder;
  late FakeEffects effects;
  late MemoryPlaybackStateStore store;
  late FakeClock clock;
  late PlaybackEngine engine;
  late List<TrackRow> tracks;
  final List<FakeTimer> timers = [];
  final List<PlaybackNotice> notices = [];
  ReplayGainSettings replayGain = const ReplayGainSettings();

  /// Whether more songs of an instant-play run are still being fetched.
  bool moreComing = false;

  /// Whether the server can be reached (the phone has a network). Songs that are not downloaded need it.
  bool reachable = true;

  /// Whether the server answers when the engine asks (the phone has a network either way), and how often it was asked.
  bool serverUp = true;
  int serverAsked = 0;

  /// The phone has a network although [reachable] says the server was last found out of reach (the radio is on and data came back).
  bool network = false;

  /// While set, the server does not answer the engine's look at all (it hangs: a network without data).
  Completer<void>? serverGate;

  static Future<Harness> start({
    int tracks = 5,
    MemoryPlaybackStateStore? store,
    Map<String, TrackRow>? library,
    Duration loadTimeout = const Duration(seconds: 12),
    Future<TrackRow?> Function(String artist, String title, String? album)?
        findByName,
    Duration lookupBudget = const Duration(seconds: 4),
  }) async {
    final h = Harness._();
    h.backend = FakeAudioBackend();
    h.resolver = FakeResolver();
    h.recorder = FakeRecorder();
    h.effects = FakeEffects();
    h.store = store ?? MemoryPlaybackStateStore();
    h.clock = FakeClock(DateTime.utc(2026, 10, 15, 12));
    h.tracks = [for (var i = 1; i <= tracks; i++) trackRow('t$i')];
    final lib = library ?? {for (final t in h.tracks) t.id: t};
    h.engine = PlaybackEngine(
      backend: h.backend,
      resolver: h.resolver,
      store: h.store,
      lookupTracks: (ids) async => {
        for (final id in ids)
          if (lib[id] != null) id: lib[id]!,
      },
      recorder: h.recorder,
      effects: h.effects,
      replayGain: () => h.replayGain,
      moreComing: () => h.moreComing,
      loadTimeout: loadTimeout,
      canReachServer: () => h.reachable,
      networkPresent: () => h.network,
      serverAnswers: () async {
        h.serverAsked++;
        await h.serverGate?.future;
        // Asking is how the phone learns the server is back.
        if (h.network && h.serverUp) h.reachable = true;
        return h.serverUp;
      },
      serverRetryDelays: const [Duration(milliseconds: 15)],
      findByName: findByName,
      catalogueLookupBudget: lookupBudget,
      clock: h.clock,
      random: Random(1),
      periodicTimer: (period, callback) {
        final t = FakeTimer(callback);
        h.timers.add(t);
        return t;
      },
    );
    h.engine.notices.listen(h.notices.add);
    return h;
  }

  /// Uids of the queue in play order.
  List<int> get uids => [for (final i in engine.debugQueue.ordered) i.uid];

  List<String> get window => [
        for (final s in backend.sources)
          engine.debugQueue.items.firstWhere((i) => i.uid == s.uid).id,
      ];

  String? get currentId => engine.snapshot.track?.id;

  Future<void> settle() => pumpEventQueue();

  Future<void> dispose() => engine.dispose();
}

void main() {
  setUpAll(() => PerfMonitor.instance.logToConsole = false);

  group('starting playback', () {
    test(
        'P1-06: play.audible ends when the music is really moving (position past 200 ms), not when the player says it plays',
        () async {
      final h = await Harness.start();
      PerfMonitor.instance.logToConsole = false;
      final before = PerfMonitor.instance.spans.length;
      h.resolver.local.add('t1');

      await h.engine.playTracks(h.tracks.sublist(0, 2));
      expect(PerfMonitor.instance.isOpen('play.audible'), isTrue,
          reason: 'the player says it plays, nothing is audible yet');

      h.backend.emitPosition(const Duration(milliseconds: 120));
      expect(PerfMonitor.instance.isOpen('play.audible'), isTrue);

      h.backend.emitPosition(const Duration(milliseconds: 420));
      expect(PerfMonitor.instance.isOpen('play.audible'), isFalse);
      final span = PerfMonitor.instance.spans
          .skip(before)
          .lastWhere((s) => s.name == 'play.audible');
      expect(span.detail, 'source=file id=t1');
      await h.dispose();
    });

    test('P1-06: a streamed song says source=stream', () async {
      final h = await Harness.start();
      PerfMonitor.instance.logToConsole = false;
      final before = PerfMonitor.instance.spans.length;

      await h.engine.playTracks(h.tracks.sublist(0, 2));
      h.backend.emitPosition(const Duration(milliseconds: 500));

      final span = PerfMonitor.instance.spans
          .skip(before)
          .lastWhere((s) => s.name == 'play.audible');
      expect(span.detail, 'source=stream id=t1');
      await h.dispose();
    });

    test('loads current + next into the window and plays', () async {
      final h = await Harness.start();
      await h.engine.playTracks(h.tracks, sourceName: 'Mix', sourceId: 'p:1');

      expect(h.window, ['t1', 't2']);
      expect(h.backend.state.playing, isTrue);
      expect(h.engine.snapshot.track!.id, 't1');
      expect(h.engine.snapshot.sourceName, 'Mix');
      expect(h.engine.snapshot.sourceId, 'p:1');
      expect(h.engine.snapshot.queueLength, 5);
      expect(h.engine.snapshot.hasNext, isTrue);
      await h.dispose();
    });

    test('a 5,000-song queue still loads only two sources', () async {
      final h = await Harness.start(tracks: 5000);
      await h.engine.playTracks(h.tracks, startIndex: 2500);
      expect(h.backend.sources.length, 2);
      expect(h.window, ['t2501', 't2502']);
      expect(h.resolver.resolveCount, 2,
          reason: 'only the window is resolved, not the queue');
      await h.dispose();
    });

    test('starts at the tapped row', () async {
      final h = await Harness.start();
      await h.engine.playTracks(h.tracks, startIndex: 3);
      expect(h.currentId, 't4');
      expect(h.window, ['t4', 't5']);
      await h.dispose();
    });

    test('the last track has no next source', () async {
      final h = await Harness.start();
      await h.engine.playTracks(h.tracks, startIndex: 4);
      expect(h.window, ['t5']);
      expect(h.engine.snapshot.hasNext, isFalse);
      await h.dispose();
    });

    test('downloaded tracks are played from the file', () async {
      final h = await Harness.start();
      h.resolver.local.add('t1');
      await h.engine.playTracks(h.tracks);
      expect(h.backend.sources.first.isLocal, isTrue);
      expect(h.backend.sources.last.isLocal, isFalse);
      await h.dispose();
    });

    test('shuffle button starts on a random track but keeps it first',
        () async {
      final h = await Harness.start(tracks: 20);
      await h.engine.playTracks(h.tracks, shuffle: true);
      expect(h.engine.snapshot.shuffle, isTrue);
      final started = h.currentId;
      // Walk the whole queue: every track exactly once.
      final seen = <String>{started!};
      for (var i = 0; i < 19; i++) {
        await h.engine.skipNext();
        seen.add(h.currentId!);
      }
      expect(seen.length, 20);
      await h.dispose();
    });

    test('rapid taps: the last request wins and loads once', () async {
      final h = await Harness.start();
      final a = h.engine.playTracks(h.tracks, startIndex: 0);
      final b = h.engine.playTracks(h.tracks, startIndex: 3);
      await Future.wait([a, b]);
      expect(h.currentId, 't4');
      expect(h.window, ['t4', 't5']);
      expect(h.backend.setSourcesCount, 1,
          reason: 'the superseded request never touched the player');
      await h.dispose();
    });
  });

  group('advancing', () {
    test('gapless auto-advance moves the cursor and slides the window',
        () async {
      final h = await Harness.start();
      await h.engine.playTracks(h.tracks);
      h.backend.finishCurrent();
      await h.settle();

      expect(h.currentId, 't2');
      expect(h.window, ['t2', 't3']);
      expect(h.backend.currentUid, h.engine.debugQueue.current!.uid);
      expect(h.backend.setSourcesCount, 1, reason: 'no reload, truly gapless');
      await h.dispose();
    });

    test('window invariants hold across a whole queue', () async {
      final h = await Harness.start(tracks: 12);
      await h.engine.playTracks(h.tracks);
      for (var i = 0; i < 11; i++) {
        h.backend.finishCurrent();
        await h.settle();
        expect(h.backend.sources.length, lessThanOrEqualTo(2));
        expect(h.backend.currentUid, h.engine.debugQueue.current!.uid,
            reason: 'player and queue agree after advance $i');
        expect(h.currentId, 't${i + 2}');
      }
      expect(h.window, ['t12']);
      await h.dispose();
    });

    test('skipNext reuses the loaded next source (gapless seek)', () async {
      final h = await Harness.start();
      await h.engine.playTracks(h.tracks);
      await h.engine.skipNext();
      await h.settle();

      expect(h.currentId, 't2');
      expect(h.backend.setSourcesCount, 1);
      expect(h.backend.calls, contains('seek(0s, @1)'));
      expect(h.window, ['t2', 't3']);
      await h.dispose();
    });

    test('skipPrevious restarts a track that has played a while', () async {
      final h = await Harness.start();
      await h.engine.playTracks(h.tracks, startIndex: 2);
      h.backend.emitPosition(const Duration(seconds: 30));
      await h.engine.skipPrevious();
      expect(h.currentId, 't3');
      expect(h.backend.position, Duration.zero);
      await h.dispose();
    });

    test('skipPrevious near the start goes to the previous track', () async {
      final h = await Harness.start();
      await h.engine.playTracks(h.tracks, startIndex: 2);
      h.backend.emitPosition(const Duration(seconds: 1));
      await h.engine.skipPrevious();
      expect(h.currentId, 't2');
      expect(h.window, ['t2', 't3']);
      await h.dispose();
    });

    test('skipPrevious on the first track just restarts it', () async {
      final h = await Harness.start();
      await h.engine.playTracks(h.tracks);
      h.backend.emitPosition(const Duration(seconds: 1));
      await h.engine.skipPrevious();
      expect(h.currentId, 't1');
      expect(h.backend.position, Duration.zero);
      await h.dispose();
    });

    test('end of queue with repeat off stops on the last track', () async {
      final h = await Harness.start(tracks: 2);
      await h.engine.playTracks(h.tracks);
      h.backend.finishCurrent();
      await h.settle();
      h.backend.finishCurrent(); // last track ends
      await h.settle();

      expect(h.currentId, 't2');
      expect(h.backend.state.playing, isFalse);
      await h.dispose();
    });

    test('skipNext at the end of the queue does not leave the queue', () async {
      final h = await Harness.start(tracks: 2);
      await h.engine.playTracks(h.tracks, startIndex: 1);
      await h.engine.skipNext();
      expect(h.currentId, 't2');
      expect(h.backend.state.playing, isFalse);
      await h.dispose();
    });
  });

  group('late events from a window that was replaced (B15)', () {
    test('a song change reported during a slow load does not skip a song',
        () async {
      final h = await Harness.start(tracks: 6);
      await h.engine.playTracks(h.tracks); // window [t1, t2]
      h.backend.setSourcesGate = Completer<void>();

      // The person picks t4; while that loads, the old window moves on.
      final loading = h.engine.playTracks(h.tracks, startIndex: 3);
      await pumpEventQueue();
      h.backend.finishCurrent(); // the old player goes t1 -> t2
      h.backend.setSourcesGate!.complete();
      await loading;
      await h.settle();

      expect(h.currentId, 't4',
          reason: 'the late "moved to t2" belongs to a window that is gone');
      await h.dispose();
    });
  });

  group('repeat and shuffle', () {
    test('repeat one loops seamlessly; next still moves on', () async {
      final h = await Harness.start();
      await h.engine.playTracks(h.tracks);
      h.engine.cycleRepeat(); // all
      h.engine.cycleRepeat(); // one
      await h.settle();
      expect(h.engine.snapshot.repeat, RepeatKind.one);
      expect(h.backend.loopOne, isTrue);
      expect(h.window, ['t1'], reason: 'no next source while looping');

      h.backend.finishCurrent();
      await h.settle();
      expect(h.currentId, 't1');

      await h.engine.skipNext();
      expect(h.currentId, 't2');
      await h.dispose();
    });

    test('a repeat mode can be set directly, from any other mode (B16)',
        () async {
      final h = await Harness.start();
      await h.engine.playTracks(h.tracks);
      h.engine.setRepeat(RepeatKind.one); // off -> one in a single step
      await h.settle();
      expect(h.engine.snapshot.repeat, RepeatKind.one);
      expect(h.backend.loopOne, isTrue);

      h.engine.setRepeat(RepeatKind.off); // one -> off, not one -> off via all
      await h.settle();
      expect(h.engine.snapshot.repeat, RepeatKind.off);
      expect(h.backend.loopOne, isFalse);

      h.engine.setRepeat(RepeatKind.all);
      await h.settle();
      expect(h.engine.snapshot.repeat, RepeatKind.all);
      await h.dispose();
    });

    test('repeat all wraps: the last track is followed by the first', () async {
      final h = await Harness.start(tracks: 3);
      await h.engine.playTracks(h.tracks, startIndex: 2);
      h.engine.cycleRepeat(); // all
      await h.settle();
      expect(h.window, ['t3', 't1']);

      h.backend.finishCurrent();
      await h.settle();
      expect(h.currentId, 't1');
      expect(h.window, ['t1', 't2']);
      await h.dispose();
    });

    test('toggling shuffle keeps the track and changes what is next', () async {
      final h = await Harness.start(tracks: 30);
      await h.engine.playTracks(h.tracks, startIndex: 4);
      h.engine.toggleShuffle();
      await h.settle();

      expect(h.currentId, 't5');
      expect(h.window.first, 't5');
      expect(h.engine.snapshot.shuffle, isTrue);
      expect(h.backend.currentUid, h.engine.debugQueue.current!.uid);
      await h.dispose();
    });
  });

  group('queue editing', () {
    test('add to queue on the last track extends the window', () async {
      final h = await Harness.start(tracks: 2);
      await h.engine.playTracks(h.tracks, startIndex: 1);
      expect(h.window, ['t2']);
      await h.engine.addToQueue(trackRow('x'));
      expect(h.window.length, 2);
      expect(h.engine.queue.items.last.id, 'x');
      await h.dispose();
    });

    test('play next replaces the preloaded next source', () async {
      final h = await Harness.start();
      await h.engine.playTracks(h.tracks);
      await h.engine.playNext(trackRow('x'));
      expect(h.window, ['t1', 'x']);
      h.backend.finishCurrent();
      await h.settle();
      expect(h.currentId, 'x');
      expect(h.window, ['x', 't2']);
      await h.dispose();
    });

    test('add to queue / play next on an empty queue starts playing', () async {
      final h = await Harness.start(tracks: 0);
      await h.engine.addToQueue(trackRow('a'));
      expect(h.currentId, 'a');
      expect(h.backend.state.playing, isTrue);
      await h.dispose();
    });

    test('removing the playing track starts the next one', () async {
      final h = await Harness.start();
      await h.engine.playTracks(h.tracks);
      await h.engine.removeFromQueue(0);
      expect(h.currentId, 't2');
      expect(h.window, ['t2', 't3']);
      expect(h.backend.state.playing, isTrue);
      await h.dispose();
    });

    test('removing the next track fixes the preloaded source', () async {
      final h = await Harness.start();
      await h.engine.playTracks(h.tracks);
      await h.engine.removeFromQueue(1);
      expect(h.window, ['t1', 't3']);
      await h.dispose();
    });

    test('removing the only track empties and stops', () async {
      final h = await Harness.start(tracks: 1);
      await h.engine.playTracks(h.tracks);
      await h.engine.removeFromQueue(0);
      expect(h.engine.snapshot.track, isNull);
      expect(h.backend.sources, isEmpty);
      expect(h.backend.state.playing, isFalse);
      await h.dispose();
    });

    test('move changes the upcoming order', () async {
      final h = await Harness.start();
      await h.engine.playTracks(h.tracks);
      await h.engine.moveInQueue(3, 1); // t4 becomes next
      expect(h.window, ['t1', 't4']);
      await h.dispose();
    });

    test('clear up next leaves only the current track', () async {
      final h = await Harness.start();
      await h.engine.playTracks(h.tracks, startIndex: 1);
      await h.engine.clearUpNext();
      expect(h.window, ['t2']);
      expect(h.engine.queue.items.map((i) => i.id), ['t1', 't2']);
      expect(h.engine.snapshot.hasNext, isFalse);
      await h.dispose();
    });

    test('jump to a queue index plays that entry', () async {
      final h = await Harness.start();
      await h.engine.playTracks(h.tracks);
      await h.engine.jumpToQueueIndex(3);
      expect(h.currentId, 't4');
      expect(h.window, ['t4', 't5']);
      await h.dispose();
    });
  });

  group('errors', () {
    test('first failure retries the same track from the same position',
        () async {
      final h = await Harness.start();
      await h.engine.playTracks(h.tracks);
      h.backend.emitPosition(const Duration(seconds: 12));
      h.backend.failCurrent();
      await h.settle();

      expect(h.currentId, 't1');
      expect(h.backend.setSourcesCount, 2);
      expect(h.backend.calls.last, isNot('pause'));
      expect(h.notices, isEmpty, reason: 'retry is silent');
      await h.dispose();
    });

    test('a second failure skips ahead and tells the user', () async {
      final h = await Harness.start();
      await h.engine.playTracks(h.tracks);
      h.backend.failCurrent();
      await h.settle();
      h.backend.failCurrent();
      await h.settle();

      expect(h.currentId, 't2');
      expect(h.notices.single.isError, isTrue);
      expect(h.notices.single.message, contains('Song t1'));
      await h.dispose();
    });

    test('one failure reported twice is still one failure (B15)', () async {
      // The real player reports a load failure both as an error event and as
      // the exception of setAudioSource.
      final h = await Harness.start();
      await h.engine.playTracks(h.tracks);
      h.backend.failCurrent();
      h.backend.failCurrent();
      await h.settle();

      expect(h.currentId, 't1', reason: 'the retry was not burnt by the echo');
      expect(h.backend.setSourcesCount, 2);
      expect(h.notices, isEmpty);
      await h.dispose();
    });

    test('a failing preload of the next song does not interrupt this one (B15)',
        () async {
      final h = await Harness.start();
      await h.engine.playTracks(h.tracks);
      expect(h.window.length, 2);

      h.backend.failSlot(1);
      await h.settle();

      expect(h.currentId, 't1');
      expect(h.backend.setSourcesCount, 1, reason: 'no reload');
      expect(h.notices, isEmpty);
      await h.dispose();
    });

    test('three tracks failing in a row stops instead of looping forever',
        () async {
      final h = await Harness.start(tracks: 10);
      await h.engine.playTracks(h.tracks);
      for (var i = 0; i < 8; i++) {
        h.backend.failCurrent();
        await h.settle();
      }
      expect(h.backend.state.playing, isFalse);
      expect(h.notices.any((n) => n.message.contains('stopped')), isTrue);
      expect(h.currentId, isNot('t10'), reason: 'did not run to the end');
      await h.dispose();
    });

    test('a track that plays resets the failure budget', () async {
      final h = await Harness.start(tracks: 10);
      await h.engine.playTracks(h.tracks);
      h.backend.failCurrent();
      await h.settle();
      h.backend.failCurrent();
      await h.settle(); // t1 skipped -> t2
      h.backend.emitState(const BackendState(
          playing: true, processing: BackendProcessing.ready));
      await h.settle();
      h.backend.failCurrent();
      await h.settle(); // t2 gets its own retry again
      expect(h.currentId, 't2');
      await h.dispose();
    });
  });

  group('persistence', () {
    test('queue and position are saved and restored paused', () async {
      final store = MemoryPlaybackStateStore();
      final h = await Harness.start(store: store);
      await h.engine.playTracks(h.tracks,
          startIndex: 2, sourceName: 'Album', sourceId: 'album:1');
      h.backend.emitPosition(const Duration(seconds: 42));
      await h.engine.pause();
      await h.settle();
      expect(store.value, isNotNull);
      expect(store.value!.positionMs, 42000);

      final h2 = await Harness.start(store: store, library: {
        for (final t in h.tracks) t.id: t,
      });
      await h2.engine.restore();
      expect(h2.currentId, 't3');
      expect(h2.engine.snapshot.isPlaying, isFalse);
      expect(h2.engine.snapshot.sourceName, 'Album');
      expect(h2.engine.snapshot.position, const Duration(seconds: 42));
      expect(h2.backend.sources, isEmpty, reason: 'nothing loaded yet');

      await h2.engine.play();
      expect(h2.window, ['t3', 't4']);
      expect(h2.backend.position, const Duration(seconds: 42));
      expect(h2.backend.state.playing, isTrue);
      await h.dispose();
      await h2.dispose();
    });

    test('restore drops tracks that left the library', () async {
      final store = MemoryPlaybackStateStore();
      final h = await Harness.start(store: store);
      await h.engine.playTracks(h.tracks, startIndex: 1);
      await h.engine.pause();
      await h.settle();

      final survivors = {
        for (final t in h.tracks)
          if (t.id != 't2') t.id: t,
      };
      final h2 = await Harness.start(store: store, library: survivors);
      await h2.engine.restore();
      expect(h2.currentId, 't3', reason: 'next survivor');
      expect(h2.engine.queue.items.length, 4);
      await h.dispose();
      await h2.dispose();
    });

    test(
        'a seek past the end of what is loaded stops at its end (a 29 s sample '
        'is never "at 2:51")', () async {
      final h = await Harness.start();
      await h.engine.playTracks(h.tracks);
      h.backend.setDuration(const Duration(seconds: 29));

      await h.engine.seek(const Duration(seconds: 171));

      expect(h.backend.position, const Duration(seconds: 29));
      expect(h.backend.calls.where((c) => c.startsWith('seek(171')), isEmpty,
          reason:
              'the player must never be asked for a position it does not have');
      await h.dispose();
    });

    test('a seek inside what is loaded is passed on untouched', () async {
      final h = await Harness.start();
      await h.engine.playTracks(h.tracks);
      h.backend.setDuration(const Duration(seconds: 29));

      await h.engine.seek(const Duration(seconds: 12));

      expect(h.backend.position, const Duration(seconds: 12));
      await h.dispose();
    });

    test('seeking before anything is loaded is remembered', () async {
      final store = MemoryPlaybackStateStore();
      final h = await Harness.start(store: store);
      await h.engine.playTracks(h.tracks);
      await h.engine.pause();
      await h.settle();

      final h2 = await Harness.start(store: store);
      await h2.engine.restore();
      await h2.engine.seek(const Duration(seconds: 90));
      await h2.engine.play();
      expect(h2.backend.position, const Duration(seconds: 90));
      await h.dispose();
      await h2.dispose();
    });
  });

  group('listening record', () {
    test('half the track is a play; "now playing" is sent once', () async {
      final h = await Harness.start();
      await h.engine.playTracks(h.tracks);
      h.backend.emitState(const BackendState(
          playing: true, processing: BackendProcessing.ready));
      h.clock.advance(const Duration(seconds: 110)); // > 100 s of 200 s
      h.backend.finishCurrent();
      await h.settle();

      expect(h.recorder.nowPlayingIds, ['t1']);
      expect(h.recorder.plays.single.id, 't1');
      expect(h.recorder.plays.single.listened.inSeconds, 110);
      await h.dispose();
    });

    test(
        'a whole song played from the service stream is a play too, '
        'filed by what it is (it used to count for nothing)', () async {
      final h = await Harness.start();
      await h.engine.playPreviews([
        PreviewTrack(
          id: 'cat-9',
          title: 'Creep',
          uri: Uri.parse('http://svc/api/play/abc/audio'),
          artist: 'Radiohead',
          duration: const Duration(minutes: 4),
          fullSong: true,
        ),
      ]);
      h.backend.emitState(const BackendState(
          playing: true, processing: BackendProcessing.ready));
      h.clock.advance(const Duration(seconds: 150));
      h.backend.finishCurrent();
      await h.settle();

      expect(h.recorder.plays.single.id, 'cat-9');
      expect(h.recorder.nowPlayingIds, isEmpty,
          reason: 'its id means nothing to the music server');
      await h.dispose();
    });

    test('skipping after a few seconds is not a play', () async {
      final h = await Harness.start();
      await h.engine.playTracks(h.tracks);
      h.clock.advance(const Duration(seconds: 12));
      await h.engine.skipNext();
      expect(h.recorder.plays, isEmpty);
      await h.dispose();
    });

    test('paused time does not count', () async {
      final h = await Harness.start();
      await h.engine.playTracks(h.tracks);
      h.clock.advance(const Duration(seconds: 20));
      await h.engine.pause();
      h.clock.advance(const Duration(minutes: 30)); // phone in a pocket
      await h.engine.play();
      h.clock.advance(const Duration(seconds: 20));
      await h.engine.skipNext();
      expect(h.recorder.plays, isEmpty, reason: '40 s of a 200 s track');
      await h.dispose();
    });
  });

  group(
      'Next while the next song of an instant-play run is still being fetched',
      () {
    PreviewTrack streamed(String id) => PreviewTrack(
          id: id,
          title: 'Song $id',
          uri: Uri.parse('http://svc/api/play/$id/audio'),
          artist: 'Pause',
          duration: const Duration(minutes: 3),
          fullSong: true,
        );

    // Found on the phone (J-05, 2026-10-17): the person tapped song 3 of an
    // EP and pressed Next ten seconds later; the next song was still being
    // fetched, so the engine took it for the end of the queue, paused and
    // rewound the music.
    test('the music keeps playing, and the song that arrives is started',
        () async {
      final h = await Harness.start();
      h.moreComing = true;
      await h.engine.playPreviews([streamed('a')]);
      h.backend.emitState(const BackendState(
          playing: true, processing: BackendProcessing.ready));
      h.backend.calls.clear();

      await h.engine.skipNext();

      expect(h.backend.calls, isNot(contains('pause')),
          reason: 'nothing to pause: the next song is on its way');
      expect(h.currentId, 'a');

      await h.engine.addStreamToQueue(streamed('b'));
      await h.settle();

      expect(h.currentId, 'b', reason: 'the Next that was asked for happens');
      await h.dispose();
    });

    test('with nothing more coming it is the end of the queue, as before',
        () async {
      final h = await Harness.start();
      h.moreComing = false;
      await h.engine.playPreviews([streamed('a')]);
      h.backend.emitState(const BackendState(
          playing: true, processing: BackendProcessing.ready));
      h.backend.calls.clear();

      await h.engine.skipNext();

      expect(h.backend.calls, contains('pause'));
      await h.dispose();
    });

    test('a song added later by the person does not start by itself', () async {
      final h = await Harness.start();
      h.moreComing = true;
      await h.engine.playPreviews([streamed('a')]);
      h.backend.emitState(const BackendState(
          playing: true, processing: BackendProcessing.ready));
      await h.engine.skipNext(); // waiting for the next song of the run
      h.moreComing = false; // the run ended without it (the song failed)

      await h.engine.addStreamToQueue(streamed('x'));
      await h.settle();

      expect(h.currentId, 'a');
      await h.dispose();
    });

    test('pausing cancels the wait', () async {
      final h = await Harness.start();
      h.moreComing = true;
      await h.engine.playPreviews([streamed('a')]);
      h.backend.emitState(const BackendState(
          playing: true, processing: BackendProcessing.ready));
      await h.engine.skipNext();
      await h.engine.pause();

      await h.engine.addStreamToQueue(streamed('b'));
      await h.settle();

      expect(h.currentId, 'a');
      await h.dispose();
    });
  });

  group('catalogue previews', () {
    List<PreviewTrack> previews(int n) => [
          for (var i = 1; i <= n; i++)
            PreviewTrack(
              id: 'p$i',
              title: 'Sample $i',
              uri: Uri.parse('https://cdn/p$i.mp3'),
              artist: 'Artist',
              album: 'Album',
              imageUrl: 'https://cdn/cover.jpg',
              duration: const Duration(seconds: 30),
            ),
        ];

    test('a run of samples plays in order from the chosen one', () async {
      final h = await Harness.start();
      await h.engine.playPreviews(previews(4),
          startIndex: 1, sourceName: 'Album', sourceId: 'catalogue-album:9');

      expect(h.currentId, 'p2');
      expect(h.engine.snapshot.sourceName, 'Album');
      expect(h.engine.snapshot.queueLength, 4);
      expect(h.window, ['p2', 'p3']);
      expect(h.backend.sources.first.uri, Uri.parse('https://cdn/p2.mp3'));

      h.backend.finishCurrent();
      await h.settle();
      expect(h.currentId, 'p3');
      expect(h.window, ['p3', 'p4']);
      await h.dispose();
    });

    test('samples are never scrobbled or recorded as listening history',
        () async {
      final h = await Harness.start();
      await h.engine.playPreviews(previews(2));
      h.backend.emitState(const BackendState(
          playing: true, processing: BackendProcessing.ready));
      h.clock.advance(const Duration(seconds: 29));
      h.backend.finishCurrent();
      await h.settle();

      expect(h.currentId, 'p2');
      expect(h.recorder.nowPlayingIds, isEmpty);
      expect(h.recorder.plays, isEmpty);
      await h.dispose();
    });

    test('an out-of-range start index is clamped, an empty run is ignored',
        () async {
      final h = await Harness.start();
      await h.engine.playPreviews(previews(3), startIndex: 99);
      expect(h.currentId, 'p3');

      await h.engine.playPreviews(const []);
      expect(h.currentId, 'p3', reason: 'nothing replaced the queue');
      await h.dispose();
    });

    test('the single-sample helper still replaces the queue with one item',
        () async {
      final h = await Harness.start();
      await h.engine.playTracks(h.tracks);
      await h.engine.playPreview(
        id: 'solo',
        title: 'Solo',
        uri: Uri.parse('https://cdn/solo.mp3'),
      );
      expect(h.currentId, 'solo');
      expect(h.engine.snapshot.queueLength, 1);
      expect(h.engine.snapshot.sourceId, 'preview:solo');
      await h.dispose();
    });

    test('a restart does not bring a sample queue back', () async {
      final store = MemoryPlaybackStateStore();
      final h = await Harness.start(store: store);
      await h.engine.playPreviews(previews(3));
      await h.engine.pause();
      await h.settle();

      final h2 = await Harness.start(store: store);
      await h2.engine.restore();
      expect(h2.engine.snapshot.track, isNull,
          reason: 'ids that are not in the library are dropped');
      await h.dispose();
      await h2.dispose();
    });
  });

  group('loudness', () {
    test('ReplayGain attenuates through the player volume', () async {
      final h = await Harness.start();
      h.replayGain = const ReplayGainSettings(mode: ReplayGainMode.track);
      h.tracks = [
        trackRow('t1', rgTrackGain: -6.0),
        trackRow('t2', rgTrackGain: -12.0),
      ];
      await h.engine.playTracks(h.tracks);
      expect(h.backend.volume, closeTo(0.501, 0.01));

      h.backend.finishCurrent();
      await h.settle();
      expect(h.backend.volume, closeTo(0.251, 0.01));
      await h.dispose();
    });

    test('a quiet track is boosted through the effects layer', () async {
      final h = await Harness.start();
      h.replayGain = const ReplayGainSettings(
          mode: ReplayGainMode.track,
          preampDb: 0,
          untaggedDb: 0,
          allowBoost: true);
      await h.engine
          .playTracks([trackRow('q', rgTrackGain: 4.0, rgTrackPeak: 0.3)]);
      expect(h.backend.volume, 1);
      expect(h.effects.boosts.last, closeTo(4.0, 1e-9));
      await h.dispose();
    });

    test(
        'by default levelling only turns loud songs down: a quiet one is not boosted',
        () async {
      final h = await Harness.start();
      h.replayGain = const ReplayGainSettings(mode: ReplayGainMode.track);
      await h.engine
          .playTracks([trackRow('q', rgTrackGain: 4.0, rgTrackPeak: 0.3)]);
      expect(h.backend.volume, 1);
      expect(h.effects.boosts.last, 0,
          reason: 'the volume buttons are the only way to louder');
      await h.dispose();
    });

    test(
        'with levelling off the player volume is exactly 1 through play, next, previous, seek, pause and a failing song',
        () async {
      final h = await Harness.start();
      h.tracks = [
        trackRow('t1', rgTrackGain: -9),
        trackRow('t2', rgTrackGain: -14),
        trackRow('t3'),
      ];
      await h.engine.playTracks(h.tracks);
      expect(h.backend.volume, 1);
      await h.engine.skipNext();
      expect(h.backend.volume, 1);
      await h.engine.skipPrevious();
      expect(h.backend.volume, 1);
      await h.engine.seek(const Duration(seconds: 30));
      expect(h.backend.volume, 1);
      await h.engine.pause();
      expect(h.backend.volume, 1);
      await h.engine.play();
      h.backend.failCurrent();
      await h.settle();
      expect(h.backend.volume, 1);
      expect(h.effects.boosts.every((b) => b == 0), isTrue);
      await h.dispose();
    });

    test(
        'the volume a song was levelled to comes back after the sleep timer faded it',
        () async {
      final h = await Harness.start();
      h.replayGain = const ReplayGainSettings(mode: ReplayGainMode.track);
      await h.engine.playTracks([
        trackRow('t1', rgTrackGain: -6.0),
        trackRow('t2', rgTrackGain: -6.0)
      ]);
      final levelled = h.backend.volume;
      expect(levelled, closeTo(0.501, 0.01));
      await h.engine.setSleepTimer(const Duration(seconds: 12));
      final ticker = h.timers.last;
      for (var i = 0; i < 6; i++) {
        ticker.fire();
      }
      expect(h.backend.volume, lessThan(levelled), reason: 'fading');
      await h.engine.setSleepTimer(null);
      expect(h.backend.volume, closeTo(levelled, 1e-9),
          reason: 'back to the levelled volume, not 1 and not the faded one');
      await h.dispose();
    });

    test('off leaves volume at unity', () async {
      final h = await Harness.start();
      await h.engine
          .playTracks([trackRow('t1', rgTrackGain: -9)]); // ReplayGainMode.off
      expect(h.backend.volume, 1);
      await h.dispose();
    });
  });

  group('sleep timer', () {
    test('counts down, fades, then pauses', () async {
      final h = await Harness.start();
      await h.engine.playTracks(h.tracks);
      await h.engine.setSleepTimer(const Duration(seconds: 12));
      expect(h.engine.sleepTimer.mode, SleepTimerMode.countdown);
      final ticker = h.timers.last;

      for (var i = 0; i < 5; i++) {
        ticker.fire(); // 11 .. 7 s
      }
      expect(h.engine.sleepTimer.remaining, const Duration(seconds: 7));
      expect(h.backend.volume, lessThan(1), reason: 'fading in last 10 s');
      expect(h.backend.state.playing, isTrue);

      for (var i = 0; i < 7; i++) {
        ticker.fire();
      }
      await h.settle();
      expect(h.backend.state.playing, isFalse);
      expect(h.backend.volume, 1, reason: 'volume restored for next time');
      expect(h.engine.sleepTimer.mode, SleepTimerMode.off);
      await h.dispose();
    });

    test('cancelling restores volume and mode', () async {
      final h = await Harness.start();
      await h.engine.playTracks(h.tracks);
      await h.engine.setSleepTimer(const Duration(seconds: 8));
      h.timers.last.fire();
      await h.engine.setSleepTimer(null);
      expect(h.engine.sleepTimer.mode, SleepTimerMode.off);
      expect(h.backend.volume, 1);
      expect(h.timers.last.cancelled, isTrue);
      await h.dispose();
    });

    test('end of track: no next source, pauses on completion, cursor advances',
        () async {
      final h = await Harness.start();
      await h.engine.playTracks(h.tracks);
      await h.engine.setSleepAtEndOfTrack(true);
      expect(h.window, ['t1'], reason: 'never reaches the next track');

      h.backend.finishCurrent();
      await h.settle();
      expect(h.backend.state.playing, isFalse);
      expect(h.currentId, 't2', reason: 'ready to continue tomorrow');
      expect(h.engine.sleepTimer.mode, SleepTimerMode.off);
      await h.dispose();
    });
  });

  group('regressions', () {
    test('a "completed" event with nothing loaded never starts playback',
        () async {
      // Seen on device: warming up the platform player with an empty
      // playlist reports "completed", and the engine (with a restored
      // queue) advanced and began playing on its own.
      final store = MemoryPlaybackStateStore();
      final h = await Harness.start(store: store);
      await h.engine.playTracks(h.tracks, startIndex: 1);
      await h.engine.pause();
      await h.settle();

      final h2 = await Harness.start(store: store);
      await h2.engine.restore();
      h2.backend.emitState(const BackendState(
          playing: false, processing: BackendProcessing.completed));
      await h2.settle();

      expect(h2.currentId, 't2', reason: 'cursor did not move');
      expect(h2.backend.state.playing, isFalse);
      expect(h2.backend.sources, isEmpty);
      await h.dispose();
      await h2.dispose();
    });

    test(
        'the platform player announcing "item 0" after a restore does not skip a track',
        () async {
      // Seen on the device (J-11): after the app was killed, the queue came back one track further than it was, and the
      // old position was then applied to the wrong song. Nothing of ours is loaded at that moment, so an index event
      // can only be the player's own start-up - never a gapless advance.
      final store = MemoryPlaybackStateStore();
      final h = await Harness.start(store: store);
      await h.engine.playTracks(h.tracks, startIndex: 1);
      h.backend.emitPosition(const Duration(seconds: 93));
      await h.engine.pause();
      await h.settle();

      final h2 = await Harness.start(store: store, library: {
        for (final t in h.tracks) t.id: t,
      });
      await h2.engine.restore();
      h2.backend.emitIndex(0);
      await h2.settle();

      expect(h2.currentId, 't2', reason: 'the cursor did not move');
      expect(h2.engine.snapshot.position, const Duration(seconds: 93));

      await h2.engine.play();
      expect(h2.currentId, 't2');
      expect(h2.window, ['t2', 't3']);
      expect(h2.backend.position, const Duration(seconds: 93),
          reason: 'the saved position belongs to this song');
      await h.dispose();
      await h2.dispose();
    });

    test('pausing a finished player does not advance twice', () async {
      final h = await Harness.start(tracks: 3);
      await h.engine.playTracks(h.tracks, startIndex: 2);
      h.backend.finishCurrent(); // last track ends: queue over
      await h.settle();
      await h.engine.pause();
      await h.engine.pause();
      await h.settle();
      expect(h.currentId, 't3');
      await h.dispose();
    });
  });

  group('misc', () {
    test('speed is clamped and forwarded', () async {
      final h = await Harness.start();
      await h.engine.playTracks(h.tracks);
      await h.engine.setSpeed(5);
      expect(h.engine.speed, 2.0);
      expect(h.backend.speed, 2.0);
      await h.dispose();
    });

    test('toggle play/pause maps to the backend', () async {
      final h = await Harness.start();
      await h.engine.playTracks(h.tracks);
      await h.engine.togglePlayPause();
      expect(h.backend.state.playing, isFalse);
      await h.engine.togglePlayPause();
      expect(h.backend.state.playing, isTrue);
      await h.dispose();
    });

    test('snapshots only fire on real changes, not on position ticks',
        () async {
      final h = await Harness.start();
      await h.engine.playTracks(h.tracks);
      await h.settle();
      var count = 0;
      final sub = h.engine.snapshots.listen((_) => count++);
      for (var i = 0; i < 50; i++) {
        h.backend.emitPosition(Duration(seconds: i));
      }
      await h.settle();
      expect(count, 0);
      await sub.cancel();
      await h.dispose();
    });

    test('the queue stream publishes order and cursor', () async {
      final h = await Harness.start();
      final seen = <QueueSnapshot>[];
      h.engine.queueStream.listen(seen.add);
      await h.engine.playTracks(h.tracks, startIndex: 1);
      await h.settle();
      expect(seen.last.currentIndex, 1);
      expect(seen.last.items.length, 5);
      expect(seen.last.upNext.length, 3);
      await h.dispose();
    });
  });

  // docs/23, B8: every command used to wait in one queue, so on a slow link the
  // lock-screen pause did nothing until the load finished or timed out.
  group('a slow load', () {
    Future<void> untilLoading(Harness h) async {
      final deadline = DateTime.now().add(const Duration(seconds: 5));
      while (!h.backend.calls.any((c) => c.startsWith('setSources'))) {
        if (DateTime.now().isAfter(deadline)) fail('the load never started');
        await Future<void>.delayed(const Duration(milliseconds: 5));
      }
    }

    test('pause returns at once and the song never starts', () async {
      final h = await Harness.start();
      h.backend.setSourcesGate = Completer<void>();
      final started = h.engine.playTracks(h.tracks);
      await untilLoading(h);

      await h.engine.pause().timeout(const Duration(seconds: 1),
          onTimeout: () => fail('pause waited behind the load'));
      h.backend.setSourcesGate!.complete();
      await started;

      expect(h.backend.state.playing, isFalse,
          reason: 'the person paused while it was still loading');
      await h.dispose();
    });

    test('play after that pause plays', () async {
      final h = await Harness.start();
      h.backend.setSourcesGate = Completer<void>();
      final started = h.engine.playTracks(h.tracks);
      await untilLoading(h);
      await h.engine.pause();
      h.backend.setSourcesGate!.complete();
      await started;

      await h.engine.play();

      expect(h.backend.state.playing, isTrue);
      await h.dispose();
    });

    test('the play/pause button pauses a load, it does not queue another play',
        () async {
      final h = await Harness.start();
      h.backend.setSourcesGate = Completer<void>();
      final started = h.engine.playTracks(h.tracks);
      await untilLoading(h);

      await h.engine.togglePlayPause().timeout(const Duration(seconds: 1),
          onTimeout: () => fail('toggle waited behind the load'));
      h.backend.setSourcesGate!.complete();
      await started;

      expect(h.backend.state.playing, isFalse);
      await h.dispose();
    });

    test('a song tapped before the pause does not start either', () async {
      // Tap A (loading), tap B (waiting its turn), press pause: B must not play.
      final h = await Harness.start();
      h.backend.setSourcesGate = Completer<void>();
      final a = h.engine.playTracks(h.tracks.sublist(0, 2));
      await untilLoading(h);
      final b = h.engine.playTracks(h.tracks.sublist(2, 4));

      await h.engine.pause();
      h.backend.setSourcesGate!.complete();
      await Future.wait([a, b]);

      expect(h.backend.state.playing, isFalse);
      expect(h.currentId, 't3', reason: 'B is the current song, just paused');
      await h.dispose();
    });

    test('a song tapped after the pause plays', () async {
      final h = await Harness.start();
      h.backend.setSourcesGate = Completer<void>();
      final a = h.engine.playTracks(h.tracks.sublist(0, 2));
      await untilLoading(h);
      await h.engine.pause();
      final b = h.engine.playTracks(h.tracks.sublist(2, 4));

      h.backend.setSourcesGate!.complete();
      await Future.wait([a, b]);

      expect(h.backend.state.playing, isTrue);
      expect(h.currentId, 't3');
      await h.dispose();
    });

    test('queue edits still wait their turn behind the load', () async {
      final h = await Harness.start();
      h.backend.setSourcesGate = Completer<void>();
      final started = h.engine.playTracks(h.tracks);
      await untilLoading(h);
      final skipped = h.engine.skipNext();

      h.backend.setSourcesGate!.complete();
      await Future.wait([started, skipped]);

      expect(h.currentId, 't2', reason: 'ordered commands keep their order');
      await h.dispose();
    });
  });

  // docs/23, B11: unchecked casts on the saved queue threw inside the command
  // queue, which failed the whole engine provider: no playback at every launch.
  group('a load that never ends, and no connection (E1, E2)', () {
    test('a load that never finishes gives up, says so, and the next tap works',
        () async {
      // The network went away in the middle of a load: it neither finishes nor fails.
      final h =
          await Harness.start(loadTimeout: const Duration(milliseconds: 80));
      h.backend.setSourcesGate = Completer<void>();

      await h.engine.playTracks(h.tracks.sublist(0, 2)).timeout(
          const Duration(seconds: 2),
          onTimeout: () => fail('the stuck load held the engine for good'));
      expect(h.notices.any((n) => n.isError), isTrue,
          reason: 'the person is told');
      expect(h.backend.state.playing, isFalse);

      h.backend.setSourcesGate = null; // the network is back
      await h.engine.playTracks(h.tracks.sublist(2, 4));

      expect(h.currentId, 't3');
      expect(h.backend.state.playing, isTrue);
      await h.dispose();
    });

    test('a newer tap does not wait for a load that is stuck: the latest wins',
        () async {
      // The limit is far away on purpose: only the newer tap can end the stuck load in time.
      final h = await Harness.start(loadTimeout: const Duration(seconds: 60));
      h.backend.setSourcesGate = Completer<void>();
      final first = h.engine.playTracks(h.tracks.sublist(0, 2));
      await h.settle();

      h.backend.setSourcesGate = null; // the network is back for the next load
      await h.engine.playTracks(h.tracks.sublist(2, 4)).timeout(
          const Duration(seconds: 2),
          onTimeout: () => fail('the new tap waited behind the stuck load'));
      await first;

      expect(h.currentId, 't3');
      expect(h.backend.state.playing, isTrue);
      await h.dispose();
    });

    test('after a load gave up, Play tries again', () async {
      final h =
          await Harness.start(loadTimeout: const Duration(milliseconds: 80));
      h.backend.setSourcesGate = Completer<void>();
      await h.engine.playTracks(h.tracks.sublist(0, 2));
      h.backend.setSourcesGate = null;

      await h.engine.play();

      expect(h.currentId, 't1');
      expect(h.backend.state.playing, isTrue);
      expect(h.backend.setSourcesCount, 2);
      await h.dispose();
    });

    test(
        'offline, a tap on a song that is not downloaded says so and changes nothing (Q30, D-42)',
        () async {
      final h = await Harness.start();
      h.reachable = false;

      await h.engine.playTracks(h.tracks.sublist(0, 3));

      expect(h.backend.setSourcesCount, 0,
          reason: 'it cannot play: do not try');
      expect(h.currentId, isNull,
          reason: 'a song that cannot play does not take the queue over, and '
              'nothing hops to the next one');
      expect(h.backend.state.playing, isFalse);
      expect(h.notices, hasLength(1));
      expect(h.notices.single.message, 'Not downloaded. Connect to play it.');
      await h.dispose();
    });

    test(
        'the server was found out of reach and is back: a tap on a song that is not downloaded asks it once and plays (the refusal does not outlive the outage)',
        () async {
      final h = await Harness.start();
      h.reachable = false;
      h.network = true;
      h.serverUp = true;

      await h.engine.playTracks(h.tracks.sublist(0, 3));

      expect(h.currentId, 't1');
      expect(h.backend.state.playing, isTrue);
      expect(h.serverAsked, 1);
      expect(h.notices, isEmpty);
      await h.dispose();
    });

    test(
        'the server is still out of reach: the tap is refused, and taps in the same few seconds do not each ask it again',
        () async {
      final h = await Harness.start();
      h.reachable = false;
      h.network = true;
      h.serverUp = false;

      await h.engine.playTracks(h.tracks.sublist(0, 3));
      await h.engine.playTracks(h.tracks.sublist(0, 3));
      await h.engine.playTracks(h.tracks.sublist(1, 3));

      expect(h.backend.setSourcesCount, 0);
      expect(h.notices.first.message, 'Not downloaded. Connect to play it.');
      expect(h.serverAsked, 1);
      await h.dispose();
    });

    test(
        'offline, Play on a list whose first song is not downloaded starts at the first one that is (field test 2026-10-31: one missing song and nothing played)',
        () async {
      final h = await Harness.start();
      h.resolver.local.addAll(['t2', 't3']);
      h.reachable = false;

      await h.engine.playTracks(h.tracks.sublist(0, 3), skipUnavailable: true);

      expect(h.currentId, 't2');
      expect(h.backend.state.playing, isTrue);
      expect(h.notices, isEmpty);
      await h.dispose();
    });

    test(
        'offline, Shuffle on a partly downloaded list only ever starts on a downloaded song',
        () async {
      for (var round = 0; round < 6; round++) {
        final h = await Harness.start();
        h.resolver.local.addAll(['t2', 't3']);
        h.reachable = false;

        await h.engine.playTracks(h.tracks.sublist(0, 3),
            shuffle: true, skipUnavailable: true);

        expect(['t2', 't3'], contains(h.currentId));
        await h.dispose();
      }
    });

    test(
        'offline, Play on a list with nothing downloaded says so and changes nothing',
        () async {
      final h = await Harness.start();
      h.reachable = false;

      await h.engine.playTracks(h.tracks.sublist(0, 3), skipUnavailable: true);

      expect(h.currentId, isNull);
      expect(h.notices.map((n) => n.message),
          ['Not downloaded. Connect to play it.']);
      await h.dispose();
    });

    test(
        'offline, A ends and the song behind it is not downloaded: the next downloaded one plays and is the one that is shown',
        () async {
      final h = await Harness.start();
      h.resolver.local.addAll(['t1', 't3']);
      h.reachable = false;
      await h.engine.playTracks(h.tracks.sublist(0, 3));
      expect(h.currentId, 't1');

      h.backend.finishCurrent();
      await pumpEventQueue();

      expect(h.currentId, 't3', reason: 't2 is not on the phone');
      expect(h.backend.state.playing, isTrue);
      expect(h.engine.snapshot.track?.id, 't3',
          reason: 'what is shown is what plays');
      await h.dispose();
    });

    test(
        'offline, that tap leaves the downloaded song that is playing playing, and the queue as it was (Q30, D-42)',
        () async {
      final h = await Harness.start();
      h.resolver.local.add('t1');
      h.reachable = false;
      await h.engine.playTracks(h.tracks.sublist(0, 1));
      expect(h.currentId, 't1');
      expect(h.backend.state.playing, isTrue);
      final loads = h.backend.setSourcesCount;
      h.notices.clear();

      await h.engine
          .playTracks(h.tracks.sublist(1, 3)); // t2 is not on the phone

      expect(h.currentId, 't1', reason: 'what was playing is still current');
      expect(h.backend.state.playing, isTrue,
          reason: 'and the music did not stop for a song that cannot play');
      expect(h.backend.setSourcesCount, loads, reason: 'nothing was loaded');
      expect(h.notices.map((n) => n.message),
          ['Not downloaded. Connect to play it.']);
      await h.dispose();
    });

    test(
        'and nothing starts by itself when the network returns, whether or not something was playing (Q30, D-42)',
        () async {
      final h = await Harness.start();
      h.resolver.local.add('t1');
      h.reachable = false;
      await h.engine.playTracks(h.tracks.sublist(0, 1));
      await h.engine.playTracks(h.tracks.sublist(1, 3)); // refused
      final loads = h.backend.setSourcesCount;

      h.reachable = true;
      await h.engine.networkChanged(online: true);
      await h.settle();

      expect(h.currentId, 't1');
      expect(h.backend.setSourcesCount, loads,
          reason: 'the refused song was never asked for again');

      final alone = await Harness.start();
      alone.reachable = false;
      await alone.engine.playTracks(alone.tracks.sublist(0, 3)); // refused
      alone.reachable = true;
      await alone.engine.networkChanged(online: true);
      await alone.settle();
      expect(alone.currentId, isNull);
      expect(alone.backend.setSourcesCount, 0);
      expect(alone.backend.state.playing, isFalse);
      await h.dispose();
      await alone.dispose();
    });

    test('offline, a downloaded song plays', () async {
      final h = await Harness.start();
      h.reachable = false;
      h.resolver.local.add('t1');

      await h.engine.playTracks(h.tracks.sublist(0, 3));

      expect(h.currentId, 't1');
      expect(h.backend.state.playing, isTrue);
      expect(h.notices, isEmpty);
      await h.dispose();
    });

    test(
        'offline, the next song to play is not preloaded when it is not downloaded',
        () async {
      final h = await Harness.start();
      h.resolver.local.addAll(['t1', 't3']);
      await h.engine.playTracks(h.tracks.sublist(0, 3));
      expect(h.window, ['t1', 't2'], reason: 'online it is preloaded as usual');

      h.reachable = false;
      await h.engine.playTracks(h.tracks.sublist(0, 3));

      expect(h.window, ['t1'],
          reason: 'offline t2 cannot play, so it is not queued behind t1');
      await h.dispose();
    });

    test('offline, Next skips songs that are not downloaded', () async {
      final h = await Harness.start();
      h.resolver.local.addAll(['t1', 't3']);
      h.reachable = false;
      await h.engine.playTracks(h.tracks.sublist(0, 3));

      await h.engine.skipNext();

      expect(h.currentId, 't3');
      expect(h.backend.state.playing, isTrue);
      await h.dispose();
    });

    test(
        'offline, when no later song is downloaded Next says so and keeps playing nothing new',
        () async {
      final h = await Harness.start();
      h.resolver.local.add('t1');
      h.reachable = false;
      await h.engine.playTracks(h.tracks.sublist(0, 3));
      h.notices.clear();

      await h.engine.skipNext();

      expect(h.currentId, isNot('t2'),
          reason: 'never moves onto a song that cannot play');
      expect(h.notices, hasLength(1));
      await h.dispose();
    });

    test('a song that failed while the network is down is not skipped',
        () async {
      final h = await Harness.start();
      await h.engine.playTracks(h.tracks.sublist(0, 3));
      h.reachable = false; // the network goes away while the song streams

      h.backend.failCurrent();
      await h.settle();
      h.backend.failCurrent();
      await h.settle();

      expect(h.currentId, 't1',
          reason: 'it is waiting for the network, not broken');
      expect(h.notices.where((n) => n.isError).length, lessThanOrEqualTo(1));
      await h.dispose();
    });

    test(
        'when the network returns, a song that lost it in the middle of playing carries on by itself',
        () async {
      final h = await Harness.start();
      await h.engine.playTracks(h.tracks.sublist(0, 3));
      h.reachable = false; // the network goes away while the song streams
      h.backend.failCurrent();
      await h.settle();
      final loads = h.backend.setSourcesCount;
      expect(h.backend.state.playing, isFalse);

      h.reachable = true;
      await h.engine.networkChanged(online: true);
      await h.settle();

      expect(h.currentId, 't1');
      expect(h.backend.state.playing, isTrue);
      expect(h.backend.setSourcesCount, loads + 1);
      await h.dispose();
    });

    test(
        'the network returning does not restart what the person paused meanwhile',
        () async {
      final h = await Harness.start();
      await h.engine.playTracks(h.tracks.sublist(0, 3));
      h.reachable = false; // the network goes away while the song streams
      h.backend.failCurrent();
      await h.settle();
      final loads = h.backend.setSourcesCount;
      await h.engine.pause(); // "stop the music": the person changed their mind

      h.reachable = true;
      await h.engine.networkChanged(online: true);
      await h.settle();

      expect(h.backend.state.playing, isFalse);
      expect(h.backend.setSourcesCount, loads);
      await h.dispose();
    });

    // ------------------------------------------------ the server does not answer (docs/33 G-1)

    test(
        'PB-F7: a song that fails while the server does not answer is waited for and never hopped over',
        () async {
      final h = await Harness.start();
      await h.engine.playTracks(h.tracks.sublist(0, 3));
      h.serverUp = false; // the phone has a network, the server has gone

      h.backend.failCurrent();
      await h.settle();

      expect(h.currentId, 't1', reason: 'the song is not broken');
      expect(h.backend.state.playing, isFalse);
      expect(h.notices.where((n) => n.isError), isEmpty,
          reason: 'no "Could not play" notice for a server that is away');
      expect(h.notices.last.message, 'Waiting for your server.');
      expect(h.serverAsked, greaterThan(0),
          reason: 'one fresh look at the server before judging the song');
      await h.dispose();
    });

    test(
        'PB-F8: when the server answers again the song carries on from where it stopped, by itself',
        () async {
      final h = await Harness.start();
      await h.engine.playTracks(h.tracks.sublist(0, 3));
      h.backend.emitPosition(const Duration(seconds: 42));
      h.serverUp = false;
      h.backend.failCurrent();
      await h.settle();
      final loadsWhileWaiting = h.backend.setSourcesCount;

      await Future<void>.delayed(const Duration(milliseconds: 60));
      expect(h.backend.setSourcesCount, loadsWhileWaiting,
          reason: 'nothing is loaded while the server is away');
      expect(h.serverAsked, greaterThan(2),
          reason: 'it keeps asking, by itself');

      h.serverUp = true; // a restart takes 2 to 5 seconds
      await Future<void>.delayed(const Duration(milliseconds: 60));
      await h.settle();

      expect(h.currentId, 't1');
      expect(h.backend.state.playing, isTrue);
      expect(h.backend.setSourcesCount, loadsWhileWaiting + 1);
      expect(h.backend.calls.lastWhere((c) => c.startsWith('setSources')),
          contains('+42s'),
          reason: 'from the second it stopped at');
      await h.dispose();
    });

    test(
        'PB-F7: a tap while the server does not answer waits for it and plays by itself when it is back',
        () async {
      final h = await Harness.start();
      h.resolver.serverAway = true;
      h.serverUp = false;

      await h.engine.playTracks(h.tracks.sublist(0, 3));

      expect(h.backend.setSourcesCount, 0);
      expect(h.currentId, 't1', reason: 'and does not hop to the next one');
      expect(h.notices.last.message, 'Waiting for your server.');
      expect(h.notices.last.isError, isFalse);

      h.resolver.serverAway = false;
      h.serverUp = true;
      await Future<void>.delayed(const Duration(milliseconds: 60));
      await h.settle();

      expect(h.currentId, 't1');
      expect(h.backend.state.playing, isTrue);
      await h.dispose();
    });

    test(
        'the radio is on but there is no data: A ends, B (not downloaded) cannot load and the player hops to C - what is shown is never other than what plays (field test 2026-10-31)',
        () async {
      final h = await Harness.start();
      h.resolver.local.addAll(['t1', 't3']);
      await h.engine.playTracks(h.tracks.sublist(0, 3));
      expect(h.currentId, 't1');
      h.serverUp =
          false; // the phone has a network, the server cannot be reached

      h.backend.finishCurrent(); // A ends, the player moves on to B
      await h.settle();
      h.backend
          .failCurrentAndHop(); // B cannot load, the platform player moves on to C by itself
      await h.settle();
      await Future<void>.delayed(const Duration(milliseconds: 60));
      await h.settle();

      final shown = h.currentId;
      final audible = h.backend.state.playing;
      final source = h.backend.currentUid;
      // Either nothing is audible, or the song that is audible is the song that is shown.
      if (audible) {
        final uri = h.backend.sources
            .firstWhere((src) => src.uid == source)
            .uri
            .toString();
        final audibleId = RegExp(r't\d+').firstMatch(uri)!.group(0);
        expect(shown, audibleId,
            reason: 'audio of $audibleId under the title of $shown');
      }
      await h.dispose();
    });

    test(
        'a failure while the look at the server hangs: the platform player hops on and plays the next song, so the music is held at once - nothing audible under another title (owner, "all covers")',
        () async {
      final h = await Harness.start();
      await h.engine.playTracks(h.tracks.sublist(0, 3));
      expect(h.currentId, 't1');
      h.serverUp = false;
      h.serverGate =
          Completer<void>(); // the look at the server never comes back

      h.backend.failCurrentAndHop(); // the platform player plays t2 by itself
      await pumpEventQueue();

      expect(h.currentId, 't1',
          reason: 'the queue did not move: a failure is not the end of a song');
      expect(h.backend.state.playing, isFalse,
          reason:
              'so nothing may be audible: it would be t2 under the title of t1');
      h.serverGate!.complete();
      await h.settle();
      await h.dispose();
    });

    test(
        'PB-F8: the platform player hopping to the next source after the failure does not move the song',
        () async {
      final h = await Harness.start();
      await h.engine.playTracks(h.tracks.sublist(0, 3));
      h.backend.emitPosition(const Duration(seconds: 42));
      h.serverUp = false;

      h.backend.failCurrentAndHop();
      await h.settle();
      await Future<void>.delayed(const Duration(milliseconds: 40));

      expect(h.currentId, 't1',
          reason: 'a failure is not the end of the song: the queue stays');
      expect(h.backend.state.playing, isFalse);

      h.serverUp = true;
      await Future<void>.delayed(const Duration(milliseconds: 60));
      await h.settle();

      expect(h.currentId, 't1');
      expect(h.backend.state.playing, isTrue);
      expect(h.backend.calls.lastWhere((c) => c.startsWith('setSources')),
          contains('+42s'));
      await h.dispose();
    });

    test(
        'PB-F7: after ten minutes the engine stops asking by itself, and pressing play still tries',
        () async {
      final h = await Harness.start();
      await h.engine.playTracks(h.tracks.sublist(0, 3));
      h.serverUp = false;
      h.backend.failCurrent();
      await h.settle();

      h.clock.advance(const Duration(minutes: 11));
      await Future<void>.delayed(const Duration(milliseconds: 60));
      final asked = h.serverAsked;
      await Future<void>.delayed(const Duration(milliseconds: 60));
      expect(h.serverAsked, asked,
          reason: 'no more questions after ten minutes');

      h.serverUp = true;
      await h.engine.play();
      await h.settle();
      expect(h.backend.state.playing, isTrue);
      expect(h.currentId, 't1');
      await h.dispose();
    });

    test('PB-F7: a downloaded song plays while the server is away', () async {
      final h = await Harness.start();
      h.resolver
        ..local.add('t1')
        ..serverAway = true;
      h.serverUp = false;

      await h.engine.playTracks(h.tracks.sublist(0, 3));

      expect(h.currentId, 't1');
      expect(h.backend.state.playing, isTrue);
      expect(h.notices, isEmpty);
      await h.dispose();
    });

    test(
        'PB-F7: a song that fails while the server answers is still a bad song (one quiet retry, then the next)',
        () async {
      final h = await Harness.start();
      await h.engine.playTracks(h.tracks.sublist(0, 3));

      h.backend.failCurrent();
      await h.settle();
      h.backend.failCurrent();
      await h.settle();

      expect(h.currentId, 't2',
          reason: 'the server answers, so it is the song');
      expect(h.notices.any((n) => n.isError && n.message.contains("Couldn't")),
          isTrue);
      await h.dispose();
    });

    test('PB-F7: pausing while a song waits for its server ends the waiting',
        () async {
      final h = await Harness.start();
      await h.engine.playTracks(h.tracks.sublist(0, 3));
      h.serverUp = false;
      h.backend.failCurrent();
      await h.settle();
      await h.engine.pause(); // the person gives up on it
      final loads = h.backend.setSourcesCount;

      h.serverUp = true;
      await Future<void>.delayed(const Duration(milliseconds: 60));
      await h.settle();

      expect(h.backend.state.playing, isFalse);
      expect(h.backend.setSourcesCount, loads);
      await h.dispose();
    });
  });

  group(
      'a queue of songs that came from the catalogue survives a kill (E6, H39)',
      () {
    final stream = Uri.parse('http://srv:8701/api/play/job1/audio');

    test('a streamed song is found again in the library by what it is',
        () async {
      final store = MemoryPlaybackStateStore();
      final h = await Harness.start(store: store);
      await h.engine.playPreviews([
        PreviewTrack(
            id: 'deezer:42',
            title: 'Weird Fishes',
            uri: stream,
            artist: 'Radiohead',
            album: 'In Rainbows'),
      ]);
      h.backend.emitPosition(const Duration(seconds: 151));
      await h.engine.pause();
      await h.settle();

      // The app is killed; the song has become a library song meanwhile (the server kept it).
      final kept = trackRow('t77');
      String? askedFor;
      final h2 = await Harness.start(
        store: store,
        library: {kept.id: kept},
        findByName: (artist, title, album) async {
          askedFor = '$artist|$title|$album';
          return kept;
        },
      );
      await h2.engine.restore();

      expect(askedFor, 'Radiohead|Weird Fishes|In Rainbows');
      expect(h2.currentId, 't77',
          reason: 'the queue comes back, it is not empty');
      expect(h2.engine.snapshot.position, const Duration(seconds: 151));
      expect(h2.engine.snapshot.isPlaying, isFalse);
      await h.dispose();
      await h2.dispose();
    });

    test('a streamed song the library does not have is dropped, the rest stays',
        () async {
      final store = MemoryPlaybackStateStore();
      final h = await Harness.start(store: store);
      await h.engine.playTracks(h.tracks.sublist(0, 2));
      await h.engine.addToQueue(h.tracks[2]);
      await h.engine.pause();
      await h.settle();

      final h2 = await Harness.start(
        store: store,
        library: {for (final t in h.tracks) t.id: t},
        findByName: (artist, title, album) async => null,
      );
      await h2.engine.restore();

      expect(h2.currentId, 't1');
      expect(h2.engine.debugQueue.items, hasLength(3));
      await h.dispose();
      await h2.dispose();
    });

    test(
        'a lookup that never answers does not hold the restore: the queue still comes back',
        () async {
      final store = MemoryPlaybackStateStore();
      final h = await Harness.start(store: store);
      await h.engine.playTracks(h.tracks.sublist(0, 2));
      await h.engine.playPreviews([
        PreviewTrack(id: 'deezer:9', title: 'T', uri: stream, artist: 'A'),
      ]);
      await h.engine.pause();
      await h.settle();

      // The saved queue is now only the streamed song; give the new phone a library song to restore as well.
      store.value = PersistedPlayback(
        queue: {
          ...store.value!.queue,
          'ids': ['t1', 'deezer:9'],
          'order': [0, 1],
          'cursor': 0,
        },
        positionMs: 0,
      );
      final h2 = await Harness.start(
        store: store,
        library: {for (final t in h.tracks) t.id: t},
        lookupBudget: const Duration(milliseconds: 100),
        findByName: (artist, title, album) =>
            Completer<TrackRow?>().future, // the network is gone: never answers
      );
      await h2.engine.restore().timeout(const Duration(seconds: 2),
          onTimeout: () => fail('the restore waited for the lookup'));

      expect(h2.currentId, 't1');
      expect(h2.engine.debugQueue.items, hasLength(1),
          reason: 'the song that could not be found is left out');
      await h.dispose();
      await h2.dispose();
    });

    test('a library song is saved by its id only, a streamed one also by name',
        () async {
      final store = MemoryPlaybackStateStore();
      final h = await Harness.start(store: store);
      await h.engine.playTracks(h.tracks.sublist(0, 1));
      await h.engine.pause();
      await h.settle();
      expect(store.value!.queue['named'], isEmpty);

      await h.engine.playPreviews([
        PreviewTrack(id: 'deezer:1', title: 'T', uri: stream, artist: 'A'),
      ]);
      await h.engine.pause();
      await h.settle();
      expect((store.value!.queue['named'] as Map).keys, ['deezer:1']);
      await h.dispose();
    });
  });

  group('a damaged saved queue', () {
    Future<Harness> startWith(Map<String, Object?> queue) async {
      final store = MemoryPlaybackStateStore()
        ..value = PersistedPlayback(queue: queue, positionMs: 1000);
      return Harness.start(store: store);
    }

    const damaged = <String, Map<String, Object?>>{
      'ids that are not text': {
        'ids': [1, 2, 3],
        'order': [0, 1, 2],
        'cursor': 0,
      },
      'an order that is not numbers': {
        'ids': ['t1', 't2'],
        'order': ['a', 'b'],
        'cursor': 0,
      },
      'a cursor that is not a number': {
        'ids': ['t1', 't2'],
        'order': [0, 1],
        'cursor': 'first',
      },
      'ids that are not a list': {
        'ids': 'oops',
      },
    };

    damaged.forEach((name, queue) {
      test('$name starts empty, clears the save, and playback still works',
          () async {
        final h = await startWith(queue);

        await h.engine.restore(); // must not throw

        expect(h.engine.snapshot.track, isNull);
        expect(h.store.value, isNull, reason: 'the damaged save is dropped');

        await h.engine.playTracks(h.tracks);
        expect(h.backend.state.playing, isTrue);
        await h.dispose();
      });
    });
  });
}
