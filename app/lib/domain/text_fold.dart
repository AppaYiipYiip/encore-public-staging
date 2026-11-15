/// The phone's twin of the server's text fold (P2-25, audit B-37): one fold for
/// every alphabet, so that "Fairuz" in Arabic, a Russian band, a Korean title
/// and "Łukasz" are never folded away to nothing, and the two sides agree.
///
/// **It is a transcription, not a design.** The rules are written once, in the
/// server's `textnorm.py` (NFKC, case fold, the decorating marks removed by an
/// allow-list, `ø ł ı` and the Arabic and Persian variants folded, every digit
/// ASCII, invisible characters gone); `tools/gen_text_fold_table.py` writes the
/// tables this file reads (`text_fold_table.g.dart`) from Python's own Unicode
/// data. Dart has no NFKC, no full case fold and no Unicode properties of a
/// pinned version (`toLowerCase` and `\p{L}` carry the SDK's own Unicode
/// version, a second pin by the back door), so nothing here asks the platform:
/// everything comes from the table. Both suites read ONE fixture
/// (`test/fixtures/text/fold-cases.json`): hand-written rows plus digests of
/// the fold of every code point and of 20,000 seeded strings.
///
/// **Slice 1 of P2-25 ships it unwired**: nothing calls it yet. The phone's
/// `normalizeForMatch` and the offline index's word rule move onto it in the
/// follow-up (docs/tasks/P2-songs-as-references.md, P2-25 part 11), which is a
/// behaviour change on its own.
library;

import 'package:meta/meta.dart';

import 'text_fold_table.g.dart';

/// The character stage of the fold: NFKC, case fold, the decorating marks
/// removed, `ø ł ı ß` and the Arabic and Persian variants folded, every digit
/// ASCII, invisible characters gone. **It keeps punctuation and spaces**;
/// [textWords] cuts the result into words. Idempotent. ASCII is just lower-cased.
String textFold(String text) {
  if (_isAscii(text)) return _asciiLower(text);
  final t = _tables;
  var s = text.runes.toList();
  // 6. Invisible characters first, so that a format character between a base
  // and its mark cannot stop them composing.
  s = _dropFormat(s, t);
  // 1. NFKC (not NFKD: it would split Hangul and the voiced kana), 2. case fold.
  s = _caseFold(_normalize(s, t, compat: true), t);
  // 3. The decorating marks (an allow-list), after the one letter that must be
  // mapped before its mark goes.
  s = _mapLetters(s, t.beforeMarks);
  s = _removeMarks(s, t);
  // 4. Letters with no decomposition, 5. digits of any script.
  s = _mapLetters(s, t.letterTable);
  return String.fromCharCodes(_digits(s, t));
}

/// The words of a folded text: runs of letters, digits and kept marks (`तुम` is
/// one word); everything else is a gap. A run made only of marks is not a word.
/// A Chinese or Japanese title is ONE word (no n-grams here).
List<String> textWords(String folded) {
  final out = <String>[];
  if (_isAscii(folded)) {
    final units = folded.codeUnits;
    var start = -1;
    for (var i = 0; i <= units.length; i++) {
      final word = i < units.length && _isAsciiWordUnit(units[i]);
      if (word && start < 0) start = i;
      if (!word && start >= 0) {
        out.add(folded.substring(start, i));
        start = -1;
      }
    }
    return out;
  }
  final t = _tables;
  var run = <int>[];
  var readable = false;
  for (final cp in folded.runes) {
    if (_inRanges(t.letters, cp) || _inRanges(t.numbers, cp)) {
      run.add(cp);
      readable = true;
    } else if (_inRanges(t.marks, cp)) {
      run.add(cp);
    } else {
      if (run.isNotEmpty && readable) out.add(String.fromCharCodes(run));
      run = <int>[];
      readable = false;
    }
  }
  if (run.isNotEmpty && readable) out.add(String.fromCharCodes(run));
  return out;
}

