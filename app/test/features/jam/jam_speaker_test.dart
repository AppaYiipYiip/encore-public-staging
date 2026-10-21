import 'dart:async';

import 'package:encore/features/jam/jam_providers.dart';
import 'package:encore/features/jam/jam_speaker.dart';
import 'package:encore/features/player/playback_facade.dart';
import 'package:encore_session/encore_session.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/test_app.dart';

/// In a Jam one phone plays and everybody else is a remote (docs/30). The phone
/// that plays does what the Jam says, tells the Jam what really happens (a song
/// ended, somebody paused it from the lock screen) and says out loud when it
/// cannot play a song instead of going quiet.
class _Songs implements JamSongPlayer {
  final List<QueueEntry> played = [];
  final Set<int> cannot = {};

  /// What the player does while the song loads (the real one starts playing
  /// the moment the song is ready, whatever the Jam says).
  void Function()? whileLoading;

  /// The titles this phone is already playing.
  final Set<String> alreadyOn = {};

  /// When set, getting the song takes until it is completed (a fetch).
  Completer<void>? gate;

  /// The songs this phone was asked to get ahead of time.
  final List<int> preloaded = [];

  @override
  Future<void> preload(QueueEntry entry) async => preloaded.add(entry.uid);

  @override
  bool alreadyPlaying(QueueEntry entry) => alreadyOn.contains(entry.title);

  @override
  Future<bool> play(QueueEntry entry) async {
    played.add(entry);
    whileLoading?.call();
    await gate?.future;
    return !cannot.contains(entry.uid);
  }
}

