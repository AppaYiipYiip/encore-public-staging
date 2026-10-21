import 'dart:convert';

import '../../core/clock.dart';
import '../../core/power.dart';
import '../sync/sync_state_store.dart';

/// One stretch of listening and what the battery did during it.
class ListeningSession {
  const ListeningSession({
    required this.startMs,
    required this.endMs,
    required this.startLevel,
    required this.endLevel,
    required this.charged,
    required this.screenOffMs,
  });

  factory ListeningSession.fromJson(Map<String, dynamic> j) => ListeningSession(
        startMs: (j['s'] as num).toInt(),
        endMs: (j['e'] as num).toInt(),
        startLevel: (j['sl'] as num).toInt(),
        endLevel: (j['el'] as num).toInt(),
        charged: j['c'] == true,
        screenOffMs: (j['so'] as num?)?.toInt() ?? 0,
      );

  final int startMs;
  final int endMs;
  final int startLevel;
  final int endLevel;

  /// The phone was charging at some point, so the drop is not the app's.
  final bool charged;

  /// Time with the screen off while this was playing (only counted at the
  /// moments the log looked).
  final int screenOffMs;

  Duration get length => Duration(milliseconds: endMs - startMs);

  /// Percentage points the battery lost.
  int get drop => startLevel - endLevel;

  /// Percent per hour; `null` when it cannot be trusted (charging, too short
  /// for a 1 % battery step to mean anything, battery went up).
  double? get percentPerHour {
    if (charged || length < const Duration(minutes: 20) || drop < 0) {
      return null;
    }
    return drop / (length.inMilliseconds / Duration.millisecondsPerHour);
  }

  Map<String, dynamic> toJson() => {
        's': startMs,
        'e': endMs,
        'sl': startLevel,
        'el': endLevel,
        'c': charged,
        'so': screenOffMs,
      };
}

/// Remembers listening sessions with the battery level at both ends, so the
/// owner's daily-driver test produces real "% per hour of listening" numbers
/// on the phone (the emulator has no discharge to measure).
///
/// Everything stays on the phone (the `sync_state` table) and shows up in
/// Settings > About > Diagnostics.
class ListeningLog {
  ListeningLog({
    required SyncStateStore store,
    required PowerProbe probe,
    Clock clock = const SystemClock(),
    this.mergeGap = const Duration(minutes: 3),
    this.keep = 30,
  })  : _store = store,
        _probe = probe,
        _clock = clock;

  static const _kSessions = 'power.sessions';
  static const _kOpen = 'power.open';

  final SyncStateStore _store;
  final PowerProbe _probe;
  final Clock _clock;

  /// A pause shorter than this does not end the session (skipping, a call).
  final Duration mergeGap;

  /// How many sessions are kept.
  final int keep;

  int get _nowMs => _clock.now().millisecondsSinceEpoch;

  /// Playback started (or resumed).
  Future<void> started() async {
    final power = await _probe.read();
    if (power == null) return;
    final open = await _readOpen();
    final recorded = await sessions();
    // Resumed shortly after the last one ended: it is the same listening.
    if (open == null &&
        recorded.isNotEmpty &&
        _nowMs - recorded.last.endMs <= mergeGap.inMilliseconds) {
      final last = recorded.last;
      await _store.set(
          _kSessions, _encode(recorded.sublist(0, recorded.length - 1)));
      await _writeOpen({
        's': last.startMs,
        'sl': last.startLevel,
        'c': last.charged || power.charging,
        'so': last.screenOffMs,
      });
      return;
    }
    if (open != null) return; // already counting
    await _writeOpen({
      's': _nowMs,
      'sl': power.level,
      'c': power.charging,
      'so': 0,
    });
  }

  /// Playback paused or stopped.
  Future<void> stopped() async {
    final open = await _readOpen();
    if (open == null) return;
    final power = await _probe.read();
    if (power == null) {
      await _store.set(_kOpen, null);
      return;
    }
    final session = ListeningSession(
      startMs: open['s'] as int,
      endMs: _nowMs,
      startLevel: open['sl'] as int,
      endLevel: power.level,
      charged: (open['c'] == true) || power.charging,
      screenOffMs: (open['so'] as int?) ?? 0,
    );
    await _store.set(_kOpen, null);
    // Less than a minute of audio is a skip, not listening.
    if (session.length < const Duration(minutes: 1)) return;
    final recorded = await sessions();
    recorded.add(session);
    final kept = recorded.length > keep
        ? recorded.sublist(recorded.length - keep)
        : recorded;
    await _store.set(_kSessions, _encode(kept));
  }

  /// Called now and then during playback: notes charging and screen state.
  Future<void> tick() async {
    final open = await _readOpen();
    if (open == null) return;
    final power = await _probe.read();
    if (power == null) return;
    open['c'] = (open['c'] == true) || power.charging;
    if (!power.screenOn) {
      open['so'] = ((open['so'] as int?) ?? 0) +
          const Duration(minutes: 1).inMilliseconds;
    }
    await _writeOpen(open);
  }

  /// Recorded sessions, oldest first.
  Future<List<ListeningSession>> sessions() async {
    final raw = await _store.get(_kSessions);
    if (raw == null) return [];
    try {
      final decoded = jsonDecode(raw);
      if (decoded is List) {
        return [
          for (final e in decoded)
            if (e is Map) ListeningSession.fromJson(e.cast<String, dynamic>()),
        ];
      }
    } on Object {
      // Corrupt: start over.
    }
    return [];
  }

  /// Average battery use over the trustworthy sessions: percent per hour and
  /// how many sessions it is based on.
  static ({double percentPerHour, int sessions})? average(
      Iterable<ListeningSession> sessions) {
    var hours = 0.0;
    var drop = 0;
    var n = 0;
    for (final s in sessions) {
      if (s.percentPerHour == null) continue;
      hours += s.length.inMilliseconds / Duration.millisecondsPerHour;
      drop += s.drop;
      n++;
    }
    if (n == 0 || hours == 0) return null;
    return (percentPerHour: drop / hours, sessions: n);
  }

  String _encode(List<ListeningSession> s) =>
      jsonEncode([for (final e in s) e.toJson()]);

  Future<Map<String, dynamic>?> _readOpen() async {
    final raw = await _store.get(_kOpen);
    if (raw == null) return null;
    try {
      final decoded = jsonDecode(raw);
      if (decoded is Map) return decoded.cast<String, dynamic>();
    } on Object {
      // Ignore.
    }
    return null;
  }

  Future<void> _writeOpen(Map<String, dynamic> value) =>
      _store.set(_kOpen, jsonEncode(value));
}