/// How [textWords] reads a code point: `l` a letter, `n` a number, `m` a mark,
/// an empty string anything else. For the corpus test of the shared fixture
/// (`class_pages`), which checks the generated class tables one page at a time.
@visibleForTesting
String textClassOf(int cp) {
  final t = _tables;
  if (_inRanges(t.letters, cp)) return 'l';
  if (_inRanges(t.numbers, cp)) return 'n';
  if (_inRanges(t.marks, cp)) return 'm';
  return '';
}

// ---------------------------------------------------------------------------
// ASCII

bool _isAscii(String s) {
  for (final unit in s.codeUnits) {
    if (unit > 0x7f) return false;
  }
  return true;
}

String _asciiLower(String s) {
  final units = s.codeUnits;
  for (var i = 0; i < units.length; i++) {
    if (units[i] >= 0x41 && units[i] <= 0x5a) {
      return String.fromCharCodes([
        for (final u in units) (u >= 0x41 && u <= 0x5a) ? u + 32 : u,
      ]);
    }
  }
  return s;
}

bool _isAsciiWordUnit(int u) =>
    (u >= 0x30 && u <= 0x39) ||
    (u >= 0x41 && u <= 0x5a) ||
    (u >= 0x61 && u <= 0x7a);

// ---------------------------------------------------------------------------
// The steps

const int _zwnj = 0x200c;

List<int> _dropFormat(List<int> s, _Tables t) {
  final out = <int>[];
  for (final cp in s) {
    if (cp == _zwnj) {
      out.add(0x20);
    } else if (!_inRanges(t.format, cp)) {
      out.add(cp);
    }
  }
  return out;
}

List<int> _caseFold(List<int> s, _Tables t) {
  final out = <int>[];
  for (final cp in s) {
    final mapped = t.caseFold[cp];
    if (mapped == null) {
      out.add(cp);
    } else {
      out.addAll(mapped);
    }
  }
  return out;
}

List<int> _mapLetters(List<int> s, Map<int, List<int>> table) {
  final out = <int>[];
  for (final cp in s) {
    final mapped = table[cp];
    if (mapped == null) {
      out.add(cp);
    } else {
      out.addAll(mapped);
    }
  }
  return out;
}

List<int> _digits(List<int> s, _Tables t) {
  final zeros = t.zeros;
  return [
    for (final cp in s) cp < 0x80 ? cp : _digitOrSelf(cp, zeros),
  ];
}

