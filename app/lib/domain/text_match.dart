/// Loose, deterministic comparison of music metadata strings.
///
/// Used to decide "is this catalogue item already in my library?" and "did my
/// request arrive?". It is intentionally forgiving about case, accents,
/// punctuation, "The " prefixes and edition/remaster suffixes, because the
/// same release is spelled differently by Deezer, MusicBrainz and file tags.
library;

import 'text_fold.dart';

/// The phone's own looser reading of Latin names, on top of the shared fold (`textFold`): letters the fold leaves as they are because the SERVER's key must not merge them, which a search on the
/// phone should ("Aeon" finds "Æon", "Thor" finds "Þór"). It is NOT part of identity: nothing here is written to the server.
const Map<String, String> _looseLatin = {
  'æ': 'ae',
  'œ': 'oe',
  'þ': 'th',
  'ð': 'd',
  'đ': 'd',
};

final RegExp _looseLatinLetters = RegExp('[æœþðđ]');

final RegExp _editionSuffix = RegExp(
  r'\s*[\(\[]?\s*(?:\d{4}\s+)?(?:remaster(?:ed)?(?: (?:version|edition))?|'
  r'deluxe(?: edition)?|'
  r'expanded(?: edition)?|bonus tracks?|anniversary(?: edition)?|'
  r'special edition|standard edition|digital edition|'
  r'album version|single version|explicit(?: version)?|clean version)'
  r'(?:\s+\d{4})?\s*[\)\]]?\s*$',
  caseSensitive: false,
);

/// Canonical comparison key for [input].
///
/// **One fold for every alphabet** (N-46, P2-25): the letters are folded by [textFold], the Dart twin of the server's fold (NFKC, case fold, the decorating marks removed by an allow-list, every
/// digit ASCII, invisible characters gone), and the words are cut by [textWords] (a run of letters, digits and kept marks: a Hindi, Thai, Hebrew or Arabic word with its vowel signs and harakat is ONE
/// word). The phone used to lower-case with the platform, fold a table of Latin accents and turn every character that is not a letter or a digit into a space, which split a word at every combining
/// mark. What stays the phone's own and looser than the server's key: a leading "The", "&" as "and", the English edition words ([dropEdition]), and the ligatures and old Nordic letters of
/// [_looseLatin].
String normalizeForMatch(String input, {bool dropEdition = true}) {
  var s = input.trim();
  if (dropEdition) {
    var previous = '';
    while (previous != s) {
      previous = s;
      s = s.replaceFirst(_editionSuffix, '');
    }
  }
  s = textFold(s);
  if (s.contains(_looseLatinLetters)) {
    final buffer = StringBuffer();
    for (final rune in s.runes) {
      final ch = String.fromCharCode(rune);
      buffer.write(_looseLatin[ch] ?? ch);
    }
    s = buffer.toString();
  }
  s = s.replaceAll('&', ' and ');
  s = textWords(s).join(' ');
  if (s.startsWith('the ')) s = s.substring(4);
  return s;
}

/// `artist|album` style key.
String matchKey(String? artist, String? title) =>
    '${normalizeForMatch(artist ?? '')}|${normalizeForMatch(title ?? '')}';

/// Loose relevance test for catalogue hits: every word the user typed must
/// begin a word of [name] (case, accents, punctuation and "The" ignored).
///
/// `matchesQueryWords('Billie Eilish & ROSALÍA', 'billie rosa')` is true;
/// `matchesQueryWords('Damian Marley', 'billie eilish')` is false.
bool matchesQueryWords(String name, String query) {
  final wanted = normalizeForMatch(query, dropEdition: false)
      .split(' ')
      .where((w) => w.isNotEmpty);
  if (wanted.isEmpty) return true;
  final words = normalizeForMatch(name, dropEdition: false).split(' ');
  return wanted.every((w) => words.any((n) => n.startsWith(w)));
}