void main() {
  const owner = Member(id: 'owner', name: 'owner', role: Role.host);
  const mia = Member(id: 'mia', name: 'mia');
  QueueEntry song(int uid, {String? title}) => QueueEntry(
      uid: uid,
      trackId: 'lib-$uid',
      addedBy: 'mia',
      title: title ?? 'Song $uid',
      artist: 'Raid');

  late FakePlaybackFacade facade;
  late _Songs songs;
  late List<Command> sent;
  late List<String> said;
  late List<bool> loads;
  late int hubPosition;
  late JamSpeaker speaker;

  setUp(() {
    facade = FakePlaybackFacade();
    songs = _Songs();
    sent = [];
    said = [];
    loads = [];
    hubPosition = 0;
    speaker = JamSpeaker(
      facade: facade,
      songs: songs,
      send: (c) async {
        sent.add(c);
        return true;
      },
      positionNowMs: () => hubPosition,
      notify: said.add,
      onLoading: loads.add,
      silenceOldAfter: const Duration(milliseconds: 10),
    )..attach();
  });

  tearDown(() => speaker.dispose());

  JamSession jam(
    String me, {
    List<QueueEntry> queue = const [],
    int index = 0,
    bool playing = false,
    int rev = 1,
    Anchor anchor = const Anchor(0, 0),
    String? player,
    bool ended = false,
  }) =>
      JamSession(
        phase: ended ? JamPhase.ended : JamPhase.active,
        code: 'AB23CD',
        me: me,
        state: SessionState(
          rev: rev,
          members: const [owner, mia],
          queue: queue,
          index: index,
          playing: playing,
          anchor: anchor,
          playerDeviceId: player,
        ),
      );

  Future<void> settle() => pumpEventQueue();

  PlaybackSnapshot playing(bool value, {bool loading = false}) =>
      PlaybackSnapshot(
        track: const NowPlayingTrack(id: 'x', title: 'x'),
        isPlaying: value,
        isLoading: loading,
      );

  group('who plays', () {
    test('the host\'s phone plays the song the Jam is on', () async {
      await speaker.onSession(jam('owner', queue: [song(1)], playing: true));

      expect(songs.played.single.uid, 1);
    });

    test(
        'a friend\'s phone is a remote: it plays nothing, and is only told to '
        'be quiet once', () async {
      await speaker.onSession(jam('mia', queue: [song(1)], playing: true));
      await speaker
          .onSession(jam('mia', queue: [song(1)], playing: false, rev: 2));

      expect(songs.played, isEmpty);
      expect(facade.calls, ['pause']);
    });

    test(
        'when the host picks a friend\'s phone, the host\'s stops and the friend\'s plays',
        () async {
      final start = jam('owner', queue: [song(1)], playing: true);
      await speaker.onSession(start);
      facade.calls.clear();

      await speaker.onSession(
          jam('owner', queue: [song(1)], playing: true, rev: 2, player: 'mia'));

      expect(facade.calls, contains('pause'));

      final friend = JamSpeaker(
        facade: FakePlaybackFacade(),
        songs: songs,
        send: (c) async => true,
        positionNowMs: () => 0,
        notify: (_) {},
      )..attach();
      addTearDown(friend.dispose);
      songs.played.clear();
      await friend.onSession(
          jam('mia', queue: [song(1)], playing: true, rev: 2, player: 'mia'));
      expect(songs.played.single.uid, 1);
    });
  });

  group('a Jam begun on a song that is already playing', () {
    test('keeps that song going: it is adopted, not started again', () async {
      songs.alreadyOn.add('Song 1');
      hubPosition = 0;
      facade.emitPosition(const Duration(seconds: 80)); // 1:20 into it
      await settle();

      await speaker.onSession(jam('owner',
          queue: [song(1)], playing: true, anchor: const Anchor(0, 0)));
      facade.emitPosition(const Duration(seconds: 80, milliseconds: 250));
      await settle();

      expect(songs.played, isEmpty, reason: 'nothing was loaded');
      expect(sent.whereType<Seek>().single.posMs, greaterThan(79000),
          reason: 'the Jam is told where the music really is');
    });

    test('a paused song stays paused', () async {
      songs.alreadyOn.add('Song 1');

      await speaker.onSession(jam('owner', queue: [song(1)], playing: false));

      expect(songs.played, isEmpty);
      expect(facade.calls, contains('pause'));
    });

    test('a different song is loaded as always', () async {
      songs.alreadyOn.add('Another');

      await speaker.onSession(jam('owner', queue: [song(1)], playing: true));

      expect(songs.played.single.uid, 1);
    });
  });

  group('a phone that does not play', () {
    test('goes quiet when it joins: its own music is not played under the Jam',
        () async {
      await speaker.onSession(jam('mia', queue: [song(1)], playing: true));

      expect(facade.calls, ['pause']);
      expect(songs.played, isEmpty);
    });

    test('only once: it is not paused again at every change of the Jam',
        () async {
      await speaker.onSession(jam('mia', queue: [song(1)], playing: true));
      facade.calls.clear();
      await speaker.onSession(
          jam('mia', queue: [song(1), song(2)], playing: true, rev: 2));

      expect(facade.calls, isEmpty);
    });

    test('and is quiet again after it leaves and joins another', () async {
      await speaker.onSession(jam('mia', queue: [song(1)], playing: true));
      await speaker.onSession(const JamSession());
      facade.calls.clear();

      await speaker.onSession(jam('mia', queue: [song(1)], playing: true));

      expect(facade.calls, ['pause']);
    });
  });

  group('doing what the Jam says', () {
    test('a song that starts paused is paused', () async {
      await speaker.onSession(jam('owner', queue: [song(1)], playing: false));

      expect(songs.played.single.uid, 1);
      expect(facade.calls, contains('pause'));
    });

    test('the same state twice does not start the song again', () async {
      final state = jam('owner', queue: [song(1)], playing: true);
      await speaker.onSession(state);
      await speaker.onSession(state);

      expect(songs.played, hasLength(1));
    });

    test('a skip starts the next song', () async {
      await speaker
          .onSession(jam('owner', queue: [song(1), song(2)], playing: true));
      await speaker.onSession(jam('owner',
          queue: [song(1), song(2)], index: 1, playing: true, rev: 2));

      expect(songs.played.map((e) => e.uid), [1, 2]);
    });

    test('pause and play in the Jam pause and play here', () async {
      await speaker
          .onSession(jam('owner', queue: [song(1)], playing: true, rev: 1));
      facade.calls.clear();

      await speaker
          .onSession(jam('owner', queue: [song(1)], playing: false, rev: 2));
      await speaker
          .onSession(jam('owner', queue: [song(1)], playing: true, rev: 3));

      expect(facade.calls, ['pause', 'play']);
    });

    test('somebody seeking in the Jam moves this phone to that place',
        () async {
      await speaker
          .onSession(jam('owner', queue: [song(1)], playing: true, rev: 1));
      facade.emitPosition(const Duration(seconds: 20));
      await settle();
      facade.calls.clear();

      hubPosition = 90000; // somebody dragged the bar to 1:30
      await speaker.onSession(jam('owner',
          queue: [song(1)],
          playing: true,
          rev: 2,
          anchor: const Anchor(5000, 90000)));

      expect(facade.calls, contains('seek(90000)'));
    });

    test(
        'the Jam confirming the seek a moment later does not move the music '
        'a second time', () async {
      // Seen on a real phone (2026-10-17): tapping a line of the lyrics left
      // three silences before the music was there. The seek is applied the
      // moment it is sent; the hub's answer arrives while the player is still
      // finding the place, and used to move it again.
      await speaker
          .onSession(jam('owner', queue: [song(1)], playing: true, rev: 1));
      facade.emitPosition(const Duration(seconds: 20));
      await settle();
      facade.calls.clear();

      hubPosition = 90000;
      await speaker.onSession(jam('owner',
          queue: [song(1)],
          playing: true,
          rev: 2,
          anchor: const Anchor(5000, 90000)));
      hubPosition = 90400; // the player has not moved yet: it is still loading
      await speaker.onSession(jam('owner',
          queue: [song(1)],
          playing: true,
          rev: 3,
          anchor: const Anchor(5400, 90000)));

      expect(facade.calls.where((c) => c.startsWith('seek')), ['seek(90000)']);
    });

    test('a pause moves the anchor but not the place: no seek', () async {
      await speaker
          .onSession(jam('owner', queue: [song(1)], playing: true, rev: 1));
      facade.emitPosition(const Duration(seconds: 20));
      await settle();
      facade.calls.clear();

      hubPosition = 20400;
      await speaker.onSession(jam('owner',
          queue: [song(1)],
          playing: false,
          rev: 2,
          anchor: const Anchor(5000, 20400)));

      expect(facade.calls.where((c) => c.startsWith('seek')), isEmpty);
    });

    test('an empty queue stops the music', () async {
      await speaker
          .onSession(jam('owner', queue: [song(1)], playing: true, rev: 1));
      facade.calls.clear();

      await speaker.onSession(jam('owner', rev: 2));

      expect(facade.calls, contains('pause'));
    });

    test('when the Jam is over, the music stops', () async {
      await speaker
          .onSession(jam('owner', queue: [song(1)], playing: true, rev: 1));
      facade.calls.clear();

      await speaker.onSession(
          jam('owner', queue: [song(1)], playing: true, rev: 5, ended: true));

      expect(facade.calls, contains('pause'));
    });
  });

  group('telling the Jam what really happens', () {
    test('a song reaching its end is reported once, by its id', () async {
      await speaker
          .onSession(jam('owner', queue: [song(7)], playing: true, rev: 1));
      facade.emit(const PlaybackSnapshot(
        track: NowPlayingTrack(id: 'x', title: 'x'),
        isPlaying: true,
        duration: Duration(minutes: 3),
      ));

      facade.emitPosition(
          const Duration(minutes: 2, seconds: 59, milliseconds: 400));
      facade.emitPosition(
          const Duration(minutes: 2, seconds: 59, milliseconds: 700));
      facade.emitPosition(const Duration(minutes: 3));
      await settle();

      expect(sent.whereType<Ended>().map((e) => e.uid), [7],
          reason:
              'one report, however many times the position ticks at the end');
    });

    test('a song cut short in the middle is not reported', () async {
      hubPosition = 60000; // the Jam agrees about where the music is
      await speaker
          .onSession(jam('owner', queue: [song(7)], playing: true, rev: 1));
      facade.emit(const PlaybackSnapshot(
        track: NowPlayingTrack(id: 'x', title: 'x'),
        isPlaying: true,
        duration: Duration(minutes: 3),
      ));

      facade.emitPosition(const Duration(minutes: 1));
      await settle();

      expect(sent, isEmpty);
    });

    test('pausing from the lock screen pauses the Jam for everybody', () async {
      await speaker
          .onSession(jam('owner', queue: [song(1)], playing: true, rev: 1));
      facade.emit(playing(true));
      await settle();

      facade.emit(playing(false)); // the person pressed pause on the phone
      await settle();

      expect(sent.single, isA<Pause>());
    });

    test('what the Jam itself did is not sent back to it', () async {
      await speaker
          .onSession(jam('owner', queue: [song(1)], playing: true, rev: 1));
      facade.emit(playing(true));
      await speaker
          .onSession(jam('owner', queue: [song(1)], playing: false, rev: 2));
      facade.emit(playing(false)); // the phone obeying the Jam
      await settle();

      expect(sent, isEmpty);
    });

    test(
        'a song that takes a while to start in a paused Jam does not start the Jam by itself',
        () async {
      // Found on the real server, 2026-10-17: a friend pressed Next while the
      // Jam was paused; the host's phone loaded the song (it starts playing
      // the moment it is ready, then is paused), and because loading took
      // longer than the settling window it told the Jam "somebody pressed
      // play on this phone", so every phone showed the Jam playing while the
      // host was silent.
      final slow = JamSpeaker(
        facade: facade,
        songs: songs,
        send: (c) async {
          sent.add(c);
          return true;
        },
        positionNowMs: () => hubPosition,
        notify: said.add,
        settleFor: Duration.zero, // a phone slower than the settling window
      )..attach();
      addTearDown(slow.dispose);
      songs.whileLoading = () => facade.emit(playing(true));

      await slow.onSession(jam('owner', queue: [song(1)], playing: false));
      facade.emit(playing(false)); // the pause that follows the load
      await settle();

      expect(sent, isEmpty);
      expect(facade.calls, contains('pause'));
    });

    test('a song that is still loading is not a pause', () async {
      await speaker
          .onSession(jam('owner', queue: [song(1)], playing: true, rev: 1));

      facade.emit(playing(false, loading: true));
      await settle();

      expect(sent, isEmpty);
    });

    test('where the speaker really is wins when a song starts late', () async {
      // The song had to be fetched: by the time it plays, the Jam's clock is 12 s on.
      songs = _Songs();
      hubPosition = 12000;
      facade.emitPosition(const Duration(milliseconds: 300));
      await settle();

      await speaker.onSession(jam('owner',
          queue: [song(1)], playing: true, anchor: const Anchor(0, 0)));
      facade.emitPosition(const Duration(milliseconds: 400));
      await settle();

      expect(sent.whereType<Seek>().single.posMs, lessThan(2000),
          reason: 'the Jam is told where the music really is');
    });
  });

  group('a song that has to be fetched first', () {
    // Seen on a real phone (2026-10-17): the Jam moved to a song the phone did
    // not have; the title changed but the song before it went on playing for
    // the half minute the fetch took.
    test(
        'the old song stops, so the wrong song is not heard under the new '
        'title', () async {
      songs.gate = Completer<void>();

      final started =
          speaker.onSession(jam('owner', queue: [song(1)], playing: true));
      await Future<void>.delayed(const Duration(milliseconds: 40));

      expect(facade.calls, contains('pause'));
      songs.gate!.complete();
      await started;
    });

    test('a song that starts at once does not pause the old one first',
        () async {
      await speaker.onSession(jam('owner', queue: [song(1)], playing: true));
      await Future<void>.delayed(const Duration(milliseconds: 40));

      expect(facade.calls, isNot(contains('pause')));
    });

    test('the player is told it is loading, and when it is not any more',
        () async {
      songs.gate = Completer<void>();

      final started =
          speaker.onSession(jam('owner', queue: [song(1)], playing: true));
      await settle();
      expect(loads, [true]);
      songs.gate!.complete();
      await started;

      expect(loads, [true, false]);
    });
  });

  group('songs coming up', () {
    // The owner's idea (2026-10-17): "preload the songs we do not have on the
    // server but that were added to the Jam".
    test('the next two are got while the current one plays', () async {
      await speaker.onSession(jam('owner',
          queue: [song(1), song(2), song(3), song(4)], playing: true));

      expect(songs.preloaded, [2, 3]);
    });

    test('each song is asked for once, and a song added later is asked for',
        () async {
      await speaker.onSession(
          jam('owner', queue: [song(1), song(2), song(3)], playing: true));
      await speaker.onSession(jam('owner',
          queue: [song(1), song(2), song(3)], playing: true, rev: 2));
      await speaker.onSession(jam('owner',
          queue: [song(1), song(2), song(3), song(4)], playing: true, rev: 3));
      await speaker.onSession(jam('owner',
          queue: [song(1), song(2), song(3), song(4)],
          index: 1,
          playing: true,
          rev: 4));

      expect(songs.preloaded, [2, 3, 4]);
    });

    test('nothing is asked for while the current song is still being got',
        () async {
      // The line is slow: the song people are waiting for comes first.
      songs.gate = Completer<void>();

      final started = speaker.onSession(
          jam('owner', queue: [song(1), song(2), song(3)], playing: true));
      await settle();
      expect(songs.preloaded, isEmpty);
      songs.gate!.complete();
      await started;

      expect(songs.preloaded, [2, 3]);
    });

    test('a friend phone, which plays nothing, gets nothing ahead', () async {
      await speaker.onSession(
          jam('mia', queue: [song(1), song(2), song(3)], playing: true));

      expect(songs.preloaded, isEmpty);
    });
  });

  group('a song that cannot be played', () {
    test('is said out loud and skipped, not silence', () async {
      songs.cannot.add(1);

      await speaker.onSession(jam('owner',
          queue: [song(1, title: 'Sommaire'), song(2)], playing: true));

      expect(said.single, contains('Sommaire'));
      expect(sent.whereType<Ended>().single.uid, 1,
          reason: 'the queue moves on by itself');
    });

    test(
        'a friend\'s phone says nothing about a song it was never asked to play',
        () async {
      songs.cannot.add(1);

      await speaker.onSession(jam('mia', queue: [song(1)], playing: true));

      expect(said, isEmpty);
      expect(sent, isEmpty);
    });
  });
}
