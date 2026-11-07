import 'dart:convert';

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

/// The bytes a Windows-1252 text holds for the characters that sit between U+0080 and U+009F in that code page (the others are the same
/// as Latin-1).
const Map<int, int> _cp1252Specials = {
  0x20AC: 0x80, 0x201A: 0x82, 0x0192: 0x83, 0x201E: 0x84, 0x2026: 0x85,
  0x2020: 0x86, 0x2021: 0x87, 0x02C6: 0x88, 0x2030: 0x89, //
  0x0160: 0x8A, 0x2039: 0x8B, 0x0152: 0x8C, 0x017D: 0x8E, 0x2018: 0x91,
  0x2019: 0x92, 0x201C: 0x93, 0x201D: 0x94, 0x2022: 0x95,
  0x2013: 0x96, 0x2014: 0x97, 0x02DC: 0x98, 0x2122: 0x99, 0x0161: 0x9A,
  0x203A: 0x9B, 0x0153: 0x9C, 0x017E: 0x9E, 0x0178: 0x9F,
};

/// The first letters of the pairs a double-encoded text is made of: `Â´` is `´`, `Ã©` is `é`, `â€™` is `’`, `Ð¿` is `п`.
final _mojibakeMark = RegExp('[ÂÃÅÐÑâ]');

/// Gives back the text a line was meant to be when it was saved twice in the wrong character set (UTF-8 bytes read as Latin-1 or
/// Windows-1252): "Here weÂ´ll be gone" becomes "Here we´ll be gone" (audit B-102: LRCLIB's record 1918075 holds it that way, and any
/// user-contributed text can).
///
/// It only ever answers with a text that is shorter and is valid UTF-8 after the bytes are put back; anything else (a real "café", a line in
/// Arabic or Chinese, a name that starts with "Ñ") comes back unchanged.
String repairMojibake(String text) {
  if (!_mojibakeMark.hasMatch(text)) return text;
  final bytes = <int>[];
  for (final rune in text.runes) {
    if (rune < 0x100) {
      bytes.add(rune);
    } else {
      final special = _cp1252Specials[rune];
      if (special == null) {
        // A real character of another script: not a double-encoded text.
        return text;
      }
      bytes.add(special);
    }
  }
  try {
    final repaired = utf8.decode(bytes);
    return repaired.runes.length < text.runes.length ? repaired : text;
  } on FormatException {
    return text;
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
    final text = repairMojibake(raw.substring(matches.last.end).trim());
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
    final t = repairMojibake(raw.trim());
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
