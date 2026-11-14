import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../domain/server_reachability.dart';
import 'providers.dart';

export '../domain/server_reachability.dart';

/// How long a problem must last before it is said: a blink of the network is not news. It is the blink filter of [serverReachabilityProvider]
/// (entering an away state waits this long, unless there is no network at all), so the strip, the grey rows and the player all see the same
/// calm state.
final connectionGraceProvider =
    Provider<Duration>((ref) => const Duration(seconds: 4));

/// RAW FACT: what the last look at the person's server's addresses found (`EndpointResolver.finding`), as it changes. [ServerFinding.unknown]
/// when there is no server (a person who has not set one up is told nothing about it) and until the first look. It says nothing about the
/// network, Android's internet check or any screen: read [serverReachabilityProvider] unless you are building it.
final serverFindingProvider = StreamProvider<ServerFinding>((ref) async* {
  final session = await ref.watch(sessionProvider.future);
  if (session == null) {
    yield ServerFinding.unknown;
    return;
  }
  yield* currentThenChanges<ServerFinding>(
      () => session.endpoints.finding, session.endpoints.findings);
});

/// RAW FACT: the address that answered with another server's key while none proved itself (docs/31 CN-11), or `null`. Only the words of the
/// strip ("Another server answers at ...") read it; whether to say anything is [serverReachabilityProvider]'s.
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

/// THE ONE STATE of "can I reach my server" (P1-17, AUDIT B-17, `docs/31`): every reader asks this and nothing underneath it. It is
/// [reachabilityOf] of the three raw facts (the link, [serverFindingProvider], and Android's own "internet found", asked fresh at the moment
/// the state decides and never through a screen), with ONE blink filter: **entering** an away state waits [connectionGraceProvider] (a blink of
/// the network is not news, and a row must not flicker grey), unless there is no network at all, which is said at once (P1-09); **leaving** an
/// away state, and changing from one away state to another, is at once. It holds for as long as the outage does.
///
/// What it is not: the strip is a presenter over it ([ConnectionStripNotifier]: said once, for a few seconds), and a FRESH look at the server
/// (the player's `recheck`) is newer than it and may know better for the tap that asked.
class ServerReachabilityNotifier extends Notifier<ServerReachability> {
  Timer? _grace;

  /// Counts evaluations: an answer from Android that arrives after a newer evaluation began belongs to a world that is gone.
  int _round = 0;

  @override
  ServerReachability build() {
    ref.onDispose(() {
      _round++;
      _grace?.cancel();
    });
    ref.listen(networkKindProvider, (_, __) => unawaited(_evaluate()));
    ref.listen(serverFindingProvider, (_, __) => unawaited(_evaluate()));
    final first = reachabilityOf(
        hasNetwork: _hasNetwork, finding: _finding, internetFound: null);
    if (first.isAway && _hasNetwork) {
      // A silent server at the first look: say it only if it lasts.
      _later();
      return ServerReachability.unknown;
    }
    return first;
  }

  bool get _hasNetwork =>
      ref.read(networkKindProvider).value != NetworkKind.none;

  ServerFinding get _finding =>
      ref.read(serverFindingProvider).value ?? ServerFinding.unknown;

  /// Android's last answer to "internet found" (`null`: never asked, or it cannot say: internet is assumed).
  bool? _internetFound;

  /// The judgement now, with the last answer of Android.
  ServerReachability _judge() => reachabilityOf(
      hasNetwork: _hasNetwork,
      finding: _finding,
      internetFound: _internetFound);

  /// Asks Android now, when it matters (a network with a silent server), and corrects the state if the answer changes the words: an answer
  /// that takes long, or never comes (a test, a platform without the channel), must not hold the state back, so the state is set first with
  /// what was last known and refined when the answer arrives. Never asked while the server answers (a home Wi-Fi with no line out is fine) and
  /// never through a screen.
  Future<void> _refine(int round) async {
    if (!_hasNetwork || _finding != ServerFinding.silent) return;
    final answer = await ref.read(networkValidationProvider).validated();
    if (round != _round) return; // a newer evaluation owns the state
    _internetFound = answer;
    if (state.isAway) _set(_judge());
  }

  void _set(ServerReachability next) {
    if (state != next) state = next;
  }

