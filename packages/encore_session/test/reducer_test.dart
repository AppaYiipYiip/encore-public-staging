import 'dart:convert';

import 'package:encore_session/encore_session.dart';
import 'package:test/test.dart';

const host = Member(id: 'host', name: 'Host', role: Role.host);
const sara = Member(id: 'sara', name: 'Sara');
const ben = Member(id: 'ben', name: 'Ben');

SessionState start({
  List<Member> people = const [host, sara, ben],
  List<String> tracks = const ['a', 'b', 'c'],
  String addedBy = 'host',
  bool playing = false,
}) {
  var uid = 1;
  return SessionState(members: people).copyWith(
    queue: [
      for (final t in tracks)
        QueueEntry(uid: uid++, trackId: t, addedBy: addedBy)
    ],
    nextUid: uid,
    playing: playing,
  );
}

SessionState ok(Outcome o) {
  expect(o.rejected, isNull, reason: 'refused: ${o.rejected}');
  return o.state;
}

String why(Outcome o) {
  expect(o.ok, isFalse, reason: 'expected a refusal');
  return o.rejected!;
}

Outcome run(SessionState s, Command c, String who, {int at = 0}) =>
    reduce(s, c, actorId: who, nowHubMs: at);

List<String> ids(SessionState s) => [for (final e in s.queue) e.trackId];

