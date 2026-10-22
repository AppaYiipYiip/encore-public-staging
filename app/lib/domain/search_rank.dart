/// How well a song, an artist or an album answers what was typed, and which one is the "Top result" (docs/19, P1-07).
///
/// Search used to show the library's artists and albums first, the library's songs next and the catalogue's songs last under a
/// technical header, so a typed "radiohead weird fishes" came 6th (E5). Now one list is ranked by how well each answers the
/// words typed, the best of all kinds is the Top result, and owned or not owned is only a tie-break.
///
/// Pure Dart: no widgets, no database (it also runs in tests with plain strings).
library;

import 'text_match.dart';

/// Apostrophes and dots join letters instead of separating words, on both sides: "God's Plan" is "gods plan", "N.Y. State of
/// Mind" is "ny state of mind", whichever way a person types them.
final RegExp _joiners = RegExp(r"[.'’‘`]");

/// A featured artist is not part of the song's name: "Instant Crush (feat. Julian Casablancas)" is "Instant Crush".
final RegExp _featured = RegExp(
    r'\s*[\(\[]\s*(?:feat\.?|ft\.?|featuring|with)\s[^\)\]]*[\)\]]',
    caseSensitive: false);

String _plain(String? text) =>
    normalizeForMatch((text ?? '').replaceAll(_joiners, ''));

String _plainTitle(String? text) => normalizeForMatch(
    (text ?? '').replaceAll(_featured, '').replaceAll(_joiners, ''));

/// Whether every word of [query] begins one of [words].
bool _covers(List<String> query, List<String> words) =>
    query.isNotEmpty && query.every((q) => words.any((w) => w.startsWith(q)));

/// 0 to 1: how well "[artist] [title]" answers [query]. 1 is exactly artist and title (in either order), 0.95 exactly the
/// title, then every typed word found (shorter songs first), and below 0.4 only some of the words.
double songMatch(String query, {String? artist, required String title}) {
  final q = _plain(query);
  if (q.isEmpty) return 0;
  final t = _plainTitle(title);
  final a = _plain(artist);
  if (q == '$a $t'.trim() || q == '$t $a'.trim()) return 1;
  if (q == t) return 0.95;

  final typed = q.split(' ');
  final titleWords = t.split(' ').where((w) => w.isNotEmpty).toList();
  final artistWords = a.split(' ').where((w) => w.isNotEmpty).toList();
  final all = [...titleWords, ...artistWords];
  final found = typed.where((w) => all.any((x) => x.startsWith(w))).length;
  if (found < typed.length) return 0.4 * found / typed.length;

  // "artist title" (or "title artist"): the first typed words are the artist's, the rest the song's. That is a clean answer, and
  // it ranks above a cover or a tribute that merely has all the words in its title ("Fade Into You (Cover Mazzy Star)").
  if (_splitsIntoArtistAndTitle(typed, artistWords, titleWords)) {
    return (0.8 + 0.15 * typed.length / all.length.clamp(1, 1000))
        .clamp(0.0, 0.99);
  }

  var score = 0.5;
  if (t.startsWith(q)) score += 0.25;
  if (_covers(typed, titleWords)) score += 0.15;
  if (_covers(typed, artistWords)) score += 0.05;
  // The tighter the match, the higher: "Instant Crush" before "Instant Crush (Live at Wembley)".
  score += 0.09 * (typed.length / all.length.clamp(1, 1000));
  return score.clamp(0.0, 0.99);
}

/// Whether [typed] is some of the artist's words then some of the song's, or the other way round.
bool _splitsIntoArtistAndTitle(
    List<String> typed, List<String> artistWords, List<String> titleWords) {
  if (artistWords.isEmpty || titleWords.isEmpty) return false;
  for (var k = 1; k < typed.length; k++) {
    final first = typed.sublist(0, k);
    final second = typed.sublist(k);
    if (_covers(first, artistWords) && _covers(second, titleWords)) return true;
    if (_covers(first, titleWords) && _covers(second, artistWords)) return true;
  }
  return false;
}

