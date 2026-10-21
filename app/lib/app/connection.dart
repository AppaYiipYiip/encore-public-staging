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

/// The current value, then every change, **without a gap between the two**.
///
/// The first version yielded the current value and only then subscribed to the
/// changes; the subscription happens when the consumer asks for more, so a
/// change announced in between was lost and the strip "Can't reach your server"
/// stayed up for good over a server that worked (found on 2026-10-18 on a cold
/// start from a share, when the answer arrives within milliseconds). Here the
/// subscription comes first, so nothing announced after it is missed, and the
/// current value is read after it, so nothing before it is either.
Stream<bool> reachabilityStream(bool Function() current, Stream<bool> changes) {
  late final StreamController<bool> out;
  StreamSubscription<bool>? sub;
  out = StreamController<bool>(
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
      return ConnectionProblem.serverUnreachable;
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
