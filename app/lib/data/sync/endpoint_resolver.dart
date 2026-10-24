import 'dart:async';

import 'package:meta/meta.dart';

import '../../core/logger.dart';
import '../../core/server_url.dart';

/// One candidate way to reach a server (ADR-028), e.g. "Home" (LAN) or
/// "Tailscale".
@immutable
class ServerEndpoint {
  const ServerEndpoint({required this.label, required this.url});

  factory ServerEndpoint.fromJson(Map<String, dynamic> json) => ServerEndpoint(
        label: (json['label'] as String?) ?? 'Server',
        // Older builds stored `http://host:4533?#`; always clean on load.
        url: canonicalBaseUrl(Uri.parse(json['url'] as String)),
      );

  final String label;
  final Uri url;

  Map<String, dynamic> toJson() => {'label': label, 'url': url.toString()};

  @override
  bool operator ==(Object other) =>
      other is ServerEndpoint && other.url == url && other.label == label;

  @override
  int get hashCode => Object.hash(label, url);

  @override
  String toString() => '$label ($url)';
}

/// Chooses which of several candidate URLs to talk to, without ever blocking
/// the UI.
///
/// * Candidates are raced "happy eyeballs" style: the first starts at once,
///   later ones start after [stagger] unless an earlier one already answered.
///   The first successful probe wins; the list order is the tie-break.
/// * [current] is always available (last known good, else the first
///   candidate), so callers never wait for resolution.
/// * Re-resolution is triggered by network changes, by repeated failures
///   ([reportFailure]) and by [resolve] with `force`.
/// * With [requireVerified] (docs/11 ADR-R40) the probe is "has this address proved it is the server?", and [currentUrl] - the one address
///   every request, stream and cover is built from - is only ever an address that has. Before the first race has finished, after a race that
///   found nothing, and after [invalidate] (the network changed), it is [unverifiedUrl], which cannot leave the phone: no login, token or
///   signed address is ever sent to an address nobody has checked.
class EndpointResolver {
  EndpointResolver({
    required List<ServerEndpoint> candidates,
    required Future<bool> Function(Uri base) probe,
    this.requireVerified = false,
    this.stagger = const Duration(milliseconds: 350),
    this.probeTimeout = const Duration(seconds: 4),
    this.failuresBeforeReresolve = 2,
    Future<void> Function(Duration)? delay,
  })  : assert(candidates.isNotEmpty, 'at least one endpoint is required'),
        _candidates = List.of(candidates),
        _probe = probe,
        _delay = delay ?? Future<void>.delayed,
        _current = candidates.first,
        _verified = !requireVerified;

  /// An address that cannot be reached by anything (`.invalid` is reserved: it never resolves). What [currentUrl] is while nothing is verified.
  static final Uri unverifiedUrl =
      Uri(scheme: 'http', host: 'unverified.invalid', path: '/');

  /// Whether [currentUrl] may only be an address that proved who it is.
  final bool requireVerified;

  final List<ServerEndpoint> _candidates;
  final Future<bool> Function(Uri base) _probe;
  final Future<void> Function(Duration) _delay;
  final Duration stagger;
  final Duration probeTimeout;
  final int failuresBeforeReresolve;

  final StreamController<ServerEndpoint> _changes =
      StreamController<ServerEndpoint>.broadcast();
  ServerEndpoint _current;
  bool _verified;
  Future<ServerEndpoint?>? _inFlight;
  int _consecutiveFailures = 0;
  bool _reachable = false;
  final StreamController<bool> _reachability =
      StreamController<bool>.broadcast();

  void _setReachable(bool value) {
    if (value == _reachable) return;
    _reachable = value;
    if (!_reachability.isClosed) _reachability.add(value);
  }

  /// Base URL requests should use right now: the last winner of the race, or - when verification is required and no address has proved
  /// itself (yet, or any more) - [unverifiedUrl].
  Uri get currentUrl => _verified ? _current.url : unverifiedUrl;

  /// The address shown to the person (its label and host), verified or not.
  ServerEndpoint get current => _current;
  List<ServerEndpoint> get candidates => List.unmodifiable(_candidates);

  /// Whether [currentUrl] is an address that has proved itself (always true when verification is not required).
  bool get isVerified => _verified;

  /// The network changed (or the phone woke up somewhere else): nothing is known about the address any more. Requests stop going out until
  /// the next race has found an address that proves itself.
  void invalidate() {
    if (requireVerified) _verified = false;
  }

  /// Adds addresses the server itself told this phone about (`GET /encore/api/v1/server`); known ones are left alone. They are only ever
  /// used after they have proved themselves in a race.
  void addCandidates(Iterable<ServerEndpoint> found) {
    for (final endpoint in found) {
      if (_candidates.any((c) => c.url == endpoint.url)) continue;
      _candidates.add(endpoint);
    }
  }

  /// `true` once a probe has succeeded and until a full resolution fails.
  bool get isReachable => _reachable;

  /// Emits whenever the chosen endpoint changes.
  Stream<ServerEndpoint> get changes => _changes.stream;

  /// Emits `true` or `false` whenever [isReachable] changes (the app tells the
  /// person when the server cannot be reached).
  Stream<bool> get reachability => _reachability.stream;

  /// Races the candidates. Returns the winner, or `null` if none answered
  /// (in which case [current] is left untouched).
  Future<ServerEndpoint?> resolve() =>
      _inFlight ??= _resolve().whenComplete(() => _inFlight = null);

  Future<ServerEndpoint?> _resolve() async {
    final completer = Completer<ServerEndpoint?>();
    // The list as it is now: an address added while the race runs waits for the next one.
    final raced = List.of(_candidates);
    var pending = raced.length;
    var decided = false;

    void settle(ServerEndpoint? winner) {
      if (decided) return;
      if (winner != null) {
        decided = true;
        completer.complete(winner);
      } else if (--pending == 0) {
        decided = true;
        completer.complete(null);
      }
    }

    for (var i = 0; i < raced.length; i++) {
      final endpoint = raced[i];
      unawaited(() async {
        if (i > 0) {
          await _delay(stagger * i);
          if (decided) return; // an earlier candidate already won
        }
        var ok = false;
        try {
          ok = await _probe(endpoint.url).timeout(probeTimeout);
        } on Object catch (error) {
          Log.debug('endpoint', '$endpoint probe failed: ${error.runtimeType}');
        }
        settle(ok ? endpoint : null);
      }());
    }

    final winner = await completer.future;
    if (winner != null) {
      _verified = true;
      _setReachable(true);
      _consecutiveFailures = 0;
      if (winner != _current) {
        _current = winner;
        Log.info('endpoint', 'using $winner');
        if (!_changes.isClosed) _changes.add(winner);
      }
    } else {
      // Nothing proved itself: the last winner may now be somebody else's address (another network), so it is not used any more.
      if (requireVerified) _verified = false;
      _setReachable(false);
      Log.info('endpoint', 'no endpoint reachable');
    }
    return winner;
  }

  /// Call when a request to [current] failed at the network level. After
  /// [failuresBeforeReresolve] consecutive failures the candidates are raced
  /// again (the user may have left home Wi-Fi).
  void reportFailure() {
    _consecutiveFailures++;
    if (_consecutiveFailures >= failuresBeforeReresolve) {
      _consecutiveFailures = 0;
      unawaited(resolve());
    }
  }

  void reportSuccess() {
    _consecutiveFailures = 0;
    _setReachable(true);
  }

  Future<void> dispose() async {
    await _changes.close();
    await _reachability.close();
  }
}