void main() {
  group('a song says what it is', () {
    // Each person on a server has their own library, so the id of a song in
    // one person's library means nothing in another's. A song in the queue
    // therefore carries its title and artist, and the phone that plays it finds
    // (or fetches) it for itself.
    test('the queue remembers the title, artist and album it was added with',
        () {
      final s = ok(run(
        start(tracks: const []),
        const Add('lib-7',
            title: 'Sommaire', artist: 'Raid', album: 'Lmorphine'),
        'sara',
      ));
      final entry = s.queue.single;
      expect(entry.trackId, 'lib-7');
      expect((entry.title, entry.artist, entry.album),
          ('Sommaire', 'Raid', 'Lmorphine'));
      expect(entry.addedBy, 'sara');
    });

    test('a song added without them is still fine (older phones)', () {
      final s = ok(run(start(tracks: const []), const Add('lib-7'), 'sara'));
      expect(s.queue.single.title, isNull);
      expect(s.queue.single.artist, isNull);
    });

    test('they survive the wire, and a state without them still reads', () {
      final s = ok(run(start(tracks: const []),
          const Add('lib-7', title: 'Sommaire', artist: 'Raid'), 'sara'));
      final back = SessionState.fromJson(jsonDecode(jsonEncode(s.toJson())));
      expect(back!.queue.single.title, 'Sommaire');
      expect(back.queue.single.artist, 'Raid');

      final old = jsonDecode(jsonEncode(s.toJson())) as Map<String, Object?>;
      for (final e in (old['queue']! as List).cast<Map<String, Object?>>()) {
        e
          ..remove('title')
          ..remove('artist')
          ..remove('album');
      }
      final fromOld = SessionState.fromJson(old);
      expect(fromOld, isNotNull, reason: 'a phone that does not send them');
      expect(fromOld!.queue.single.title, isNull);
    });

    test('a command with a title that is not text, or far too long, is refused',
        () {
      expect(
          Command.fromJson({'op': 'add', 'trackId': 'x', 'title': 42}), isNull);
      expect(
          Command.fromJson({'op': 'add', 'trackId': 'x', 'artist': 'a' * 500}),
          isNull);
      expect(Command.fromJson({'op': 'add', 'trackId': 'x', 'title': 'Fine'}),
          isA<Add>());
    });
  });

  group('what the screens need to show a song', () {
    // The Jam is the person's normal player (docs/39 F4): the queue, the mini
    // player and the player show what the song is, so an entry carries its length,
    // a cover and the catalogue's id of the artist (to open their page).
    test('an entry keeps its length, cover and artist reference', () {
      final s = ok(run(
        start(tracks: const []),
        const Add('lib-7',
            title: 'Sommaire',
            artist: 'Raid',
            durationSec: 200,
            imageUrl: 'https://cdn/cover.jpg',
            artistRef: '4242'),
        'sara',
      ));
      final e = s.queue.single;
      expect((e.durationSec, e.imageUrl, e.artistRef),
          (200, 'https://cdn/cover.jpg', '4242'));
      final back = SessionState.fromJson(jsonDecode(jsonEncode(s.toJson())));
      expect(back!.queue.single.durationSec, 200);
      expect(back.queue.single.imageUrl, 'https://cdn/cover.jpg');
      expect(back.queue.single.artistRef, '4242');
    });

    test('they are optional, and what is not a number or text is refused', () {
      expect(Command.fromJson({'op': 'add', 'trackId': 'x'}), isA<Add>());
      expect(
          Command.fromJson(
              {'op': 'add', 'trackId': 'x', 'durationSec': 'long'}),
          isNull);
      expect(Command.fromJson({'op': 'add', 'trackId': 'x', 'durationSec': -5}),
          isNull);
      expect(
          Command.fromJson(
              {'op': 'add', 'trackId': 'x', 'imageUrl': 'a' * 900}),
          isNull);
      expect(Command.fromJson({'op': 'add', 'trackId': 'x', 'artistRef': 7}),
          isNull);
    });
  });

  group('playing a song now', () {
    // "If I play a song while I am in a Jam, that is the song the Jam plays."
    test(
        'goes right after the current song, which becomes the current one, '
        'playing from the start', () {
      var s = ok(run(start(playing: true), const Play(), 'host', at: 0));
      s = ok(run(s, const Add('x', at: AddAt.now), 'sara', at: 5000));

      expect(ids(s), ['a', 'x', 'b', 'c']);
      expect(s.current!.trackId, 'x');
      expect(s.playing, isTrue);
      expect(s.positionAt(5000), 0, reason: 'from the start');
      expect(s.queue[1].addedBy, 'sara');
    });

    test('into an empty queue it starts playing at once', () {
      final s = ok(run(
          start(tracks: const []), const Add('x', at: AddAt.now), 'host',
          at: 100));

      expect(s.current!.trackId, 'x');
      expect(s.playing, isTrue);
    });

    test(
        'from a paused Jam it starts playing too: the person pressed play on a song',
        () {
      final s = ok(run(start(), const Add('x', at: AddAt.now), 'ben', at: 10));

      expect(s.current!.trackId, 'x');
      expect(s.playing, isTrue);
    });

    test('a full queue refuses it like any other add', () {
      final s = start(tracks: [for (var i = 0; i < maxQueue; i++) 't$i']);
      expect(
          why(run(s, const Add('x', at: AddAt.now), 'sara')), contains('full'));
    });

    test('the word travels over the wire', () {
      final c = Command.fromJson(
          {'op': 'add', 'trackId': 'x', 'at': 'now', 'title': 'T'});
      expect(c, isA<Add>());
      expect((c! as Add).at, AddAt.now);
    });
  });

  group('jumping to a song of the queue', () {
    test('plays that song from the start, whatever is before or after it', () {
      var s = ok(run(start(), const Play(), 'host', at: 0));
      s = ok(run(s, const Jump(3), 'sara', at: 8000));

      expect(s.current!.uid, 3);
      expect(s.playing, isTrue);
      expect(s.positionAt(8000), 0);
      s = ok(run(s, const Jump(1), 'ben', at: 9000));
      expect(s.current!.uid, 1);
      expect(ids(s), ['a', 'b', 'c'], reason: 'nothing moved');
    });

    test('a song that is not in the queue (any more) is refused', () {
      expect(why(run(start(), const Jump(99), 'sara')), contains('no such'));
    });

    test('it is an ordinary command: anybody may', () {
      expect(denial(sara, const Jump(2)), isNull);
    });
  });

  group('a song that finished playing', () {
    // Every phone that plays notices the end of the song at about the same
    // moment, and every one of them says so. The queue must move on ONCE.
    test('moves to the next song, however many phones say so', () {
      final playing = start(playing: true);
      final first = ok(run(playing, const Ended(1), 'sara', at: 200000));
      expect(first.index, 1);
      expect(first.anchor, const Anchor(200000, 0));
      expect(first.playing, isTrue);

      final second = ok(run(first, const Ended(1), 'ben', at: 200040));
      expect(second.index, 1,
          reason:
              'the second report is about a song that is no longer current');
      expect(second.rev, first.rev, reason: 'nothing changed, so no new state');
    });

    test('after the last song it stops, ready to start again', () {
      var s = start(playing: true, tracks: const ['a']);
      s = ok(run(s, const Ended(1), 'host', at: 90000));
      expect(s.playing, isFalse);
      expect(s.index, 0);
    });

    test('with "repeat all" the last song goes back to the first', () {
      var s = start(playing: true, tracks: const ['a', 'b'])
          .copyWith(repeat: Repeat.all, index: 1);
      s = ok(run(s, const Ended(2), 'host', at: 90000));
      expect(s.index, 0);
      expect(s.playing, isTrue);
    });

    test('with "repeat one" the same song starts again', () {
      var s = start(playing: true).copyWith(repeat: Repeat.one);
      s = ok(run(s, const Ended(1), 'host', at: 90000));
      expect(s.index, 0);
      expect(s.anchor, const Anchor(90000, 0));
      expect(s.playing, isTrue);
    });

    test('a report about another song, or while paused, changes nothing', () {
      final s = start(playing: true);
      expect(ok(run(s, const Ended(3), 'sara', at: 5)).index, 0,
          reason: 'song 3 is not the one playing');
      final paused = start();
      expect(ok(run(paused, const Ended(1), 'sara', at: 5)).index, 0,
          reason: 'nothing was playing');
    });

    test('only people in the session can say it', () {
      final s = start(playing: true);
      expect(why(run(s, const Ended(1), 'stranger')),
          'you are not in this session');
    });
  });

  group('playing and pausing', () {
    test('play starts the clock where the song was', () {
      final s = ok(run(start(), const Play(), 'host', at: 1000));
      expect(s.playing, isTrue);
      expect(s.anchor, const Anchor(1000, 0));
      expect(s.positionAt(1000), 0);
      expect(s.positionAt(6000), 5000);
    });

    test('pause freezes the position at that moment', () {
      var s = ok(run(start(), const Play(), 'host', at: 1000));
      s = ok(run(s, const Pause(), 'host', at: 4000));
      expect(s.playing, isFalse);
      expect(s.positionAt(99999), 3000,
          reason: 'it does not move while paused');
    });

    test('seek moves the anchor', () {
      var s = ok(run(start(), const Play(), 'host', at: 0));
      s = ok(run(s, const Seek(60000), 'host', at: 5000));
      expect(s.positionAt(7000), 62000);
    });

    test('repeating a command changes nothing: same state, same rev', () {
      final s = ok(run(start(), const Play(), 'host', at: 0));
      final again = ok(run(s, const Play(), 'sara', at: 500));
      expect(again.rev, s.rev);
      expect(again.anchor, s.anchor);
    });

    test('nothing to play is refused', () {
      expect(why(run(start(tracks: const []), const Play(), 'host')),
          contains('nothing'));
    });

    test('every accepted change moves the revision up by one', () {
      var s = start();
      final before = s.rev;
      s = ok(run(s, const Play(), 'host'));
      s = ok(run(s, const Seek(1000), 'host'));
      expect(s.rev, before + 2);
    });
  });

  group('next and previous', () {
    test('next moves on and restarts the song clock', () {
      final s = ok(run(start(playing: true), const Next(), 'sara', at: 9000));
      expect(s.index, 1);
      expect(s.anchor, const Anchor(9000, 0));
      expect(s.playing, isTrue);
    });

    test('next at the end stops, unless the queue repeats', () {
      var s = start(playing: true).copyWith(index: 2);
      final stopped = ok(run(s, const Next(), 'host', at: 100));
      expect(stopped.playing, isFalse);
      expect(stopped.index, 2);

      s = s.copyWith(repeat: Repeat.all);
      final wrapped = ok(run(s, const Next(), 'host', at: 100));
      expect(wrapped.index, 0);
      expect(wrapped.playing, isTrue);
    });

    test('previous restarts a song that has played a while, else goes back',
        () {
      var s = start(playing: true).copyWith(index: 1);
      s = s.copyWith(anchor: const Anchor(0, 0));
      final restart = ok(run(s, const Previous(), 'host', at: 10000));
      expect(restart.index, 1);
      expect(restart.positionAt(10000), 0);

      final back = ok(run(s, const Previous(), 'host', at: 1000));
      expect(back.index, 0);
    });
  });

  group('the queue', () {
    test('add puts the song last, or right after the current one', () {
      var s = ok(run(start(), const Add('x'), 'sara'));
      expect(ids(s), ['a', 'b', 'c', 'x']);
      s = ok(run(s, const Add('y', at: AddAt.next), 'ben'));
      expect(ids(s), ['a', 'y', 'b', 'c', 'x']);
      expect(s.queue[1].addedBy, 'ben', reason: 'the row says who added it');
    });

    test('adding to an empty queue makes it the current song, not playing', () {
      final s = ok(run(start(tracks: const []), const Add('x'), 'host'));
      expect(s.current!.trackId, 'x');
      expect(s.playing, isFalse);
    });

    test('a full queue refuses more', () {
      final s = start(tracks: [for (var i = 0; i < maxQueue; i++) 't$i']);
      expect(why(run(s, const Add('x'), 'sara')), contains('full'));
    });

    test('removing a song before the current one keeps the current song', () {
      final s = start().copyWith(index: 2);
      final out = ok(run(s, const Remove(1), 'host'));
      expect(ids(out), ['b', 'c']);
      expect(out.current!.trackId, 'c');
    });

    test('removing the current song moves to the next and restarts the clock',
        () {
      final s = start(playing: true).copyWith(index: 1);
      final out = ok(run(s, const Remove(2), 'host', at: 500));
      expect(out.current!.trackId, 'c');
      expect(out.anchor, const Anchor(500, 0));
      expect(out.playing, isTrue);
    });

    test('removing the last song stops', () {
      final s = start(tracks: const ['a'], playing: true);
      final out = ok(run(s, const Remove(1), 'host'));
      expect(out.queue, isEmpty);
      expect(out.playing, isFalse);
    });

    test('move keeps the same song current', () {
      final s = start().copyWith(index: 1); // b is current
      final out = ok(run(s, const Move(3, 0), 'host')); // c to the front
      expect(ids(out), ['c', 'a', 'b']);
      expect(out.current!.trackId, 'b');
    });

    test('an unknown song id in remove or move is refused', () {
      expect(why(run(start(), const Remove(99), 'host')), contains('no such'));
      expect(why(run(start(), const Move(99, 0), 'host')), contains('no such'));
    });
  });

  group('transfer and volume', () {
    test('transfer names the player and leaves the clock alone', () {
      var s = ok(run(start(playing: true), const Transfer('tablet'), 'host'));
      expect(s.playerDeviceId, 'tablet');
      expect(s.playing, isTrue);
      s = ok(run(s, const Transfer('phone'), 'host'));
      expect(s.playerDeviceId, 'phone');
    });

    test('volume is set by the host', () {
      expect(ok(run(start(), const SetVolume(40), 'host')).volume, 40);
    });
  });

  group(
      'who may do what (Spotify Jam: everybody plays, the host keeps the keys)',
      () {
    test(
        'everybody in the session can play, pause, skip, seek and edit the queue',
        () {
      for (final who in ['sara', 'ben']) {
        var s = start();
        s = ok(run(s, const Play(), who));
        s = ok(run(s, const Seek(5000), who));
        s = ok(run(s, const Next(), who));
        s = ok(run(s, const Previous(), who));
        s = ok(run(s, const Add('x'), who));
        s = ok(run(s, const Move(1, 2), who));
        s = ok(run(s, const Remove(2), who));
        s = ok(run(s, const SetRepeat(Repeat.all), who));
        ok(run(s, const Pause(), who));
      }
    });

    test('only the host controls the volume, the speaker and who is in', () {
      final s = start();
      for (final command in const [
        SetVolume(10),
        Transfer('tablet'),
        Kick('ben'),
      ]) {
        expect(why(run(s, command, 'sara')), contains('host'),
            reason: '${command.op.name} by a guest');
        ok(run(s, command, 'host'));
      }
    });

    test('a stranger, or a command from nobody, is refused', () {
      expect(why(run(start(), const Play(), 'mallory')), contains('not in'));
    });
  });

  group('people', () {
    test('join adds a member until the session is full', () {
      var s = const SessionState(members: [host]);
      for (var i = 1; i < maxPeople; i++) {
        s = ok(join(s, Member(id: 'p$i', name: 'Person $i')));
      }
      expect(s.members.length, maxPeople);
      expect(why(join(s, ben)), contains('full'));
    });

    test('the same person joining again changes nothing', () {
      final s = start();
      final again = ok(join(s, sara));
      expect(again.members.length, 3);
      expect(again.rev, s.rev);
    });

    test('kick removes a person', () {
      final s = ok(run(start(), const Kick('sara'), 'host'));
      expect(s.member('sara'), isNull);
      expect(s.members.length, 2);
    });

    test('the host cannot be kicked; leaving as the host ends the session', () {
      final s = start();
      expect(why(run(s, const Kick('host'), 'host')), contains('host'));
      expect(ok(leave(s, 'host')).ended, isTrue);
      expect(ok(leave(s, 'sara')).ended, isFalse);
    });

    test('nothing can be done in a session that has ended', () {
      final s = ok(leave(start(), 'host'));
      expect(why(run(s, const Play(), 'sara')), contains('ended'));
    });
  });
}
