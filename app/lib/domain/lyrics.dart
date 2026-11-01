import 'package:meta/meta.dart';

/// One line of lyrics, optionally time-synced.
@immutable
class LyricLine {
  const LyricLine({required this.startMs, required this.text});

  /// Start time in milliseconds; `null` for unsynced lyrics.
  final int? startMs;
  final String text;

  bool get isBlank => text.trim().isEmpty;
}

@immutable
class TrackLyrics {
  const TrackLyrics({required this.lines, required this.synced, this.source});

  final List<LyricLine> lines;
  final bool synced;

  /// `server`, `lrclib`, `cache`...
  final String? source;

  bool get isEmpty => lines.every((l) => l.isBlank);

  /// Index of the line being sung at [positionMs] (the last line whose start
  /// is <= position), or -1 before the first line / when unsynced.
  int activeIndex(int positionMs, {int offsetMs = 0}) {
    if (!synced || lines.isEmpty) return -1;
    final t = positionMs + offsetMs;
    var lo = 0;
    var hi = lines.length - 1;
    var found = -1;
    while (lo <= hi) {
      final mid = (lo + hi) >> 1;
      final start = lines[mid].startMs ?? 0;
      if (start <= t) {
        found = mid;
        lo = mid + 1;
      } else {
        hi = mid - 1;
      }
    }
    return found;
  }
}

/// A line that only names a detail of the song, as the lines of a tag sheet do.
final _detailsLine = RegExp(
    r'^(artist|album|title|track|song|composer|lyricist|writer|length|year|genre)\s*:\s*\S?.*$',
    caseSensitive: false);

/// Parses LRC text (`[mm:ss.xx] words`, multiple stamps per line, metadata
/// tags ignored). Falls back to unsynced plain lines when no stamp is found.
TrackLyrics parseLrc(String content, {String? source}) {
  final stamp = RegExp(r'\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]');
  final lines = <LyricLine>[];

  for (final raw in content.split(RegExp(r'\r?\n'))) {
    final matches = stamp.allMatches(raw).toList();
    if (matches.isEmpty) continue;
    final text = raw.substring(matches.last.end).trim();
    for (final m in matches) {
      final minutes = int.parse(m.group(1)!);
      final seconds = int.parse(m.group(2)!);
      final fraction = m.group(3);
      var ms = 0;
      if (fraction != null) {
        // "5" = 500 ms, "50" = 500 ms, "500" = 500 ms
        ms = int.parse(fraction.padRight(3, '0').substring(0, 3));
      }
      lines.add(LyricLine(
        startMs: (minutes * 60 + seconds) * 1000 + ms,
        text: text,
      ));
    }
  }

  if (lines.isNotEmpty) {
    lines.sort((a, b) => a.startMs!.compareTo(b.startMs!));
    return TrackLyrics(lines: lines, synced: true, source: source);
  }

  // Unsynced: keep non-empty lines, drop LRC header tags like [ar:Artist].
  final plain = <LyricLine>[];
  for (final raw in content.split(RegExp(r'\r?\n'))) {
    final t = raw.trim();
    if (t.isEmpty) {
      if (plain.isNotEmpty && !plain.last.isBlank) {
        plain.add(const LyricLine(startMs: null, text: ''));
      }
      continue;
    }
    if (RegExp(r'^\[[a-zA-Z]+:.*\]$').hasMatch(t)) continue;
    plain.add(LyricLine(startMs: null, text: t));
  }
  while (plain.isNotEmpty && plain.last.isBlank) {
    plain.removeLast();
  }
  // Some catalogue entries hold only the song's own details ("Artist: ... / Album: ... / Title: ...") where the words should be (found on
  // "Any Colour You Like", an instrumental): that is no lyrics, and the player says so instead of showing it as a poem.
  final words = [
    for (final l in plain)
      if (!l.isBlank) l.text
  ];
  if (words.isNotEmpty && words.every(_detailsLine.hasMatch)) {
    return TrackLyrics(lines: const [], synced: false, source: source);
  }
  return TrackLyrics(lines: plain, synced: false, source: source);
}
