import 'dart:async';
import 'dart:math' as math;

import 'package:encore_session/encore_session.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../core/logger.dart';
import '../../core/network_policy.dart';
import '../../core/result.dart';
import '../../data/jam/jam_client.dart';
import '../instant/instant_controller.dart' show jsonDecodeEndpoints;
import '../people/people_providers.dart' show peopleAuthProvider;
import '../providers.dart' show enginePlaybackFacadeProvider;

/// The Jam hub's usual port on the home network.
const int kJamPort = 8703;

/// Where to look for the Jam hub, most likely first: behind an https address
/// under `/hub` (the public address has one door, and the hub sits behind it
/// like the people service does), and on its own port on a home-network
/// address.
List<Uri> jamServiceCandidates(Iterable<Uri> serverEndpoints) {
  final out = <Uri>[];
  final seen = <String>{};
  void add(Uri uri) {
    if (uri.host.isEmpty) return;
    final text = uri.toString().replaceAll(RegExp(r'/+$'), '');
    if (seen.add(text)) out.add(Uri.parse(text));
  }

  final https = [
    for (final e in serverEndpoints)
      if (e.scheme == 'https') e,
  ];
  for (final endpoint in https) {
    final basePath = endpoint.path.replaceAll(RegExp(r'/+$'), '');
    add(Uri(
      scheme: 'https',
      host: endpoint.host,
      port: endpoint.hasPort ? endpoint.port : null,
      path: '$basePath/hub',
    ));
  }
  for (final endpoint in serverEndpoints) {
    if (endpoint.scheme == 'https') continue; // its door is /hub, above
    add(Uri(
      scheme: isPrivateHost(endpoint.host) ? 'http' : 'https',
      host: endpoint.host,
      port: kJamPort,
    ));
  }
  return out;
}

/// Where the Jam hub answers, or `null` (not set up on this server, or not
/// reachable from this network). Looked at again when the phone changes network.
final jamServiceProvider = FutureProvider<Uri?>((ref) async {
  ref.watch(networkKindProvider);
  final auth = await ref.watch(peopleAuthProvider.future);
  if (auth == null) return null;
  final server = await ref.watch(activeServerProvider.future);
  if (server == null) return null;
  final List<Uri> endpoints;
  try {
    endpoints = [
      for (final e in jsonDecodeEndpoints(server.endpointsJson)) e.url
    ];
  } on FormatException {
    return null;
  } on TypeError {
    return null;
  }
  final candidates = jamServiceCandidates(endpoints);
  final answers = await Future.wait([
    for (final uri in candidates) JamClient.probe(uri),
  ]);
  for (var i = 0; i < candidates.length; i++) {
    if (answers[i]) {
      Log.info('jam', 'the Jam hub is at ${candidates[i].host}');
      return candidates[i];
    }
  }
  Log.info('jam', 'no Jam hub at ${candidates.map((u) => u.host).join(', ')}');
  return null;
});

/// The client of the hub, once it is found and somebody is signed in.
final jamApiProvider = FutureProvider<JamApi?>((ref) async {
  final uri = await ref.watch(jamServiceProvider.future);
  final auth = await ref.watch(peopleAuthProvider.future);
  if (uri == null || auth == null) return null;
  return JamClient(baseUrl: uri, auth: auth);
});

/// How long to wait before listening again after the connection dropped; the
/// last value repeats.
final jamBackoffProvider = Provider<List<Duration>>((ref) => const [
      Duration(seconds: 1),
      Duration(seconds: 2),
      Duration(seconds: 4),
      Duration(seconds: 8),
      Duration(seconds: 15),
      Duration(seconds: 30),
    ]);

/// How often the hub's clock is asked about while a Jam is on.
final jamClockEveryProvider =
    Provider<Duration>((ref) => const Duration(seconds: 60));

/// This phone's clock, in milliseconds (tests replace it).
final jamNowProvider = Provider<int Function()>(
    (ref) => () => DateTime.now().millisecondsSinceEpoch);

enum JamPhase { none, connecting, active, ended }

/// What the person's Jam is right now.
@immutable
class JamSession {
  const JamSession({
    this.phase = JamPhase.none,
    this.code,
    this.me,
    this.state,
    this.reconnecting = false,
    this.message,
  });

  final JamPhase phase;

  /// What others type to join.
  final String? code;
  final String? me;
  final SessionState? state;

  /// The connection dropped and the app is listening again.
  final bool reconnecting;

  /// A sentence to show (why something did not work, or that it is over).
  final String? message;

  bool get inJam => phase == JamPhase.active;

  bool get isHost => state?.member(me ?? '')?.isHost ?? false;

