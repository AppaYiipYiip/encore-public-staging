/// How well a song, an artist or an album answers what was typed, and which one is the "Top result" (docs/19, P1-07).
///
/// Search used to show the library's artists and albums first, the library's songs next and the catalogue's songs last under a
/// technical header, so a typed "radiohead weird fishes" came 6th (E5). Now one list is ranked by how well each answers the
/// words typed, the best of all kinds is the Top result, and owned or not owned is only a tie-break.
///
/// Pure Dart: no widgets, no database (it also runs in tests with plain strings).
library;

import 'artist_typo.dart';
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

/// What the scores below compare: [text] folded (case, accents, apostrophes, dots, "The", every alphabet kept). The typo scan of
/// artist names ([ArtistTypoIndex]) is given this one function for the names and for what was typed, so it cannot fold differently
/// from the scores.
String searchKey(String? text) => _plain(text);

String _plainTitle(String? text) => normalizeForMatch(
    (text ?? '').replaceAll(_featured, '').replaceAll(_joiners, ''));

/// Whether every word of [query] begins one of [words].
bool _covers(List<String> query, List<String> words) =>
    query.isNotEmpty && query.every((q) => words.any((w) => w.startsWith(q)));

/// The scale. The scores of songs, artists and albums are compared with each other to pick the Top result ([pickTop]), so what a kind of
/// answer is worth is fixed here and nowhere else:
///
/// * 1: the artist and the song typed in full ([songMatch]); 0.97 the same for an album.
/// * 0.95: the title or the name typed exactly; 0.9 for an album.
/// * 0.8 to 0.94: a song that is "artist title" in the words typed (the first ones the artist's, the rest the song's).
/// * [partialSongCeiling] (0.8) and below: a song that merely has the words, or starts with them, down to 0.5.
/// * below 0.4: only some of the words.
///
/// For an artist ([artistMatch]): 0.95 the name typed exactly, 0.7 the start of the name, [typoArtistScore] (0.6) a name that is one or two
/// letters off (the one rule of `artist_typo.dart`), 0.55 every typed word begins some word of the name, not the first ("eilish" for "Billie Eilish"). So a typo is below
/// every exact answer and every start of a name, above a loose one, and inside the band of the partial songs (0.5 to [partialSongCeiling]): a song whose title starts with the typed word
/// (0.72 and up) is above it, a song that only contains the word, or has it in its artist, is level with it or below (0.5 to about 0.6).
///
/// The rule behind it (P1-07, owner 13 Nov 2026: searching "jinjer", spelled right, put a song before the band): **an answer that is
/// only partial is never worth as much as an exact one**, whatever its parts add up to, so an artist whose name is exactly what was
/// typed comes before every song and album that only starts with or contains the words. Only an exact title or an exact album can
/// take that place, and only when the artist is barely known ([barelyKnownArtistPenalty]).
const double partialSongCeiling = 0.8;

/// What an artist whose name is one or two letters off what was typed is worth ([typoEdits], N-23a: "landmarks" finds "Landmvrks").
/// Under an exact name (0.95) and the start of a name (0.7), so a typo only comes first when nothing answers better.
const double typoArtistScore = 0.6;

/// What an artist that is barely known (not in the library and below the fan count of `wellKnownFans`) loses when the Top result is
/// picked: enough to go below an exact title (0.95) and an exact album (0.9) that are named like it ("Hotel California" is the song,
/// not the artist with 7,812 fans), not enough to go below a song that is only partial ([partialSongCeiling], at most 0.8).
const double barelyKnownArtistPenalty = 0.1;