int _digitOrSelf(int cp, List<int> zeros) {
  // The largest zero that is not above cp; the digit is cp minus it, when that
  // is below ten (the generator checks every Nd code point sits in such a run).
  var lo = 0;
  var hi = zeros.length - 1;
  var found = -1;
  while (lo <= hi) {
    final mid = (lo + hi) >> 1;
    if (zeros[mid] <= cp) {
      found = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  if (found < 0) return cp;
  final digit = cp - zeros[found];
  return digit <= 9 ? 0x30 + digit : cp;
}

/// NFD, remove the allow-listed marks, NFC; the protected letters are cut out
/// first and put back whole.
List<int> _removeMarks(List<int> s, _Tables t) {
  final out = <int>[];
  var segment = <int>[];
  void flush() {
    if (segment.isEmpty) return;
    final decomposed = _normalize(segment, t, compat: false, compose: false);
    final kept = [
      for (final cp in decomposed)
        if (!_inRanges(t.marksOut, cp)) cp,
    ];
    out.addAll(_compose(kept, t));
    segment = <int>[];
  }

  for (final cp in s) {
    if (t.protected.contains(cp)) {
      flush();
      out.add(cp);
    } else {
      segment.add(cp);
    }
  }
  flush();
  return out;
}

// ---------------------------------------------------------------------------
// Normalisation (UAX #15) from the tables

const int _sBase = 0xac00;
const int _lBase = 0x1100;
const int _vBase = 0x1161;
const int _tBase = 0x11a7;
const int _lCount = 19;
const int _vCount = 21;
const int _tCount = 28;
const int _nCount = _vCount * _tCount;
const int _sCount = _lCount * _nCount;

List<int> _normalize(
  List<int> s,
  _Tables t, {
  required bool compat,
  bool compose = true,
}) {
  final out = <int>[];
  for (final cp in s) {
    if (cp >= _sBase && cp < _sBase + _sCount) {
      final index = cp - _sBase;
      out.add(_lBase + index ~/ _nCount);
      out.add(_vBase + (index % _nCount) ~/ _tCount);
      final tail = index % _tCount;
      if (tail != 0) out.add(_tBase + tail);
      continue;
    }
    final mapped = (compat ? t.compat[cp] : null) ?? t.canon[cp];
    if (mapped == null) {
      out.add(cp);
    } else {
      out.addAll(mapped);
    }
  }
  _reorder(out, t);
  return compose ? _compose(out, t) : out;
}

/// Canonical ordering: inside every run of non-starters, a stable sort by
/// combining class.
void _reorder(List<int> s, _Tables t) {
  var i = 0;
  while (i < s.length) {
    if (_combiningClass(s[i], t) == 0) {
      i++;
      continue;
    }
    var j = i;
    while (j < s.length && _combiningClass(s[j], t) != 0) {
      j++;
    }
    for (var a = i + 1; a < j; a++) {
      final cp = s[a];
      final klass = _combiningClass(cp, t);
      var b = a - 1;
      while (b >= i && _combiningClass(s[b], t) > klass) {
        s[b + 1] = s[b];
        b--;
      }
      s[b + 1] = cp;
    }
    i = j;
  }
}

/// Canonical composition: a mark or a starter joins the last starter when
/// nothing of an equal or higher class stands between them and the pair is a
/// primary composite (or a Hangul pair).
List<int> _compose(List<int> s, _Tables t) {
  final out = <int>[];
  var starter = -1;
  for (final cp in s) {
    final klass = _combiningClass(cp, t);
    if (starter >= 0) {
      final blocked =
          out.length - 1 != starter && _combiningClass(out.last, t) >= klass;
      if (!blocked) {
        final composite = _pair(out[starter], cp, t);
        if (composite != null) {
          out[starter] = composite;
          continue;
        }
      }
    }
    out.add(cp);
    if (klass == 0) starter = out.length - 1;
  }
  return out;
}

int? _pair(int first, int second, _Tables t) {
  if (first >= _lBase &&
      first < _lBase + _lCount &&
      second >= _vBase &&
      second < _vBase + _vCount) {
    return _sBase + ((first - _lBase) * _vCount + (second - _vBase)) * _tCount;
  }
  if (first >= _sBase &&
      first < _sBase + _sCount &&
      (first - _sBase) % _tCount == 0 &&
      second > _tBase &&
      second < _tBase + _tCount) {
    return first + (second - _tBase);
  }
  return t.composition[first * _pairShift + second];
}

const int _pairShift = 0x200000;

int _combiningClass(int cp, _Tables t) {
  final lo = t.combiningLo;
  var a = 0;
  var b = lo.length - 1;
  while (a <= b) {
    final mid = (a + b) >> 1;
    if (cp < lo[mid]) {
      b = mid - 1;
    } else if (cp > t.combiningHi[mid]) {
      a = mid + 1;
    } else {
      return t.combiningClasses[mid];
    }
  }
  return 0;
}

// ---------------------------------------------------------------------------
// The tables, read from the generated strings on first use

bool _inRanges(List<int> ranges, int cp) {
  var lo = 0;
  var hi = ranges.length ~/ 2 - 1;
  while (lo <= hi) {
    final mid = (lo + hi) >> 1;
    if (cp < ranges[2 * mid]) {
      hi = mid - 1;
    } else if (cp > ranges[2 * mid + 1]) {
      lo = mid + 1;
    } else {
      return true;
    }
  }
  return false;
}

final _Tables _tables = _Tables();

class _Tables {
  _Tables()
      : canon = _parseMap(kTextFoldCanon),
        compat = _parseMap(kTextFoldCompat),
        caseFold = _parseMap(kTextFoldCase),
        beforeMarks = _parseMap(kTextFoldBeforeMarks),
        letterTable = _parseMap(kTextFoldLetterTable),
        composition = _parseComposition(kTextFoldComposition),
        letters = _parseRanges(kTextFoldLetters),
        numbers = _parseRanges(kTextFoldNumbers),
        marks = _parseRanges(kTextFoldMarks),
        format = _parseRanges(kTextFoldFormat),
        marksOut = _parseRanges(kTextFoldMarksOut),
        zeros = _parseList(kTextFoldDigitZeros),
        protected = _parseList(kTextFoldProtected).toSet() {
    final lo = <int>[];
    final hi = <int>[];
    final klass = <int>[];
    for (final entry in kTextFoldCombining.split(' ')) {
      final colon = entry.indexOf(':');
      final span = entry.substring(0, colon);
      final dash = span.indexOf('-');
      lo.add(int.parse(dash < 0 ? span : span.substring(0, dash), radix: 16));
      hi.add(int.parse(dash < 0 ? span : span.substring(dash + 1), radix: 16));
      klass.add(int.parse(entry.substring(colon + 1)));
    }
    combiningLo = lo;
    combiningHi = hi;
    combiningClasses = klass;
  }

  final Map<int, List<int>> canon;
  final Map<int, List<int>> compat;
  final Map<int, List<int>> caseFold;
  final Map<int, List<int>> beforeMarks;
  final Map<int, List<int>> letterTable;
  final Map<int, int> composition;
  final List<int> letters;
  final List<int> numbers;
  final List<int> marks;
  final List<int> format;
  final List<int> marksOut;
  final List<int> zeros;
  final Set<int> protected;
  late final List<int> combiningLo;
  late final List<int> combiningHi;
  late final List<int> combiningClasses;
}

List<int> _parseList(String s) => [
      for (final item in s.split(' '))
        if (item.isNotEmpty) int.parse(item, radix: 16),
    ];

/// `lo-hi` or `lo`, flattened to [lo0, hi0, lo1, hi1, ...].
List<int> _parseRanges(String s) {
  final out = <int>[];
  for (final item in s.split(' ')) {
    if (item.isEmpty) continue;
    final dash = item.indexOf('-');
    final lo = int.parse(dash < 0 ? item : item.substring(0, dash), radix: 16);
    final hi = int.parse(dash < 0 ? item : item.substring(dash + 1), radix: 16);
    out
      ..add(lo)
      ..add(hi);
  }
  return out;
}

/// `cp:cp,cp` (an empty right side removes the character), or `lo-hi:target`
/// for a run that maps to consecutive code points.
Map<int, List<int>> _parseMap(String s) {
  final out = <int, List<int>>{};
  for (final entry in s.split(' ')) {
    if (entry.isEmpty) continue;
    final colon = entry.indexOf(':');
    final left = entry.substring(0, colon);
    final right = entry.substring(colon + 1);
    final dash = left.indexOf('-');
    if (dash >= 0) {
      final lo = int.parse(left.substring(0, dash), radix: 16);
      final hi = int.parse(left.substring(dash + 1), radix: 16);
      final target = int.parse(right, radix: 16);
      for (var cp = lo; cp <= hi; cp++) {
        out[cp] = [target + cp - lo];
      }
    } else {
      out[int.parse(left, radix: 16)] = right.isEmpty
          ? const <int>[]
          : [for (final part in right.split(',')) int.parse(part, radix: 16)];
    }
  }
  return out;
}

/// `first,second:composite`.
Map<int, int> _parseComposition(String s) {
  final out = <int, int>{};
  for (final entry in s.split(' ')) {
    if (entry.isEmpty) continue;
    final colon = entry.indexOf(':');
    final pair = entry.substring(0, colon).split(',');
    out[int.parse(pair[0], radix: 16) * _pairShift +
            int.parse(pair[1], radix: 16)] =
        int.parse(entry.substring(colon + 1), radix: 16);
  }
  return out;
}
