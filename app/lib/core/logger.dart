import 'package:flutter/foundation.dart';

/// Severity levels, ordered.
enum LogLevel { debug, info, warn, error }

/// Removes credentials from text before it is logged or stored (ADR-017).
///
/// Handles URL query parameters used by the Subsonic API (`t`, `s`, `p`,
/// `password`, `token`, `apiKey`, `api_key`), `Authorization` headers and JWTs.
String scrubSecrets(String input) {
  var out = input;
  out = out.replaceAllMapped(
    RegExp(
      r'([?&;\s"])(t|s|p|u|password|token|apiKey|api_key|access_token)=([^&\s"]+)',
      caseSensitive: false,
    ),
    (m) {
      // Keep the user name (`u`) readable for debugging, hide the rest.
      final key = m.group(2)!.toLowerCase();
      if (key == 'u') return m.group(0)!;
      return '${m.group(1)}${m.group(2)}=***';
    },
  );
  out = out.replaceAllMapped(
    RegExp(r'(authorization|x-nd-authorization)\s*[:=]\s*\S+(\s+\S+)?',
        caseSensitive: false),
    (m) => '${m.group(1)}: ***',
  );
  out = out.replaceAll(
    RegExp(r'eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}'),
    '***jwt***',
  );
  return out;
}

/// A log record (kept in a ring buffer for the Diagnostics screen).
@immutable
class LogRecord {
  const LogRecord(this.time, this.level, this.tag, this.message);

  final DateTime time;
  final LogLevel level;
  final String tag;
  final String message;

  @override
  String toString() =>
      '${time.toIso8601String()} ${level.name.toUpperCase().padRight(5)} '
      '[$tag] $message';
}

/// Minimal leveled logger with secret scrubbing and an in-memory ring buffer.
///
/// Intentionally tiny: the goal is *no secrets, no `print`, queryable in the
/// app's Diagnostics screen*, not a logging framework.
class Log {
  Log._();

  static LogLevel minLevel = kReleaseMode ? LogLevel.info : LogLevel.debug;
  static const int _capacity = 500;
  static final List<LogRecord> _buffer = <LogRecord>[];

  /// Optional sink (tests, crash reporter). Receives scrubbed records.
  static void Function(LogRecord record)? sink;

  /// Most recent records, oldest first.
  static List<LogRecord> get recent => List.unmodifiable(_buffer);

  static void clear() => _buffer.clear();

  static void debug(String tag, String message) =>
      _log(LogLevel.debug, tag, message);
  static void info(String tag, String message) =>
      _log(LogLevel.info, tag, message);
  static void warn(String tag, String message, [Object? error]) =>
      _log(LogLevel.warn, tag, _withError(message, error));
  static void error(
    String tag,
    String message, [
    Object? error,
    StackTrace? stackTrace,
  ]) =>
      _log(LogLevel.error, tag, _withError(message, error, stackTrace));

  static String _withError(String message, Object? error,
      [StackTrace? stackTrace]) {
    if (error == null) return message;
    final trace = stackTrace == null ? '' : '\n$stackTrace';
    return '$message: ${error.runtimeType}: $error$trace';
  }

  static void _log(LogLevel level, String tag, String message) {
    if (level.index < minLevel.index) return;
    final record = LogRecord(
      DateTime.now(),
      level,
      tag,
      scrubSecrets(message),
    );
    _buffer.add(record);
    if (_buffer.length > _capacity) {
      _buffer.removeRange(0, _buffer.length - _capacity);
    }
    sink?.call(record);
    // Profile builds log too, so a phone can be inspected with
    // `adb logcat -s flutter`; release builds stay silent (Diagnostics
    // screen shows the ring buffer instead).
    if (!kReleaseMode) {
      debugPrint(record.toString());
    }
  }
}