/// 0 to 1: how well "[artist] [title]" answers [query]. 1 is exactly artist and title (in either order), 0.95 exactly the
/// title, then "artist title" (0.8 to 0.94), then every typed word found (shorter songs first, never above [partialSongCeiling]), and
/// below 0.4 only some of the words. The whole scale is explained at [partialSongCeiling].
double songMatch(String query, {String? artist, required String title}) {
  final q = _plain(query);
  if (q.isEmpty) return 0;
  final t = _plainTitle(title);
  final a = _plain(artist);
  // "artist title" is only said of a song that has an artist: with none, the title alone is all there is to match (0.95).
  if (a.isNotEmpty && (q == '$a $t'.trim() || q == '$t $a'.trim())) return 1;
  if (q == t) return 0.95;

  final typed = q.split(' ');
  final titleWords = t.split(' ').where((w) => w.isNotEmpty).toList();
  final artistWords = a.split(' ').where((w) => w.isNotEmpty).toList();
  final all = [...titleWords, ...artistWords];
  final found = typed.where((w) => all.any((x) => x.startsWith(w))).length;
  if (found < typed.length) return 0.4 * found / typed.length;

  // How much of the song's words were typed (1 at most: a word typed twice does not make a song better).
  final tight = (typed.length / all.length.clamp(1, 1000)).clamp(0.0, 1.0);

  // "artist title" (or "title artist"): the first typed words are the artist's, the rest the song's. That is a clean answer, and
  // it ranks above a cover or a tribute that merely has all the words in its title ("Fade Into You (Cover Mazzy Star)").
  if (_splitsIntoArtistAndTitle(typed, artistWords, titleWords)) {
    return 0.8 + 0.14 * tight;
  }

  // The words are all there, but the song is not what was typed: 0.5 to just under [partialSongCeiling] (0.79). That is below an
  // exact title, an exact album and an exact artist, whatever the parts add up to: a song of Jinjer named "Jinjer - Pisces" has the
  // band's name twice and is still not the band.
  var score = 0.5;
  if (t.startsWith(q)) score += 0.13;
  if (_covers(typed, titleWords)) score += 0.09;
  if (_covers(typed, artistWords)) score += 0.03;
  // The tighter the match, the higher: "Instant Crush" before "Instant Crush (Live at Wembley)".
  score += 0.04 * tight;
  assert(score < partialSongCeiling,
      'a partial answer must stay below an exact one');
  return score;
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

/// 0 to 1: how well the artist [name] answers [query]: 0.95 exactly, 0.7 the start of the name, [typoArtistScore] a name one letter off
/// (two from 9 letters on, never for 1 to 4 letters: [typoEdits]), 0.55 every typed word begins some word of the name. The library's search
/// cannot find a typo, so `searchResultsProvider` adds such artists to its results ([ArtistTypoIndex]); the catalogue's (Deezer's) own
/// matching finds them for the catalogue. Both are scored here, by the same rule.
double artistMatch(String query, String name) {
  final q = _plain(query);
  final n = _plain(name);
  if (q.isEmpty || n.isEmpty) return 0;
  if (q == n) return 0.95;
  if (n.startsWith(q)) return 0.7;
  if (_covers(q.split(' '), n.split(' '))) return 0.55;
  return typoEdits(q, n) != null ? typoArtistScore : 0;
}

/// 0 to 1: how well the album [title] by [artist] answers [query].
double albumMatch(String query, {required String title, String? artist}) {
  final q = _plain(query);
  final t = _plainTitle(title);
  final a = _plain(artist);
  if (q.isEmpty || t.isEmpty) return 0;
  // As for a song: with no artist the title alone is all there is to match.
  if (a.isNotEmpty && (q == '$a $t'.trim() || q == '$t $a'.trim())) return 0.97;
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
///
/// So **popularity only settles a tie between exact answers**: the artist who was typed exactly is on top of every song or album that
/// is only partial, known or not ([barelyKnownArtistPenalty] is smaller than the gap to [partialSongCeiling]); a well known artist
/// is also on top of a song or an album that is exactly the same words; a barely known one is not.
({HitKind kind, double score})? pickTop({
  double? song,
  double? artist,
  double? album,
  bool artistWellKnown = true,
  double minimum = 0.5,
}) {
  final candidates = <({HitKind kind, double score})>[
    if (artist != null)
      (
        kind: HitKind.artist,
        score: artistWellKnown ? artist : artist - barelyKnownArtistPenalty
      ),
    if (album != null) (kind: HitKind.album, score: album),
    if (song != null) (kind: HitKind.song, score: song),
  ];
  ({HitKind kind, double score})? best;
  for (final c in candidates) {
    if (c.score >= minimum && (best == null || c.score > best.score)) best = c;
  }
  return best;
}