/// 0 to 1: how well the artist [name] answers [query]. A name spelled almost like what was typed ("bilie eilsh") still scores 0.6:
/// the catalogue corrects such typos and the person meant that artist.
double artistMatch(String query, String name) {
  final q = _plain(query);
  final n = _plain(name);
  if (q.isEmpty || n.isEmpty) return 0;
  if (q == n) return 0.95;
  if (n.startsWith(q)) return 0.7;
  if (_covers(q.split(' '), n.split(' '))) return 0.55;
  return _similarity(q, n) >= 0.75 ? 0.6 : 0;
}

/// 0 to 1: how alike two strings are (1 minus the edit distance over the longer length).
double _similarity(String a, String b) {
  if (a == b) return 1;
  final longer = a.length > b.length ? a.length : b.length;
  if (longer == 0) return 1;
  var previous = List<int>.generate(b.length + 1, (j) => j);
  for (var i = 1; i <= a.length; i++) {
    final current = List<int>.filled(b.length + 1, 0)..[0] = i;
    for (var j = 1; j <= b.length; j++) {
      final cost = a.codeUnitAt(i - 1) == b.codeUnitAt(j - 1) ? 0 : 1;
      final best = [previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost]
          .reduce((x, y) => x < y ? x : y);
      current[j] = best;
    }
    previous = current;
  }
  return 1 - previous[b.length] / longer;
}

/// 0 to 1: how well the album [title] by [artist] answers [query].
double albumMatch(String query, {required String title, String? artist}) {
  final q = _plain(query);
  final t = _plainTitle(title);
  final a = _plain(artist);
  if (q.isEmpty || t.isEmpty) return 0;
  if (q == '$a $t'.trim() || q == '$t $a'.trim()) return 0.97;
  if (q == t) return 0.9;
  if (t.startsWith(q)) return 0.6;
  final typed = q.split(' ');
  return _covers(typed, [...t.split(' '), ...a.split(' ')]) ? 0.5 : 0;
}

/// What kind of thing a result is.
enum HitKind { song, artist, album }

/// One ranked result of any kind: [value] is the library's row or the catalogue's item.
class Ranked<T> {
  const Ranked(this.value, this.score, {required this.owned});

  final T value;

  /// 0 to 1, see [songMatch], [artistMatch], [albumMatch].
  final double score;

  /// The library has it (a tie is won by the song that is already there).
  final bool owned;
}

/// Orders [hits] best first: by score, then owned before not owned, then the order they arrived in (the catalogue's own rank).
List<Ranked<T>> rankHits<T>(Iterable<Ranked<T>> hits) {
  final indexed = [for (final (i, h) in hits.indexed) (i, h)];
  indexed.sort((x, y) {
    final byScore = y.$2.score.compareTo(x.$2.score);
    if (byScore != 0) return byScore;
    if (x.$2.owned != y.$2.owned) return x.$2.owned ? -1 : 1;
    return x.$1.compareTo(y.$1);
  });
  return [for (final (_, h) in indexed) h];
}

/// The best of the best song, artist and album: the "Top result". Below [minimum] nothing is on top (a list of loose matches has
/// no obvious answer). An exact tie goes to the artist, then the album, then the song, like Spotify, unless the artist is barely
/// known ([artistWellKnown] false): typing "Hotel California" means the song, not an artist of 7,000 fans who has that name.
({HitKind kind, double score})? pickTop({
  double? song,
  double? artist,
  double? album,
  bool artistWellKnown = true,
  double minimum = 0.5,
}) {
  final candidates = <({HitKind kind, double score})>[
    if (artist != null)
      (kind: HitKind.artist, score: artistWellKnown ? artist : artist - 0.1),
    if (album != null) (kind: HitKind.album, score: album),
    if (song != null) (kind: HitKind.song, score: song),
  ];
  ({HitKind kind, double score})? best;
  for (final c in candidates) {
    if (c.score >= minimum && (best == null || c.score > best.score)) best = c;
  }
  return best;
}
