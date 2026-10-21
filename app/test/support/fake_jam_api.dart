import 'dart:async';

import 'package:encore/core/result.dart';
import 'package:encore/data/jam/jam_client.dart';
import 'package:encore_session/encore_session.dart';

/// The Jam hub as tests see it: answers from fields, records what the app sent,
/// and lets a test push events down the stream by hand.
class FakeJamApi implements JamApi {
  FakeJamApi({this.me = 'owner'});

  /// Who the app is signed in as.
  final String me;

  /// What the hub answers to [create] and [join] (a test may change it).
  Result<JamJoined>? createAnswer;
  Result<JamJoined>? joinAnswer;
  Result<SessionState>? commandAnswer;

  /// When set, [command] does not answer until it completes.
  Completer<void>? commandGate;
  final List<(String, Command)> commands = [];
  final List<String> left = [];
  final List<String> joinedWith = [];
  int createCalls = 0;
  List<Result<ClockSample>> clockAnswers = [];
  int clockCalls = 0;

  /// One controller per call of [events]: a test pushes events into the latest.
  final List<StreamController<JamEvent>> streams = [];
  final List<String> listenedTo = [];

  StreamController<JamEvent> get stream => streams.last;

  void push(JamEvent event) => stream.add(event);
  void pushState(SessionState state) => push(JamStateEvent(state));

  /// The connection drops (the network): the stream ends.
  Future<void> drop() async {
    stream.add(const JamClosedEvent(dropped: true));
    await stream.close();
  }

  static SessionState alone(String user, {int rev = 1}) => SessionState(
        rev: rev,
        members: [Member(id: user, name: user, role: Role.host)],
      );

  @override
  Future<Result<JamJoined>> create() async {
    createCalls++;
    return createAnswer ??
        Result.ok(JamJoined(code: 'AB23CD', you: me, state: alone(me)));
  }

  @override
  Future<Result<JamJoined>> join(String code) async {
    joinedWith.add(code);
    return joinAnswer ??
        Result.ok(JamJoined(
          code: code.trim().toUpperCase(),
          you: me,
          state: SessionState(rev: 2, members: [
            const Member(id: 'owner', name: 'owner', role: Role.host),
            Member(id: me, name: me),
          ]),
        ));
  }

  @override
  Future<Result<void>> leave(String code) async {
    left.add(code);
    return const Result.ok(null);
  }

  @override
  Future<Result<SessionState>> command(String code, Command command) async {
    commands.add((code, command));
    // A slow hub: the answer waits until a test opens the gate.
    await commandGate?.future;
    return commandAnswer ??
        const Result.err(ServerFailure('no answer configured'));
  }

  @override
  Future<Result<ClockSample>> sampleClock() async {
    clockCalls++;
    if (clockAnswers.isEmpty) {
      return const Result.ok(ClockSample(sentMs: 0, receivedMs: 0, hubMs: 0));
    }
    return clockAnswers.length > 1
        ? clockAnswers.removeAt(0)
        : clockAnswers.first;
  }

  @override
  Stream<JamEvent> events(String code) {
    listenedTo.add(code);
    final controller = StreamController<JamEvent>();
    streams.add(controller);
    return controller.stream;
  }
}
