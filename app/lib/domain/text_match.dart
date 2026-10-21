/// Loose, deterministic comparison of music metadata strings.
///
/// Used to decide "is this catalogue item already in my library?" and "did my
/// request arrive?". It is intentionally forgiving about case, accents,
/// punctuation, "The " prefixes and edition/remaster suffixes, because the
/// same release is spelled differently by Deezer, MusicBrainz and file tags.
library;

const Map<String, String> _fold = {
  'à': 'a',
  'á': 'a',
  'â': 'a',
  'ã': 'a',
  'ä': 'a',
  'å': 'a',
  'ā': 'a',
  'ç': 'c',
  'ć': 'c',
  'č': 'c',
  'è': 'e',
  'é': 'e',
  'ê': 'e',
  'ë': 'e',
  'ē': 'e',
  'ę': 'e',
  'ě': 'e',
  'ì': 'i',
  'í': 'i',
  'î': 'i',
  'ï': 'i',
  'ī': 'i',
  'ñ': 'n',
  'ń': 'n',
  'ň': 'n',
  'ò': 'o',
  'ó': 'o',
  'ô': 'o',
  'õ': 'o',
  'ö': 'o',
  'ø': 'o',
  'ō': 'o',
  'ù': 'u',
  'ú': 'u',
  'û': 'u',
  'ü': 'u',
  'ū': 'u',
  'ů': 'u',
  'ý': 'y',
  'ÿ': 'y',
  'š': 's',
  'ś': 's',
  'ß': 'ss',
  'ž': 'z',
  'ź': 'z',
  'ż': 'z',
  'ł': 'l',
  'đ': 'd',
  'ð': 'd',
  'þ': 'th',
  'æ': 'ae',
  'œ': 'oe',
  '’': "'",
  '‘': "'",
  '“': '"',
  '”': '"',
};

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
String normalizeForMatch(String input, {bool dropEdition = true}) {
  var s = input.trim().toLowerCase();
  if (dropEdition) {
    var previous = '';
    while (previous != s) {
      previous = s;
      s = s.replaceFirst(_editionSuffix, '');
    }
  }
  final buffer = StringBuffer();
  for (final rune in s.runes) {
    final ch = String.fromCharCode(rune);
    buffer.write(_fold[ch] ?? ch);
  }
  s = buffer.toString();
  s = s.replaceAll('&', ' and ');
  s = s.replaceAll(RegExp(r"[^\p{L}\p{N}\s]", unicode: true), ' ');
  s = s.replaceAll(RegExp(r'\s+'), ' ').trim();
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
