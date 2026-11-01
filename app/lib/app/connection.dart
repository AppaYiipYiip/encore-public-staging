import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../features/jam/jam_providers.dart';
import 'providers.dart';

/// What the person is told about the connection (a slim strip above the
/// player on every main screen): "a widget to show you lost the internet"
/// (the owner, 2026-10-17).
enum ConnectionProblem {
  none,

  /// The phone has no internet: downloaded music still plays.
  offline,

  /// The phone is online but the music server does not answer.
  serverUnreachable,

  /// A Jam lost its connection and is listening again.
  jamReconnecting,

  /// An address answers, but with the key of **another server** (docs/31 CN-11, O-6): nothing is sent to it. Not "offline": the phone is
  /// online and something is there, only it is not the person's server. D-45's one sentence is for an outage; this is a different thing.
  anotherServer,
}

extension ConnectionProblemMeaning on ConnectionProblem {
  /// The person's music server is away as far as the player is concerned: it does not answer, or somebody else does.
  bool get serverIsAway =>
      this == ConnectionProblem.serverUnreachable ||
      this == ConnectionProblem.anotherServer;
}

/// How long a problem must last before it is shown: a blink of the network is
/// not news.
final connectionGraceProvider =
    Provider<Duration>((ref) => const Duration(seconds: 4));

/// Whether the person's music server answers. `true` when there is none (a
/// person who has not set one up is told nothing about it).
final serverReachableProvider = StreamProvider<bool>((ref) async* {
  final session = await ref.watch(sessionProvider.future);
  if (session == null) {
    yield true;
    return;
  }
  yield* reachabilityStream(
      () => session.endpoints.isReachable, session.endpoints.reachability);
});

/// The address that answered with another server's key while none proved itself (docs/31 CN-11), or `null`.
final anotherServerAtProvider = StreamProvider<Uri?>((ref) async* {
  final session = await ref.watch(sessionProvider.future);
  if (session == null) {
    yield null;
    return;
  }
  yield* currentThenChanges<Uri?>(
      () => session.endpoints.anotherServerAt, session.endpoints.anotherServer);
});

/// The current value, then every change, **without a gap between the two**.
///
/// The first version yielded the current value and only then subscribed to the
/// changes; the subscription happens when the consumer asks for more, so a
/// change announced in between was lost and the strip "Can't reach your server"
/// stayed up for good over a server that worked (found on 2026-10-18 on a cold
/// start from a share, when the answer arrives within milliseconds). Here the
/// subscription comes first, so nothing announced after it is missed, and the
/// current value is read after it, so nothing before it is either.
Stream<bool> reachabilityStream(
        bool Function() current, Stream<bool> changes) =>
    currentThenChanges<bool>(current, changes);

/// [reachabilityStream] for any value.
Stream<T> currentThenChanges<T>(T Function() current, Stream<T> changes) {
  late final StreamController<T> out;
  StreamSubscription<T>? sub;
  out = StreamController<T>(
    onListen: () {
      sub = changes.listen(out.add, onError: out.addError);
      out.add(current());
    },
    onCancel: () {
      unawaited(sub?.cancel());
      unawaited(out.close());
    },
  );
  return out.stream;
}

/// The problem to show now, or [ConnectionProblem.none]. It appears after
/// [connectionGraceProvider] and goes away at once.
class ConnectionProblemNotifier extends Notifier<ConnectionProblem> {
  Timer? _timer;

  @override
  ConnectionProblem build() {
    ref.onDispose(() => _timer?.cancel());
    ref.listen(networkKindProvider, (_, __) => _evaluate());
    ref.listen(serverReachableProvider, (_, __) => _evaluate());
    ref.listen(anotherServerAtProvider, (_, __) => _evaluate());
    ref.listen(jamControllerProvider.select((j) => j.reconnecting && j.inJam),
        (_, __) => _evaluate());
    final first = _raw();
    if (first != ConnectionProblem.none) _later();
    return ConnectionProblem.none;
  }