  /// The person whose phone plays: the one the host chose, else the host.
  String? get speakerId {
    final s = state;
    if (s == null) return null;
    final chosen = s.playerDeviceId;
    if (chosen != null && s.member(chosen) != null) return chosen;
    for (final m in s.members) {
      if (m.isHost) return m.id;
    }
    return null;
  }

  /// This phone is the one that plays.
  bool get iPlay => inJam && speakerId == me;

  JamSession copyWith({
    JamPhase? phase,
    Object? code = _keep,
    Object? me = _keep,
    Object? state = _keep,
    bool? reconnecting,
    Object? message = _keep,
  }) =>
      JamSession(
        phase: phase ?? this.phase,
        code: identical(code, _keep) ? this.code : code as String?,
        me: identical(me, _keep) ? this.me : me as String?,
        state: identical(state, _keep) ? this.state : state as SessionState?,
        reconnecting: reconnecting ?? this.reconnecting,
        message: identical(message, _keep) ? this.message : message as String?,
      );
}

const Object _keep = Object();

/// The person's Jam: start or join, hear every change in order, listen again
/// when the connection drops, say plainly when it is over (docs/30).
class JamController extends Notifier<JamSession> {
  /// Bumped whenever the Jam is left or ends, so an older listener stops.
  int _generation = 0;
  StreamSubscription<JamEvent>? _sub;
  Completer<void>? _waiting;
  Timer? _clockTimer;
  Timer? _warmUp;
  final ClockEstimator _clock = ClockEstimator();
  bool _entering = false;

  @override
  JamSession build() {
    ref.onDispose(_stop);
    return const JamSession();
  }

  void _stop() {
    _generation++;
    _sub?.cancel();
    _sub = null;
    final waiting = _waiting;
    if (waiting != null && !waiting.isCompleted) waiting.complete();
    _clockTimer?.cancel();
    _warmUp?.cancel();
    _clockTimer = null;
    _warmUp = null;
  }

  /// Starts a Jam; this phone hosts it. A song that is playing becomes the
  /// Jam's first and goes on playing (a Jam begun in the middle of a song does
  /// not stop the music).
  Future<void> start() async {
    await _enter((api) => api.create());
    if (state.inJam && state.isHost) await _carryOverSong();
  }

  Future<void> _carryOverSong() async {
    final snapshot = ref.read(enginePlaybackFacadeProvider).snapshot;
    final t = snapshot.track;
    if (t == null) return;
    // A song of the library keeps its id; one that only the catalogue knows is
    // asked for by name.
    final inLibrary =
        t.albumId != null || t.artistId != null || t.coverArt != null;
    await send(Add(
      inLibrary ? t.id : 'cat:${t.id}',
      at: snapshot.isPlaying ? AddAt.now : AddAt.end,
      title: t.title,
      artist: t.artist,
      album: t.album,
      durationSec: (t.duration ?? snapshot.duration).inSeconds,
      imageUrl: t.imageUrl,
      artistRef: t.catalogueArtistId,
    ));
  }

  /// Joins the Jam [code] (as typed: any case, spaces around).
  Future<void> join(String code) {
    if (code.trim().isEmpty) {
      state = state.copyWith(message: 'Type the Jam\'s code.');
      return Future.value();
    }
    return _enter((api) => api.join(code));
  }

  Future<void> _enter(
      Future<Result<JamJoined>> Function(JamApi api) call) async {
    if (_entering || state.phase == JamPhase.active) return;
    _entering = true;
    try {
      _stop();
      state = const JamSession(phase: JamPhase.connecting);
      final api = await ref.read(jamApiProvider.future);
      if (api == null) {
        state = const JamSession(
            message: 'Your server has no Jam yet. Ask whoever runs it to '
                'switch it on.');
        return;
      }
      final result = await call(api);
      final joined = result.valueOrNull;
      if (joined == null) {
        state = JamSession(message: result.failureOrNull!.message);
        return;
      }
      state = JamSession(
        phase: JamPhase.active,
        code: joined.code,
        me: joined.you,
        state: joined.state,
      );
      _listen(api, joined.code);
      _watchClock(api);
    } finally {
      _entering = false;
    }
  }

  /// What is shown is this phone's guess at what the hub will say to a command
  /// just sent (see [send]); the hub's own state of that revision replaces it.
  bool _guessed = false;

  /// Applies a state from the hub unless it is older than what is shown. A guess
  /// is replaced by the hub's state of the same revision (the hub has the last
  /// word); a real state is only replaced by a newer one.
  void _apply(SessionState incoming) {
    final current = state.state;
    if (current != null &&
        (_guessed ? incoming.rev < current.rev : incoming.rev <= current.rev)) {
      return;
    }
    _guessed = false;
    state = state.copyWith(state: incoming, reconnecting: false);
  }