  Future<void> _evaluate() async {
    final round = ++_round;
    final hasNetwork = _hasNetwork;
    final finding = _finding;
    final neutral = hasNetwork &&
        (finding == ServerFinding.unknown ||
            finding == ServerFinding.answering);
    if (!hasNetwork || neutral) {
      // Nothing to wait for: no network is said at once, and what is fine (or not known) is shown at once.
      _grace?.cancel();
      _grace = null;
      _set(reachabilityOf(
          hasNetwork: hasNetwork, finding: finding, internetFound: null));
      return;
    }
    if (state.isAway) {
      // Already saying something: the sentence changes at once (Android decides between "offline" and "your server").
      _grace?.cancel();
      _grace = null;
      _set(_judge());
      await _refine(round);
      return;
    }
    // Saying nothing: wait, it may be a blink.
    if (_grace == null) _later();
  }

  void _later() {
    _grace?.cancel();
    _grace = Timer(ref.read(connectionGraceProvider), () {
      _grace = null;
      unawaited(_enter());
    });
  }

  Future<void> _enter() async {
    final round = _round;
    _set(_judge());
    await _refine(round);
  }
}

final serverReachabilityProvider =
    NotifierProvider<ServerReachabilityNotifier, ServerReachability>(
        ServerReachabilityNotifier.new);

/// How long an outage stays on the strip: it is said once and goes by itself (owner, 2026-10-31: "all day telling me it cannot connect,
/// sure we get it"). The details stay on Settings > Your server.
final connectionShownForProvider =
    Provider<Duration>((ref) => const Duration(seconds: 5));

/// How long everything must have worked before a later problem counts as a new outage. The radio coming back on while the old answer
/// about the server is still "fine" is not recovery: it is the same outage.
final connectionRecoveredProvider =
    Provider<Duration>((ref) => const Duration(seconds: 10));

/// What the strip shows: `null` (nothing) or the away state to say. [serverReachabilityProvider] is what is wrong (the player and every grey
/// row read it); the strip is only a PRESENTER over it and says an outage once: no internet and a server that does not answer are one outage to
/// the person (the 4G radio is on and there is no data), shown for a few seconds or until the cross, and not again until everything has worked
/// for a while. The state already waited out a blink of the SERVER; the strip waits out a blink of the radio itself (`noNetwork` is at once for
/// the rows and the player, but a flash of the strip for a second of lost signal is not news, D-45): the one place a presenter holds back.
class ConnectionStripNotifier extends Notifier<ServerReachability?> {
  Timer? _hideTimer;
  Timer? _recoveredTimer;
  Timer? _waitTimer;
  bool _said = false;

  @override
  ServerReachability? build() {
    ref.onDispose(() {
      _hideTimer?.cancel();
      _recoveredTimer?.cancel();
      _waitTimer?.cancel();
    });
    ref.listen(serverReachabilityProvider, (_, now) => _follow(now));
    return _follow(ref.read(serverReachabilityProvider), initial: true);
  }

  ServerReachability? _follow(ServerReachability reach,
      {bool initial = false, bool waited = false}) {
    ServerReachability? shown;
    if (!reach.isAway) {
      _waitTimer?.cancel();
      _waitTimer = null;
      _hideTimer?.cancel();
      _hideTimer = null;
      if (_said) {
        _recoveredTimer ??= Timer(ref.read(connectionRecoveredProvider), () {
          _recoveredTimer = null;
          _said = false;
        });
      }
      shown = null;
    } else {
      _recoveredTimer?.cancel();
      _recoveredTimer = null;
      if (_said) {
        shown = null;
      } else if (reach == ServerReachability.noNetwork &&
          !waited &&
          (initial || state == null)) {
        // Nothing is showing and the radio has just gone: say it only if it lasts.
        _waitTimer ??= Timer(ref.read(connectionGraceProvider), () {
          _waitTimer = null;
          final now = ref.read(serverReachabilityProvider);
          if (now.isAway) _follow(now, waited: true);
        });
        shown = null;
      } else {
        _waitTimer?.cancel();
        _waitTimer = null;
        shown = reach;
        _hideTimer ??= Timer(ref.read(connectionShownForProvider), () {
          _hideTimer = null;
          _said = true;
          if (state != null) state = null;
        });
      }
    }
    if (!initial && state != shown) state = shown;
    return shown;
  }

  /// The cross on the strip: this outage has been said.
  void dismiss() {
    if (state == null) return;
    _hideTimer?.cancel();
    _hideTimer = null;
    _said = true;
    state = null;
  }
}

final connectionStripProvider =
    NotifierProvider<ConnectionStripNotifier, ServerReachability?>(
        ConnectionStripNotifier.new);