  /// What is wrong this instant, most basic first: no internet is the reason
  /// for the others.
  ConnectionProblem _raw() {
    if (ref.read(networkKindProvider).value == NetworkKind.none) {
      return ConnectionProblem.offline;
    }
    if (ref.read(serverReachableProvider).value == false) {
      return ref.read(anotherServerAtProvider).value != null
          ? ConnectionProblem.anotherServer
          : ConnectionProblem.serverUnreachable;
    }
    final jam = ref.read(jamControllerProvider);
    if (jam.inJam && jam.reconnecting) return ConnectionProblem.jamReconnecting;
    return ConnectionProblem.none;
  }

  void _evaluate() {
    final raw = _raw();
    if (raw == ConnectionProblem.none) {
      _timer?.cancel();
      _timer = null;
      if (state != ConnectionProblem.none) state = ConnectionProblem.none;
      return;
    }
    if (raw == state) {
      _timer?.cancel();
      _timer = null;
      return;
    }
    // Already showing something: the sentence changes at once. Showing
    // nothing: wait, it may be a blink.
    if (state != ConnectionProblem.none) {
      state = raw;
    } else if (_timer == null) {
      _later();
    }
  }

  void _later() {
    _timer?.cancel();
    _timer = Timer(ref.read(connectionGraceProvider), () {
      _timer = null;
      state = _raw();
    });
  }
}

final connectionProblemProvider =
    NotifierProvider<ConnectionProblemNotifier, ConnectionProblem>(
        ConnectionProblemNotifier.new);

/// How long an outage stays on the strip: it is said once and goes by itself (owner, 2026-10-31: "all day telling me it cannot connect,
/// sure we get it"). The details stay on Settings > Your server.
final connectionShownForProvider =
    Provider<Duration>((ref) => const Duration(seconds: 5));

/// How long everything must have worked before a later problem counts as a new outage. The radio coming back on while the old answer
/// about the server is still "fine" is not recovery: it is the same outage.
final connectionRecoveredProvider =
    Provider<Duration>((ref) => const Duration(seconds: 10));

/// What the strip shows. [connectionProblemProvider] is what is wrong (the player reads it to know its server is away); the strip says an
/// outage once: no internet and a server that does not answer are one outage to the person (the 4G radio is on and there is no data), shown for
/// a few seconds or until the cross, and not again until everything has worked for a while. A Jam that is reconnecting stays while it lasts.
class ConnectionStripNotifier extends Notifier<ConnectionProblem> {
  Timer? _hideTimer;
  Timer? _recoveredTimer;
  bool _said = false;

  static bool _isOutage(ConnectionProblem p) =>
      p == ConnectionProblem.offline ||
      p == ConnectionProblem.serverUnreachable ||
      p == ConnectionProblem.anotherServer;

  @override
  ConnectionProblem build() {
    ref.onDispose(() {
      _hideTimer?.cancel();
      _recoveredTimer?.cancel();
    });
    ref.listen(connectionProblemProvider, (_, now) => _follow(now));
    return _follow(ref.read(connectionProblemProvider), initial: true);
  }

  ConnectionProblem _follow(ConnectionProblem problem, {bool initial = false}) {
    ConnectionProblem shown;
    if (problem == ConnectionProblem.none) {
      _hideTimer?.cancel();
      _hideTimer = null;
      if (_said) {
        _recoveredTimer ??= Timer(ref.read(connectionRecoveredProvider), () {
          _recoveredTimer = null;
          _said = false;
        });
      }
      shown = ConnectionProblem.none;
    } else if (!_isOutage(problem)) {
      _hideTimer?.cancel();
      _hideTimer = null;
      shown = problem;
    } else {
      _recoveredTimer?.cancel();
      _recoveredTimer = null;
      if (_said) {
        shown = ConnectionProblem.none;
      } else {
        shown = problem;
        _hideTimer ??= Timer(ref.read(connectionShownForProvider), () {
          _hideTimer = null;
          _said = true;
          if (_isOutage(state)) state = ConnectionProblem.none;
        });
      }
    }
    if (!initial && state != shown) state = shown;
    return shown;
  }

  /// The cross on the strip: this outage has been said.
  void dismiss() {
    if (!_isOutage(state)) return;
    _hideTimer?.cancel();
    _hideTimer = null;
    _said = true;
    state = ConnectionProblem.none;
  }
}

final connectionStripProvider =
    NotifierProvider<ConnectionStripNotifier, ConnectionProblem>(
        ConnectionStripNotifier.new);