  void _end(String message) {
    _stop();
    state = state.copyWith(
        phase: JamPhase.ended, reconnecting: false, message: message);
  }

  void _listen(JamApi api, String code) {
    final generation = _generation;
    var attempt = 0;

    Future<void> run() async {
      while (generation == _generation) {
        final over = Completer<void>();
        _waiting = over;
        var refusal = false;
        _sub = api.events(code).listen(
          (event) {
            if (generation != _generation) return;
            switch (event) {
              case JamStateEvent(:final state):
                attempt = 0;
                _apply(state);
                if (state.ended) _end('The Jam is over.');
              case JamKickedEvent():
                _end('You were removed from the Jam.');
              case JamClosedEvent(:final reason, :final dropped):
                if (!dropped) {
                  refusal = true;
                  _end(reason ?? 'The Jam closed.');
                }
            }
          },
          onDone: () {
            if (!over.isCompleted) over.complete();
          },
        );
        await over.future;
        if (generation != _generation || refusal) return;
        // The stream ended and nothing said why: the network. Listen again; the
        // hub tells a returning phone the whole state at once.
        state = state.copyWith(reconnecting: true);
        final delays = ref.read(jamBackoffProvider);
        await Future<void>.delayed(
            delays[math.min(attempt, delays.length - 1)]);
        attempt++;
      }
    }

    unawaited(run());
  }

  /// Sends one command; `true` when the hub accepted it (the new state is
  /// shown at once), `false` with the reason in [JamSession.message] when not.
  Future<bool> send(Command command) async {
    final code = state.code;
    if (!state.inJam || code == null) return false;
    final api = await ref.read(jamApiProvider.future);
    if (api == null) return false;

    // Show the result at once. The rules are the hub's own (the same code), so
    // the guess is right unless somebody else's command got there first; the
    // phone does not wait for a round trip through the internet to move the bar
    // the person has just dragged.
    final before = state.state;
    final me = state.me;
    SessionState? guess;
    if (before != null && me != null) {
      final predicted =
          reduce(before, command, actorId: me, nowHubMs: hubNowMs());
      if (predicted.ok && predicted.state != before) {
        guess = predicted.state;
        _guessed = true;
        state = state.copyWith(state: guess);
      }
    }

    final result = await api.command(code, command);
    final accepted = result.valueOrNull;
    if (accepted == null) {
      if (guess != null && identical(state.state, guess)) {
        // The hub did not take it: back to what it last said.
        _guessed = false;
        state = state.copyWith(state: before);
      }
      state = state.copyWith(message: result.failureOrNull!.message);
      return false;
    }
    _apply(accepted);
    return true;
  }

  /// Leaves the Jam (the host leaving ends it for everybody).
  Future<void> leave() async {
    final code = state.code;
    final api = await ref.read(jamApiProvider.future);
    _stop();
    state = const JamSession();
    if (code != null && api != null) await api.leave(code);
  }

  /// Something for the person to read (shown once, then dismissed).
  void say(String message) => state = state.copyWith(message: message);

  /// The message was read.
  void dismissMessage() {
    if (state.message != null) state = state.copyWith(message: null);
  }

  // ----------------------------------------------------------------- clock

  void _watchClock(JamApi api) {
    // A few quick samples first so the phone knows the hub's time at once, then
    // one a minute (a phone's clock drifts, and the network changes).
    var quick = 0;
    void next() {
      _warmUp = Timer(const Duration(milliseconds: 250), () async {
        await sampleClock();
        if (++quick < 3) next();
      });
    }

    unawaited(sampleClock());
    next();
    _clockTimer =
        Timer.periodic(ref.read(jamClockEveryProvider), (_) => sampleClock());
  }

  /// One question to the hub's clock.
  Future<void> sampleClock() async {
    final api = await ref.read(jamApiProvider.future);
    if (api == null) return;
    final result = await api.sampleClock();
    final sample = result.valueOrNull;
    if (sample != null) _clock.add(sample);
  }

  /// What time it is at the hub, from this phone's clock and what it learned.
  int hubNowMs() => _clock.hubNow(ref.read(jamNowProvider)());

  /// Where the current song is right now, by the hub's clock.
  int positionNowMs() => state.state?.positionAt(hubNowMs()) ?? 0;
}

/// Whether the phone that plays is still getting the Jam's song: a song it does
/// not have is fetched first. The speaker sets it; the player reads it.
class JamLoading extends Notifier<bool> {
  @override
  bool build() => false;

  // ignore: use_setters_to_change_properties
  void set(bool value) => state = value;
}

final jamLoadingProvider = NotifierProvider<JamLoading, bool>(JamLoading.new);

final jamControllerProvider =
    NotifierProvider<JamController, JamSession>(JamController.new);
