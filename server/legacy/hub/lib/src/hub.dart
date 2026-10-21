import 'dart:math';

import 'package:encore_session/encore_session.dart';
import 'package:encore_session/encore_session.dart' as engine;

/// What a listener of a session is told.
sealed class HubEvent {
  const HubEvent();
}

/// The session is now like this (sent first, and after every change).
class StateEvent extends HubEvent {
  const StateEvent(this.state);
  final SessionState state;
}

/// The host sent this person away: their phone should leave.
class KickedEvent extends HubEvent {
  const KickedEvent();
}

/// Somebody who listens; [cancel] when they stop.
class Subscription {
  Subscription._(this._hub, this._code, this._user, this._listener);

  final Hub _hub;
  final String _code;
  final String _user;
  final void Function(HubEvent) _listener;

  void cancel() => _hub._unsubscribe(_code, this);

  String get user => _user;
}

/// One listening session.
class Session {
  Session._(this.code, this.state, this.touchedMs);

  /// What people type to join.
  final String code;
  SessionState state;
  int touchedMs;
  final List<Subscription> _listeners = [];
}

/// Holds the listening sessions in memory (a session is an evening, not a
/// record), applies every command with the engine's rules and the hub's clock,
/// and tells the listeners the new state.
///
/// Pure of the network: the HTTP layer ([HubServer]) only turns requests into
/// calls on this class and events into a stream.
class Hub {
  Hub({
    required int Function() clock,
    Random? random,
    this.maxSessions = 100,
    this.idleAfter = const Duration(hours: 6),
  })  : _clock = clock,
        _random = random ?? Random.secure();

  /// Milliseconds on the hub's own clock (the same one phones estimate).
  final int Function() _clock;
  final Random _random;
  final int maxSessions;
  final Duration idleAfter;

  final Map<String, Session> _sessions = {};

  /// Letters and digits that cannot be mistaken for each other.
  static const _alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';

  int get sessionCount => _sessions.length;

  /// The hub's own clock, in milliseconds (what phones estimate).
  int get nowMs => _clock();

  String _newCode() {
    while (true) {
      final code = String.fromCharCodes([
        for (var i = 0; i < 6; i++)
          _alphabet.codeUnitAt(_random.nextInt(_alphabet.length)),
      ]);
      if (!_sessions.containsKey(code)) return code;
    }
  }

  static String _normal(String code) => code.trim().toUpperCase();

  Session? find(String code) => _sessions[_normal(code)];

  void _tell(Session session) {
    final event = StateEvent(session.state);
    for (final listener in [...session._listeners]) {
      listener._listener(event);
    }
  }

  void _forget(Session session) {
    _sessions.remove(session.code);
    session._listeners.clear();
  }

  /// A new session with [user] as its host, or `null` when the hub is full.
  /// A person hosts one session at a time: the earlier one ends.
  Session? create(String user) {
    for (final old in _sessions.values.toList()) {
      final host = old.state.members.where((m) => m.isHost).firstOrNull;
      if (host?.id == user) _end(old);
    }
    if (_sessions.length >= maxSessions) return null;
    final code = _newCode();
    final started = engine.join(
      const SessionState(),
      Member(id: user, name: _name(user), role: Role.host),
    );
    final session = Session._(code, started.state, _clock());
    _sessions[code] = session;
    return session;
  }

  static String _name(String user) =>
      user.length <= 40 ? user : user.substring(0, 40);

  void _end(Session session) {
    final host = session.state.members.where((m) => m.isHost).firstOrNull;
    if (host == null) {
      _forget(session);
      return;
    }
    session.state = engine.leave(session.state, host.id).state;
    _tell(session);
    _forget(session);
  }

  Outcome _missing() => const Outcome.refused(
      SessionState(), 'there is no session with that code');

  /// [user] joins the session [code].
  Outcome join(String code, String user) {
    final session = find(code);
    if (session == null) return _missing();
    final outcome =
        engine.join(session.state, Member(id: user, name: _name(user)));
    if (outcome.ok) {
      session.state = outcome.state;
      session.touchedMs = _clock();
      _tell(session);
    }
    return outcome;
  }

  /// Applies [command] from [user] to the session [code].
  Outcome command(String code, String user, Command command) {
    final session = find(code);
    if (session == null) return _missing();
    final outcome = engine.reduce(session.state, command,
        actorId: user, nowHubMs: _clock());
    if (!outcome.ok) return outcome;
    final kicked =
        command is Kick ? session.state.member(command.memberId) : null;
    final changed = !identical(outcome.state, session.state) &&
        outcome.state.rev != session.state.rev;
    session.state = outcome.state;
    session.touchedMs = _clock();
    if (kicked != null) {
      // Told first, then dropped from the listeners: the state that follows
      // is for the people who are still there.
      for (final l
          in session._listeners.where((l) => l.user == kicked.id).toList()) {
        l._listener(const KickedEvent());
        session._listeners.remove(l);
      }
    }
    if (changed) _tell(session);
    return outcome;
  }

  /// [user] leaves; when the host leaves the session ends for everybody.
  Outcome leaveSession(String code, String user) {
    final session = find(code);
    if (session == null) return _missing();
    final who = session.state.member(user);
    if (who == null) return Outcome.accepted(session.state);
    final outcome = engine.leave(session.state, user);
    session.state = outcome.state;
    session.touchedMs = _clock();
    session._listeners.removeWhere((l) => l.user == user && !who.isHost);
    _tell(session);
    if (session.state.ended) _forget(session);
    return outcome;
  }

  /// Starts telling [onEvent] about the session; the current state comes at
  /// once. `null` when there is no such session or [user] is not in it.
  Subscription? subscribe(
      String code, String user, void Function(HubEvent) onEvent) {
    final session = find(code);
    if (session == null || session.state.member(user) == null) return null;
    final subscription = Subscription._(this, session.code, user, onEvent);
    session._listeners.add(subscription);
    onEvent(StateEvent(session.state));
    return subscription;
  }

  void _unsubscribe(String code, Subscription subscription) {
    _sessions[code]?._listeners.remove(subscription);
  }

  /// Ends the sessions nobody has touched for [idleAfter]; how many.
  int sweep() {
    final cutoff = _clock() - idleAfter.inMilliseconds;
    var ended = 0;
    for (final session in _sessions.values.toList()) {
      if (session.touchedMs < cutoff) {
        _end(session);
        ended++;
      }
    }
    return ended;
  }
}
