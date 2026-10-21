import 'dart:async';

import 'package:encore/features/jam/jam_facade.dart';
import 'package:encore/features/player/playback_facade.dart';
import 'package:encore_session/encore_session.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/factories.dart';
import '../../support/test_app.dart';

class _Link implements JamLink {
  @override
  bool inJam = false;
  @override
  bool iPlay = false;
  @override
  SessionState? state;
  @override
  bool loading = false;
  int position = 0;
  final List<Command> sent = [];
  final List<String> said = [];
  final _changes = StreamController<void>.broadcast();

  @override
  Stream<void> get changes => _changes.stream;
  void changed() => _changes.add(null);

  @override
  int positionNowMs() => position;

  @override
  Future<bool> send(Command command) async {
    sent.add(command);
    return true;
  }

  @override
  void say(String message) => said.add(message);
}

/// In a Jam the person's player is the Jam's (docs/39 F4, F5): the same player,
/// mini-player and queue, showing the shared queue and sending every command
/// to the Jam. Outside a Jam it is the ordinary player, untouched.
void main() {
  const host = Member(id: 'host', name: 'tester', role: Role.host);
  const mia = Member(id: 'mia', name: 'mia');

  QueueEntry entry(int uid, String title,
          {String artist = 'Ramones', String? ref, int? seconds = 150}) =>
      QueueEntry(
        uid: uid,
        trackId: 'lib-$uid',
        addedBy: 'mia',
        title: title,
        artist: artist,
        album: 'Greatest Hits',
        durationSec: seconds,
        imageUrl: 'https://cdn/$uid.jpg',
        artistRef: ref,
      );

  SessionState session({
    List<QueueEntry>? queue,
    int index = 0,
    bool playing = true,
    Repeat repeat = Repeat.off,
  }) =>
      SessionState(
        members: const [host, mia],
        queue:
            queue ?? [entry(1, 'Blitzkrieg Bop'), entry(2, 'Judy Is a Punk')],
        nextUid: 10,
        index: index,
        playing: playing,
        repeat: repeat,
      );

  late FakePlaybackFacade engine;
  late _Link link;
  late JamPlaybackFacade facade;

  setUp(() {
    engine = FakePlaybackFacade();
    link = _Link();
    facade = JamPlaybackFacade(engine: engine, link: link);
  });

  tearDown(() => facade.dispose());

  void inJam({bool iPlay = false, SessionState? state}) {
    link
      ..inJam = true
      ..iPlay = iPlay
      ..state = state ?? session();
    link.changed();
  }

  group('outside a Jam', () {
    test('it is the ordinary player: what it shows and what it does', () async {
      engine.emit(samplePlaying());

      expect(facade.snapshot.track?.title, 'Opening The');
      await facade.skipNext();

      expect(engine.calls, contains('next'));
      expect(link.sent, isEmpty);
    });
  });

  group('in a Jam, it shows the Jam', () {
    test('the song that is on, how far it is, and that it plays in the Jam',
        () async {
      inJam();
      link.position = 42000;

      final s = facade.snapshot;

      expect(s.track?.title, 'Blitzkrieg Bop');
      expect(s.track?.artist, 'Ramones');
      expect(s.track?.imageUrl, 'https://cdn/1.jpg');
      expect(s.duration, const Duration(seconds: 150));
      expect(s.isPlaying, isTrue);
      expect(s.queueIndex, 0);
      expect(s.queueLength, 2);
      expect(s.hasNext, isTrue);
      expect(s.hasPrevious, isFalse);
      expect(s.sourceName, 'Jam');
    });

    test(
        'a song has the same id in every Jam and another song never has it: '
        'the lyrics of one Jam are not shown in the next', () {
      // Seen on a real phone (2026-10-17): the host's lyrics page showed rap
      // lyrics under "Schism", because the Jam's songs were named by their
      // place in the queue ("jam:3") and every Jam counts from 1.
      QueueEntry at(int uid, String trackId) => QueueEntry(
          uid: uid, trackId: trackId, addedBy: 'mia', title: 't$uid');

      inJam(state: session(queue: [at(3, 'cat:55')]));
      final first = facade.snapshot.track?.id;
      inJam(state: session(queue: [at(3, 'cat:56')]));
      final other = facade.snapshot.track?.id;
      inJam(state: session(queue: [at(1, 'cat:55')]));
      final same = facade.snapshot.track?.id;

      expect(first, isNot(other), reason: 'same place, another song');
      expect(first, same, reason: 'same song, another place');
      expect(first, startsWith('jam:'), reason: 'never taken for a library id');
    });

    test('the artist can be opened when the song carried the catalogue id', () {
      inJam(
          state: session(
              queue: [entry(1, 'Sommaire', artist: 'Raid', ref: '4242')]));

      expect(facade.snapshot.track?.catalogueArtistId, '4242');
    });

    test(
        'while the phone that plays is still getting the song, the old song '
        'under the new title is not shown: the new length, and loading', () {
      // Seen on a real phone (2026-10-17): a Jam on "Vicarious" showed the
      // bar at its end, because the length was that of the song the phone was
      // still playing; a tap on a line of the lyrics then "ended" the song.
      engine.emit(const PlaybackSnapshot(
        track: NowPlayingTrack(
            id: 'old', title: 'Spiritual Healing', artist: 'Death'),
        isPlaying: true,
        duration: Duration(seconds: 156),
      ));
      link.loading = true;
      inJam(
          iPlay: true,
          state: session(
              queue: [entry(1, 'Vicarious', artist: 'Tool', seconds: 426)]));
      link.position = 20000;

      final s = facade.snapshot;

      expect(s.track?.title, 'Vicarious');
      expect(s.duration, const Duration(seconds: 426));
      expect(s.isLoading, isTrue);
    });

    test('once the song is there, its own length and no loading', () {
      engine.emit(const PlaybackSnapshot(
        track: NowPlayingTrack(id: 'mine', title: 'Vicarious', artist: 'Tool'),
        isPlaying: true,
        duration: Duration(seconds: 427),
      ));
      link.loading = false;
      inJam(
          iPlay: true,
          state: session(
              queue: [entry(1, 'Vicarious', artist: 'Tool', seconds: 426)]));

      final s = facade.snapshot;

      expect(s.duration, const Duration(seconds: 427));
      expect(s.isLoading, isFalse);
    });

    test('the position follows the Jam\'s clock', () async {
      inJam();
      link.position = 5000;
      final seen = <Duration>[];
      final sub = facade.positionStream.listen(seen.add);

      await Future<void>.delayed(const Duration(milliseconds: 600));
      link.position = 9000;
      await Future<void>.delayed(const Duration(milliseconds: 600));
      await sub.cancel();

      expect(seen, isNotEmpty);
      expect(seen.last, const Duration(seconds: 9));
    });

    test('an empty Jam shows nothing playing, not the person\'s old song', () {
      engine.emit(samplePlaying());
      inJam(state: session(queue: const []));

      expect(facade.snapshot.track, isNull);
      expect(facade.queue.items, isEmpty);
    });

    test('a phone that plays shows the real song it has (its own library id)',
        () {
      engine.emit(PlaybackSnapshot(
        track: const NowPlayingTrack(
            id: 'my-library-id',
            title: 'Blitzkrieg Bop',
            artist: 'Ramones',
            coverArt: 'cover-9',
            duration: Duration(seconds: 133)),
        isPlaying: true,
        duration: const Duration(seconds: 133),
      ));
      inJam(iPlay: true);

      expect(facade.snapshot.track?.id, 'my-library-id',
          reason: 'liking it must like the song in the right library');
      expect(facade.snapshot.track?.coverArt, 'cover-9');
      expect(facade.snapshot.sourceName, 'Jam');
      expect(facade.snapshot.queueLength, 2);
    });

    test('while the song loads on the speaker, the player says so', () {
      engine.emit(const PlaybackSnapshot(isLoading: true));
      inJam(iPlay: true);

      expect(facade.snapshot.isLoading, isTrue);
    });
  });

  group('in a Jam, the buttons are the Jam\'s', () {
    setUp(() => inJam());

    test('play, pause, next, previous and seek', () async {
      await facade.pause();
      await facade.play();
      await facade.skipNext();
      await facade.skipPrevious();
      await facade.seek(const Duration(seconds: 33));

      expect(link.sent.map((c) => c.op), [
        Op.pause,
        Op.play,
        Op.next,
        Op.previous,
        Op.seek,
      ]);
      expect((link.sent.last as Seek).posMs, 33000);
      expect(engine.calls, isEmpty,
          reason: 'nothing touched this phone\'s own player');
    });

    test('the play button toggles by what the Jam is doing', () async {
      await facade.togglePlayPause();
      expect(link.sent.single.op, Op.pause);

      inJam(state: session(playing: false));
      await facade.togglePlayPause();
      expect(link.sent.last.op, Op.play);
    });

    test('repeat goes round: off, all, one', () async {
      facade.cycleRepeat();
      inJam(state: session(repeat: Repeat.all));
      facade.cycleRepeat();
      inJam(state: session(repeat: Repeat.one));
      facade.cycleRepeat();
      await Future<void>.delayed(Duration.zero);

      expect(link.sent.map((c) => (c as SetRepeat).mode),
          [Repeat.all, Repeat.one, Repeat.off]);
    });

    test('shuffle is not there yet, and says so', () async {
      facade.toggleShuffle();

      expect(link.sent, isEmpty);
      expect(link.said.single, contains('Shuffle'));
    });
  });

  group('in a Jam, a song played from anywhere plays in the Jam', () {
    setUp(() => inJam());

    test('a song tapped in an album goes right after the current one and plays',
        () async {
      await facade.playTracks(
        [trackRow('al1-t1', title: 'Opening Kodama', artist: 'Alcest')],
        sourceName: 'Kodama',
        sourceId: 'album:al1',
      );

      final add = link.sent.single as Add;
      expect(add.at, AddAt.now);
      expect((add.trackId, add.title, add.artist),
          ('al1-t1', 'Opening Kodama', 'Alcest'));
      expect(engine.calls, isEmpty,
          reason: 'this phone does not start it by itself');
    });

    test('only the tapped song, not the whole album', () async {
      await facade.playTracks([
        trackRow('a', title: 'One'),
        trackRow('b', title: 'Two'),
        trackRow('c', title: 'Three'),
      ], startIndex: 1);

      expect(link.sent, hasLength(1));
      expect((link.sent.single as Add).title, 'Two');
    });

    test(
        'a song from the catalogue goes in by what it is, with its cover and artist',
        () async {
      await facade.playPreview(
        id: 'dz-77',
        title: 'Sommaire',
        uri: Uri.parse('https://cdn/p.mp3'),
        artist: 'Raid',
        catalogueArtistId: '4242',
        album: 'Lmorphine',
        imageUrl: 'https://cdn/cover.jpg',
        duration: const Duration(minutes: 3, seconds: 20),
      );

      final add = link.sent.single as Add;
      expect(add.at, AddAt.now);
      expect(add.trackId, 'cat:dz-77');
      expect((add.artistRef, add.imageUrl, add.durationSec),
          ('4242', 'https://cdn/cover.jpg', 200));
    });

    test('add to queue and play next', () async {
      await facade.addToQueue(trackRow('x', title: 'Last'));
      await facade.playNext(trackRow('y', title: 'Next'));

      expect(link.sent.map((c) => (c as Add).at), [AddAt.end, AddAt.next]);
    });

    test('a song the service just fetched goes to the end by name', () async {
      await facade.addStreamToQueue(PreviewTrack(
        id: 'dz-5',
        title: 'Creep',
        uri: Uri.parse('http://svc/a'),
        artist: 'Radiohead',
        fullSong: true,
      ));

      final add = link.sent.single as Add;
      expect(
          (add.at, add.trackId, add.title), (AddAt.end, 'cat:dz-5', 'Creep'));
    });
  });

  group('in a Jam, the queue is the Jam\'s queue', () {
    setUp(() => inJam(
        state: session(
            queue: [entry(1, 'A'), entry(2, 'B'), entry(3, 'C')], index: 1)));

    test('as the queue sheet reads it', () {
      final q = facade.queue;

      expect(q.items.map((i) => i.title), ['A', 'B', 'C']);
      expect(q.currentIndex, 1);
      expect(q.upNext.map((i) => i.title), ['C']);
      expect(q.items.every((i) => !i.isLibraryTrack), isTrue,
          reason: 'these are not rows of this phone\'s library');
    });

    test('a tap on a song of the queue jumps to it', () async {
      await facade.jumpToQueueIndex(2);

      expect((link.sent.single as Jump).uid, 3);
    });

    test('removing and moving go to the Jam, by the entry, not by the row',
        () async {
      await facade.removeFromQueue(0);
      await facade.moveInQueue(0, 2);

      expect((link.sent[0] as Remove).uid, 1);
      expect((link.sent[1] as Move).uid, 1);
      expect((link.sent[1] as Move).to, 2);
    });

    test('clearing what is up next removes those songs', () async {
      await facade.clearUpNext();

      expect(link.sent.whereType<Remove>().map((r) => r.uid), [3]);
    });
  });

  group('when the Jam is over', () {
    test('the player is the person\'s own again, as it was', () async {
      engine.emit(samplePlaying());
      inJam();
      expect(facade.snapshot.track?.title, 'Blitzkrieg Bop');

      link
        ..inJam = false
        ..state = null;
      link.changed();

      expect(facade.snapshot.track?.title, 'Opening The');
      await facade.skipNext();
      expect(engine.calls, contains('next'));
    });

    test('whoever listens is told at once', () async {
      final seen = <String?>[];
      final sub = facade.snapshots.listen((s) => seen.add(s.track?.title));

      inJam();
      await Future<void>.delayed(Duration.zero);
      link
        ..inJam = false
        ..state = null;
      link.changed();
      await Future<void>.delayed(Duration.zero);
      await sub.cancel();

      expect(seen, contains('Blitzkrieg Bop'));
    });
  });
}
