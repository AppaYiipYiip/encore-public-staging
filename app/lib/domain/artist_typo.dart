/// Typo tolerance for artist names (N-23a, owner 13 Nov 2026: typing "landmarks" must find the band "Landmvrks").
///
/// **The rule, in one sentence: when what was typed and an artist's name both have 5 or more letters, one letter wrong, missing, extra
/// or swapped with its neighbour still finds the artist, and two do from 9 letters on; a name of 1 to 4 letters is never guessed.**
///
/// Why it is a scan and not part of the library's text search: the full-text index only matches the start of a word, and a typo in the
/// first letters ("lamdmarks") has no start to match. The scan compares the typed words with the library's artist names only (a few
/// thousand at most, never songs or albums), so it costs a few milliseconds ([ArtistTypoIndex]). The score such a name gets is
/// `typoArtistScore` in `search_rank.dart`, below every exact answer; the scan is used only when the library has no artist whose name
/// begins with the typed words (the wiring, `searchResultsProvider`).
///
/// Pure Dart. The functions work on **folded** text (the same folding the search scores use, `searchKey` in `search_rank.dart`), which
/// this file never does itself: folding is what costs (about 20 microseconds a name), the comparison here is what must stay cheap.
library;

import 'dart:math' as math;

/// The fewest letters a name, and what was typed, must have to be guessed: a 4 letter name is one edit from a dozen others.
const int typoMinLetters = 5;

/// From this many letters on, two edits are allowed instead of one.
const int typoTwoEditsFromLetters = 9;

/// How many edits a name of [letters] letters may be off: none below [typoMinLetters], one up to 8, two from
/// [typoTwoEditsFromLetters].
int typoAllowance(int letters) => letters >= typoTwoEditsFromLetters
    ? 2
    : letters >= typoMinLetters
        ? 1
        : 0;

/// The letters and digits of a folded text: its spaces are not counted.
int _letters(String key) {
  var n = 0;
  for (var i = 0; i < key.length; i++) {
    if (key.codeUnitAt(i) != 0x20) n++;
  }
  return n;
}

/// How many edits (a letter wrong, missing, extra, or two neighbours swapped: one each) [name] is from [typed], or `null` when that is
/// more than the rule allows. Both are folded. The allowance follows the shorter of the two in letters, so the answer is the same
/// whichever is the name; 0 when they are the same.
int? typoEdits(String typed, String name) {
  final allowed = typoAllowance(math.min(_letters(typed), _letters(name)));
  return allowed == 0 ? null : _editsWithin(typed, name, allowed);
}

/// The optimal string alignment distance of [a] and [b] (Levenshtein, plus one for two neighbours swapped) when it is at most [most],
/// else `null`. Gives up as soon as no alignment can end within [most], so a name that is not close costs a few rows, not the whole
/// table. Compares UTF-16 code units: a letter outside the basic plane (rare in names) counts as two, which only makes the rule
/// stricter for it.
int? _editsWithin(String a, String b, int most) {
  final n = a.length;
  final m = b.length;
  if ((n - m).abs() > most) return null;
  var older = List<int>.filled(m + 1, 0);
  var previous = List<int>.generate(m + 1, (j) => j);
  var current = List<int>.filled(m + 1, 0);
  var previousBest = 0;
  for (var i = 1; i <= n; i++) {
    current[0] = i;
    var best = i;
    final ca = a.codeUnitAt(i - 1);
    for (var j = 1; j <= m; j++) {
      final cb = b.codeUnitAt(j - 1);
      var d = previous[j - 1] + (ca == cb ? 0 : 1);
      if (previous[j] + 1 < d) d = previous[j] + 1;
      if (current[j - 1] + 1 < d) d = current[j - 1] + 1;
      if (i > 1 &&
          j > 1 &&
          ca == b.codeUnitAt(j - 2) &&
          a.codeUnitAt(i - 2) == cb &&
          older[j - 2] + 1 < d) {
        d = older[j - 2] + 1;
      }
      current[j] = d;
      if (d < best) best = d;
    }
    // A swap reaches row i + 1 from row i - 1, so no alignment can end within [most] only when two rows in a row are above it.
    if (best > most && previousBest > most) return null;
    previousBest = best;
    final spare = older;
    older = previous;
    previous = current;
    current = spare;
  }
  final d = previous[m];
  return d <= most ? d : null;
}

/// The library's artists, folded once so that a search only scans them: folding 5,000 names takes about 100 ms (debug build), which is
/// too much to repeat on every key, while comparing them takes a few milliseconds.
///
/// Built from a list; build a new one when the list changes. The names are folded on the first [find], not when it is built. A list
/// that arrives again with the same names (the database tells the screen again whenever any song is written, artists or not) is
/// given the index it replaces as [reusing], and then takes over its folded names instead of folding them again.
class ArtistTypoIndex<T> {
  ArtistTypoIndex(
    this._items, {
    required String Function(T) nameOf,
    required String Function(String) fold,
    ArtistTypoIndex<T>? reusing,
  })  : _fold = fold,
        _names = [for (final i in _items) nameOf(i)] {
    if (reusing != null &&
        identical(reusing._fold, fold) &&
        _sameNames(reusing._names, _names)) {
      _folded = reusing._folded;
    }
  }

  final List<T> _items;

  /// The one folding of names and of the typed words: the same function on both sides, so they cannot disagree.
  final String Function(String) _fold;
  final List<String> _names;

  /// The folded names and their letter counts, once folded.
  ({List<String> keys, List<int> letters})? _folded;

  static bool _sameNames(List<String> a, List<String> b) {
    if (a.length != b.length) return false;
    for (var i = 0; i < a.length; i++) {
      if (a[i] != b[i]) return false;
    }
    return true;
  }

  ({List<String> keys, List<int> letters}) _foldNames() => _folded ??= () {
        final keys = [for (final n in _names) _fold(n)];
        return (keys: keys, letters: [for (final k in keys) _letters(k)]);
      }();

  /// The artists whose name is within the rule of [query] ([typoEdits]), the closest first and, among as close ones, in the order of
  /// the list; at most [limit]. Nothing for fewer than [typoMinLetters] letters typed.
  List<T> find(String query, {int limit = 8}) {
    final typed = _fold(query);
    final typedLetters = _letters(typed);
    if (typedLetters < typoMinLetters) return const [];
    final (:keys, :letters) = _foldNames();
    final found = <(int, int)>[];
    for (var i = 0; i < keys.length; i++) {
      final allowed = typoAllowance(math.min(typedLetters, letters[i]));
      if (allowed == 0) continue;
      final edits = _editsWithin(typed, keys[i], allowed);
      if (edits != null) found.add((edits, i));
    }
    found.sort((x, y) => x.$1 != y.$1 ? x.$1 - y.$1 : x.$2 - y.$2);
    return [for (final (_, i) in found.take(limit)) _items[i]];
  }
}
