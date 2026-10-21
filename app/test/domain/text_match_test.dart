import 'package:encore/domain/text_match.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('normalizeForMatch', () {
    test('folds case, accents, punctuation and a leading "The"', () {
      expect(normalizeForMatch('The Weeknd'), 'weeknd');
      expect(normalizeForMatch('Sigur Rós'), 'sigur ros');
      expect(normalizeForMatch("Guns N' Roses"), 'guns n roses');
      expect(normalizeForMatch('AC/DC'), 'ac dc');
    });

    test('drops edition suffixes only when asked to', () {
      expect(normalizeForMatch('Folklore (Deluxe Edition)'), 'folklore');
      expect(normalizeForMatch('Folklore (Deluxe Edition)', dropEdition: false),
          'folklore deluxe edition');
    });

    test('"&" and "and" are the same word', () {
      expect(normalizeForMatch('Simon & Garfunkel'),
          normalizeForMatch('Simon and Garfunkel'));
    });
  });

  group('matchKey', () {
    test('same release spelled differently has one key', () {
      expect(matchKey('Opeth', 'Ghost Reveries (Remastered)'),
          matchKey('OPETH', 'ghost reveries'));
    });

    test('"Remastered Version" and "Remastered Edition" are one release too',
        () {
      // The catalogue spells Pink Floyd's reissues this way ("Animals (2018
      // Remastered Version)"); the library holds the plain name (B39).
      expect(matchKey('Pink Floyd', 'Animals (2018 Remastered Version)'),
          matchKey('Pink Floyd', 'Animals'));
      expect(matchKey('Pink Floyd', 'Animals - Remastered Edition'),
          matchKey('Pink Floyd', 'Animals'));
      expect(matchKey('Pink Floyd', 'Animals [Remastered Version 2011]'),
          matchKey('Pink Floyd', 'Animals'));
    });

    test('"album version" and "explicit" tags are not a different song', () {
      expect(matchKey('Tool', 'Forty Six & 2 (album version)'),
          matchKey('TOOL', 'Forty Six & 2'));
      expect(matchKey('Tool', 'Stinkfist [Explicit]'),
          matchKey('Tool', 'Stinkfist'));
      expect(matchKey('Tool', 'Sober (Single Version)'),
          matchKey('Tool', 'Sober'));
    });

    test('a live take or a remix is a different song', () {
      expect(
          matchKey('Tool', 'Sober (Live)'), isNot(matchKey('Tool', 'Sober')));
      expect(
          matchKey('Tool', 'Sober (Remix)'), isNot(matchKey('Tool', 'Sober')));
    });

    test('null artist and title do not crash', () {
      expect(matchKey(null, null), '|');
    });
  });

  group('matchesQueryWords', () {
    test('every typed word must start a word of the name', () {
      expect(matchesQueryWords('Billie Eilish', 'billie eilish'), isTrue);
      expect(matchesQueryWords('Billie Eilish', 'bill eil'), isTrue);
      expect(
          matchesQueryWords('Billie Eilish & ROSALÍA', 'billie rosa'), isTrue);
      expect(matchesQueryWords('Damian Marley', 'billie eilish'), isFalse);
    });

    test('word order and "The" do not matter', () {
      expect(matchesQueryWords('The Weeknd', 'weeknd'), isTrue);
      expect(matchesQueryWords('The Weeknd', 'the weeknd'), isTrue);
      expect(matchesQueryWords('Eilish Billie', 'billie eilish'), isTrue);
    });

    test('an empty query matches everything', () {
      expect(matchesQueryWords('Anything', '   '), isTrue);
    });

    test('a middle-of-word fragment is not a match', () {
      expect(matchesQueryWords('Periphery', 'riph'), isFalse);
    });
  });
}
