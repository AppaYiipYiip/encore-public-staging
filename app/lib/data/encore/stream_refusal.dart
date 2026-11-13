import 'package:flutter/foundation.dart';

/// Why the server will not play a song, in its own words: the answer to the first byte of a stream that failed (`song_unavailable`: no matching
/// upload was found, the upload was removed, it needs an age check; `source_busy`: YouTube is resting; and so on).
@immutable
class StreamRefusal {
  const StreamRefusal({
    required this.code,
    required this.message,
    required this.retryable,
    this.reason,
  });

  /// The server's error code (`song_unavailable`, `source_busy`, `upstream_timeout`, ...).
  final String code;

  /// The sentence the server wrote for a person.
  final String message;

  /// Whether asking again may help (the server says so).
  final bool retryable;

  /// For `song_unavailable`: `not_found`, `removed` or `age_restricted`.
  final String? reason;

  /// The song itself cannot be had, however often it is asked for: trying again only costs the server another look-up at YouTube.
  bool get permanent => code == 'song_unavailable' && !retryable;
}
