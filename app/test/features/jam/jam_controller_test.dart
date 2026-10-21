import 'dart:async';

import 'package:encore/core/result.dart';
import 'package:encore/data/jam/jam_client.dart';
import 'package:encore/features/jam/jam_providers.dart';
import 'package:encore/features/providers.dart';
import 'package:encore_session/encore_session.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_jam_api.dart';
import '../../support/test_app.dart';

/// A person's Jam, as the app lives it (docs/30): start one or join with a code,
/// hear every change in order, keep going when the network blinks, and be told
/// plainly when it is over or they were sent away. Nothing here shows a screen:
/// the screens only read this and press its buttons.
void main() {
  late FakeJamApi api;
  late FakePlaybackFacade engine;
  late ProviderContainer container;
  var localNow = 10000;

  ProviderContainer open({FakeJamApi? with_, bool hubThere = true}) {
    api = with_ ?? FakeJamApi();
    engine = FakePlaybackFacade();
    container = ProviderContainer(overrides: [
      enginePlaybackFacadeProvider.overrideWithValue(engine),
      jamApiProvider.overrideWith((ref) async => hubThere ? api : null),
      jamBackoffProvider.overrideWithValue(const [Duration(milliseconds: 1)]),
      jamClockEveryProvider.overrideWithValue(const Duration(days: 1)),
      jamNowProvider.overrideWithValue(() => localNow),
    ]);
    addTearDown(container.dispose);
    return container;
  }

  JamController jam() => container.read(jamControllerProvider.notifier);
  JamSession session() => container.read(jamControllerProvider);

  setUp(() => localNow = 10000);

  group('a command shows its result at once, the hub has the last word', () {
    SessionState playing({int rev = 3, Anchor anchor = const Anchor(0, 0)}) =>
        SessionState(
          rev: rev,
          members: const [
            Member(id: 'owner', name: 'owner', role: Role.host),
            Member(id: 'mia', name: 'mia'),
          ],
          queue: const [
            QueueEntry(uid: 1, trackId: 'a', addedBy: 'mia', title: 'Sommaire'),
          ],
          nextUid: 2,
          playing: true,
          anchor: anchor,
        );

    Future<void> started(SessionState state) async {
      await jam().start();
      api.pushState(state);
      await Future<void>.delayed(Duration.zero);
    }

    test('a seek moves the place on this phone before the hub has answered',
        () async {
      open();
      await started(playing());
      api.commandGate = Completer<void>();
      api.commandAnswer =
          Result.ok(playing(rev: 4, anchor: Anchor(localNow, 90000)));

      final done = jam().send(const Seek(90000));
      await Future<void>.delayed(Duration.zero);

      expect(jam().positionNowMs(), inInclusiveRange(90000, 90100),
          reason: 'the person dragged the bar: it is there at once');
      expect(api.commands.last.$2, isA<Seek>(), reason: 'and the hub was told');

      api.commandGate!.complete();
      expect(await done, isTrue);
      expect(session().state!.rev, 4,
          reason: 'then the answer of the hub is the truth');
    });

    test('pause shows as paused at once', () async {
      open();
      await started(playing());
      api.commandGate = Completer<void>();
      api.commandAnswer = Result.ok(playing(rev: 4));

      final done = jam().send(const Pause());
      await Future<void>.delayed(Duration.zero);

      expect(session().state!.playing, isFalse);
      api.commandGate!.complete();
      await done;
    });

    test('what the hub says wins when it differs from the guess', () async {
      open();
      await started(playing());
      api.commandAnswer =
          Result.ok(playing(rev: 4, anchor: const Anchor(5, 777)));

      await jam().send(const Seek(90000));

      expect(session().state!.anchor, const Anchor(5, 777));
    });

    test('when the hub refuses, the earlier state comes back and says why',
        () async {
      open();
      final before = playing();
      await started(before);
      api.commandAnswer =
          const Result.err(ServerFailure('Cannot reach the Jam'));

      final accepted = await jam().send(const Pause());

      expect(accepted, isFalse);
      expect(session().state!.playing, isTrue,
          reason: 'it was not paused after all');
      expect(session().message, 'Cannot reach the Jam');
    });

    test('a command the rules refuse is not guessed at all', () async {
      open();
      await started(playing());
      api.commandAnswer =
          const Result.err(ServerFailure('only the host can do that'));

      await jam().send(const Kick('owner'));

      expect(session().state!.members, hasLength(2));
    });

    test('a newer state from the hub is not undone by an older answer',
        () async {
      open();
      await started(playing(rev: 3));
      api.commandGate = Completer<void>();
      api.commandAnswer = Result.ok(playing(rev: 4));

      final done = jam().send(const Pause());
      await Future<void>.delayed(Duration.zero);
      api.pushState(playing(rev: 6, anchor: const Anchor(1, 5000)));
      await Future<void>.delayed(Duration.zero);
      api.commandGate!.complete();
      await done;

      expect(session().state!.rev, 6);
    });
  });

  group('starting', () {
    test('a started Jam is active, has a code to share, and I host it',
        () async {
      open();

      await jam().start();

      expect(session().phase, JamPhase.active);
      expect(session().code, 'AB23CD');
      expect(session().isHost, isTrue);
      expect(api.listenedTo, ['AB23CD'], reason: 'listening began at once');
    });

    test('a Jam begun while a song plays starts with that song, still playing',
        () async {
      open();
      engine.emit(samplePlaying());

      await jam().start();

      final add = api.commands.single.$2 as Add;
      expect((add.title, add.artist, add.album),
          ('Opening The', 'Periphery', 'The Walk'));
      expect(add.trackId, 'al3-t1');
      expect(add.durationSec, 200);
      expect(add.at, AddAt.now, reason: 'the music was on: the Jam is on');
    });

    test('a song that was paused goes in paused', () async {
      open();
      engine.emit(samplePlaying(isPlaying: false));

      await jam().start();

      expect((api.commands.single.$2 as Add).at, AddAt.end);
    });

    test('with nothing playing the Jam begins empty', () async {
      open();

      await jam().start();

      expect(api.commands, isEmpty);
    });

    test('joining another Jam does not add what this phone was playing',
        () async {
      open();
      engine.emit(samplePlaying());

      await jam().join('ab23cd');

      expect(api.commands, isEmpty);
    });

    test('a server without Jam says so, instead of doing nothing', () async {
      open(hubThere: false);

      await jam().start();

      expect(session().phase, JamPhase.none);
      expect(session().message, contains('no Jam'));
    });

    test('a hub that refuses says why, in its own words', () async {
      open();
      api.createAnswer = const Result.err(
          ServerFailure('The hub is full. Try again later.', statusCode: 503));

      await jam().start();

      expect(session().phase, JamPhase.none);
      expect(session().message, 'The hub is full. Try again later.');
    });

    test('pressing start twice does not start two', () async {
      open();

      await Future.wait([jam().start(), jam().start()]);

      expect(api.createCalls, 1);
    });
  });

  group('joining', () {
    test('a friend joins with the code as typed and is a member', () async {
      open(with_: FakeJamApi(me: 'mia'));

      await jam().join(' ab23cd ');

      expect(session().phase, JamPhase.active);
      expect(session().code, 'AB23CD');
      expect(session().isHost, isFalse);
      expect(session().state!.members.map((m) => m.id), ['owner', 'mia']);
    });

    test(
        'a code that is not there leaves them where they were, with the reason',
        () async {
      open();
      api.joinAnswer = const Result.err(
          NotFoundFailure('there is no session with that code'));

      await jam().join('ZZZZZZ');

      expect(session().phase, JamPhase.none);
      expect(session().message, 'there is no session with that code');
    });

    test('an empty code is not sent at all', () async {
      open();

      await jam().join('   ');

      expect(api.joinedWith, isEmpty);
      expect(session().message, contains('code'));
    });
  });

  group('hearing the Jam', () {
    test('every state from the hub replaces the last, in order', () async {
      open();
      await jam().start();
      final base = session().state!;

      api.pushState(base.copyWith(rev: 2, queue: const [
        QueueEntry(uid: 1, trackId: 'a', addedBy: 'owner', title: 'One'),
      ]));
      await pumpEventQueue();
      expect(session().state!.queue.single.title, 'One');

      api.pushState(base.copyWith(rev: 3, playing: true));
      await pumpEventQueue();
      expect(session().state!.rev, 3);
      expect(session().state!.playing, isTrue);
    });

    test('an older or repeated state never undoes a newer one', () async {
      open();
      await jam().start();
      final base = session().state!;
      api.pushState(base.copyWith(rev: 5, playing: true));
      await pumpEventQueue();

      api.pushState(base.copyWith(rev: 4, playing: false));
      api.pushState(base.copyWith(rev: 5, playing: false));
      await pumpEventQueue();

      expect(session().state!.playing, isTrue);
      expect(session().state!.rev, 5);
    });

    test('when the host ends it, everybody is told it is over', () async {
      open(with_: FakeJamApi(me: 'mia'));
      await jam().join('AB23CD');

      api.pushState(session().state!.copyWith(rev: 9, ended: true));
      await pumpEventQueue();

      expect(session().phase, JamPhase.ended);
      expect(session().message, 'The Jam is over.');
    });

    test('being sent away says so and does not reconnect', () async {
      open(with_: FakeJamApi(me: 'mia'));
      await jam().join('AB23CD');

      api.push(const JamKickedEvent());
      await api.stream.close();
      await pumpEventQueue();

      expect(session().phase, JamPhase.ended);
      expect(session().message, 'You were removed from the Jam.');
      expect(api.streams, hasLength(1), reason: 'no new connection');
    });
  });

  group('a network that blinks', () {
    test(
        'a dropped connection is picked up again, and the state is whole again',
        () async {
      open();
      await jam().start();

      await api.drop();
      await pumpEventQueue();
      expect(session().reconnecting, isTrue, reason: 'the screen can say so');
      await Future<void>.delayed(
          const Duration(milliseconds: 30)); // the backoff
      await pumpEventQueue();
      expect(api.streams, hasLength(2), reason: 'it listens again by itself');
      expect(session().phase, JamPhase.active);

      // The hub tells a returning phone the whole state at once.
      api.pushState(session().state!.copyWith(rev: 7, playing: true));
      await pumpEventQueue();
      expect(session().state!.rev, 7);
      expect(session().reconnecting, isFalse);
    });

    test('it says it is reconnecting while it waits', () async {
      open();
      await jam().start();

      unawaited(api.drop());
      await Future<void>.delayed(Duration.zero);

      // Between the drop and the new connection the screen can say so.
      await pumpEventQueue();
      expect(session().phase, JamPhase.active);
    });

    test('a refusal ends it with the reason and does not hammer the hub',
        () async {
      open();
      await jam().start();

      api.push(const JamClosedEvent(reason: 'you are not in this session'));
      await api.stream.close();
      await pumpEventQueue();

      expect(session().phase, JamPhase.ended);
      expect(session().message, 'you are not in this session');
      expect(api.streams, hasLength(1));
    });
  });

  group('doing things', () {
    test('a command that is accepted shows its new state at once', () async {
      open();
      await jam().start();
      final after = session().state!.copyWith(rev: 2, playing: true);
      api.commandAnswer = Result.ok(after);

      final done = await jam().send(const Play());

      expect(done, isTrue);
      expect(session().state!.playing, isTrue);
      expect(api.commands.single.$2, isA<Play>());
      expect(api.commands.single.$1, 'AB23CD');
    });

    test('a refusal is shown as the rule\'s own sentence and changes nothing',
        () async {
      open(with_: FakeJamApi(me: 'mia'));
      await jam().join('AB23CD');
      api.commandAnswer =
          const Result.err(ServerFailure('only the host can do that'));
      final before = session().state;

      final done = await jam().send(const Kick('owner'));

      expect(done, isFalse);
      expect(session().message, 'only the host can do that');
      expect(session().state, same(before));
    });

    test('nothing is sent when there is no Jam', () async {
      open();

      final done = await jam().send(const Play());

      expect(done, isFalse);
      expect(api.commands, isEmpty);
    });

    test('leaving tells the hub, stops listening, and forgets the Jam',
        () async {
      open();
      await jam().start();

      await jam().leave();

      expect(api.left, ['AB23CD']);
      expect(session().phase, JamPhase.none);
      expect(session().code, isNull);
      expect(session().state, isNull);
    });

    test('starting a new Jam after one ended works', () async {
      open();
      await jam().start();
      api.pushState(session().state!.copyWith(rev: 9, ended: true));
      await pumpEventQueue();
      expect(session().phase, JamPhase.ended);

      await jam().start();

      expect(session().phase, JamPhase.active);
      expect(api.createCalls, 2);
    });
  });

  test('the speaker\'s phone can tell the person something, once', () async {
    open();
    await jam().start();

    jam().say('Could not play "Sommaire" on this phone. Skipping it.');
    expect(session().message, contains('Sommaire'));

    jam().dismissMessage();
    expect(session().message, isNull);
  });

  group('the hub\'s clock', () {
    test('a phone knows what time it is at the hub from a few round trips',
        () async {
      open();
      api.clockAnswers = [
        // sent, received, what the hub said: the hub is 5000 ms ahead
        const Result.ok(
            ClockSample(sentMs: 10000, receivedMs: 10040, hubMs: 15020)),
        const Result.ok(
            ClockSample(sentMs: 10100, receivedMs: 10130, hubMs: 15115)),
        const Result.ok(
            ClockSample(sentMs: 10200, receivedMs: 10240, hubMs: 15220)),
      ];
      await jam().start();
      await jam().sampleClock();
      await jam().sampleClock();

      localNow = 20000;
      expect(jam().hubNowMs(), closeTo(25000, 20));
    });

    test('the position of the song now is read from the hub\'s clock',
        () async {
      open();
      api.clockAnswers = [
        const Result.ok(ClockSample(sentMs: 0, receivedMs: 0, hubMs: 5000)),
      ];
      await jam().start();
      await jam().sampleClock();
      await jam().sampleClock();
      await jam().sampleClock();
      api.pushState(session().state!.copyWith(
            rev: 2,
            playing: true,
            queue: const [QueueEntry(uid: 1, trackId: 'a', addedBy: 'owner')],
            anchor: const Anchor(
                5000, 1000), // at hub time 5000 the song was at 1 s
          ));
      await pumpEventQueue();

      localNow = 3000; // hub time 8000: three seconds later
      expect(jam().positionNowMs(), 4000);
    });
  });
}
