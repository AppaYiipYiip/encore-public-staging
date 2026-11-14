import 'dart:math';

import 'package:encore/domain/artist_typo.dart';
import 'package:encore/domain/search_rank.dart';
import 'package:flutter_test/flutter_test.dart';

/// N-23a: the typo rule for artist names, in one sentence: **when what was typed and an artist's name both have 5 or more letters, one
/// letter wrong, missing, extra or swapped with its neighbour is still that artist, and two from 9 letters on.**
void main() {
  group('how many edits a name may be off', () {
    test('none for 1 to 4 letters, one for 5 to 8, two from 9', () {
      expect([for (var n = 0; n <= 4; n++) typoAllowance(n)], everyElement(0));
      expect([for (var n = 5; n <= 8; n++) typoAllowance(n)], everyElement(1));
      expect([for (var n = 9; n <= 30; n++) typoAllowance(n)], everyElement(2));
    });
  });

  group('typoEdits', () {
    test('the owner\'s example: "landmarks" is "Landmvrks"', () {
      expect(typoEdits('landmarks', 'landmvrks'), 1);
    });

    test('a letter wrong, missing or extra is one edit', () {
      expect(typoEdits('radiohed', 'radiohead'), 1, reason: 'missing');
      expect(typoEdits('radiohaed', 'radiohead'), 1, reason: 'swapped');
      expect(typoEdits('radioheead', 'radiohead'), 1, reason: 'extra');
      expect(typoEdits('rodiohead', 'radiohead'), 1, reason: 'wrong');
      expect(typoEdits('metalx', 'metal'), 1);
      expect(typoEdits('metla', 'metal'), 1, reason: 'swapped, 5 letters');
    });

    test('two letters swapped with their neighbours is a typo of its own', () {
      expect(typoEdits('lnadmarks', 'landmarks'), 1,
          reason: 'one swap is one edit, not two');
      expect(typoEdits('landmakrs', 'landmarks'), 1,
          reason: 'the swap can be anywhere in the name');
    });

    test('the same name is no edit at all', () {
      expect(typoEdits('landmarks', 'landmarks'), 0);
    });

    test('one edit only for 5 to 8 letters, two from 9', () {
      expect(typoEdits('jinjer', 'jinjir'), 1);
      expect(typoEdits('jinjer', 'jonjir'), isNull,
          reason: 'two wrong in a 6 letter name');
      expect(typoEdits('landmarks', 'lendmvrks'), 2,
          reason: 'two wrong in a 9 letter name');
      expect(typoEdits('landmarks', 'lendmvrkz'), isNull,
          reason: 'three wrong is another band');
      expect(typoEdits('landmark', 'landmvrx'), isNull,
          reason: 'two wrong in an 8 letter name');
    });

    test('never when the name or what was typed has fewer than 5 letters', () {
      expect(typoEdits('mose', 'muse'), isNull);
      expect(typoEdits('abca', 'abba'), isNull);
      expect(typoEdits('tooll', 'tool'), isNull, reason: 'a 4 letter name');
      expect(typoEdits('mtal', 'metal'), isNull, reason: 'typed in 4 letters');
      expect(typoEdits('', ''), isNull);
      expect(typoEdits('a', 'b'), isNull);
    });

    test('words are told apart by the letters, spaces do not count as letters',
        () {
      // "billie eilish": 12 letters, so two edits.
      expect(typoEdits('billie eilsh', 'billie eilish'), 1);
      expect(typoEdits('bilie eilsh', 'billie eilish'), 2);
      // "tom odell": 8 letters and one space: the space is not a letter, so one edit only.
      expect(typoEdits('tom odel', 'tom odell'), 1);
      expect(typoEdits('tim odel', 'tom odell'), isNull);
    });

    test('a different length by more than the edits allowed is no match', () {
      expect(typoEdits('landmarks and more', 'landmarks'), isNull);
      expect(typoEdits('landmar', 'landmarks'), isNull);
    });

    test('every alphabet: the rule counts letters, not Latin ones', () {
      expect(typoEdits('كايروكى', 'كايروكي'), 1);
      expect(typoEdits('мумий тролль', 'мумий троль'), 1);
      expect(typoEdits('東京事変です', '東京事変です'), 0);
    });

    test('agrees with a plain reference on thousands of random pairs', () {
      final random = Random(23);
      String word() => String.fromCharCodes([
            for (var i = 0, n = 3 + random.nextInt(12); i < n; i++)
              97 + random.nextInt(4)
          ]);
      var matched = 0;
      for (var i = 0; i < 4000; i++) {
        final a = word();
        // Half of the pairs are one or two random edits of each other, so that the matching side is exercised too.
        var b = word();
        if (i.isEven) {
          final chars = a.split('');
          for (var e = random.nextInt(3); e > 0 && chars.length > 1; e--) {
            final at = random.nextInt(chars.length - 1);
            switch (random.nextInt(4)) {
              case 0:
                chars[at] = String.fromCharCode(97 + random.nextInt(4));
              case 1:
                chars.removeAt(at);
              case 2:
                chars.insert(at, String.fromCharCode(97 + random.nextInt(4)));
              default:
                final t = chars[at];
                chars[at] = chars[at + 1];
                chars[at + 1] = t;
            }
          }
          b = chars.join();
        }
        final letters = min(a.length, b.length);
        final allowed = letters < 5 ? 0 : typoAllowance(letters);
        final reference = _osa(a, b);
        final expected =
            reference <= allowed && letters >= 5 ? reference : null;
        expect(typoEdits(a, b), expected, reason: '$a vs $b');
        if (expected != null) matched++;
      }
      expect(matched, greaterThan(200),
          reason: 'the cases cover matches, not only misses');
    });
  });

  group('the index of artist names', () {
    String fold(String s) => searchKey(s);
    ArtistTypoIndex<String> index(List<String> names) =>
        ArtistTypoIndex<String>(names, nameOf: (n) => n, fold: fold);

    test('finds the artists whose name is a typo of what was typed', () {
      final found = index(['Jinjer', 'Landmvrks', 'Opeth', 'Lamb of God'])
          .find('landmarks');
      expect(found, ['Landmvrks']);
    });

    test('folds both sides the way the search scores do', () {
      final names = index(['Beyoncé', 'Sigur Rós', "Guns N' Roses", 'Ænima']);
      expect(names.find('beyonse'), ['Beyoncé']);
      expect(names.find('sigur rps'), ['Sigur Rós']);
      expect(names.find('guns n roess'), ["Guns N' Roses"],
          reason: 'an apostrophe joins letters, as in artistMatch');
    });

    test('the closest first, then the order of the library; at most [limit]',
        () {
      final names = index(['Jinjir', 'Jonjer', 'Jinjer', 'Jenjer', 'Janjer']);
      expect(names.find('jinjer'),
          ['Jinjer', 'Jinjir', 'Jonjer', 'Jenjer', 'Janjer']);
      expect(names.find('jinjer', limit: 2), ['Jinjer', 'Jinjir']);
    });

    test('finds nothing for a short word, an empty one or no near name', () {
      final names = index(['Muse', 'Tool', 'Metal Church', 'Opeth']);
      expect(names.find('mose'), isEmpty);
      expect(names.find(''), isEmpty);
      expect(names.find('   '), isEmpty);
      expect(names.find('zzzzzz'), isEmpty);
    });

    test('folds the names once, on the first search', () {
      var folded = 0;
      final names = ['Landmvrks', 'Jinjer'];
      final built = ArtistTypoIndex<String>(names,
          nameOf: (n) => n,
          fold: (s) {
            folded++;
            return fold(s);
          });
      expect(folded, 0, reason: 'nothing is folded before the first search');
      built.find('landmarks');
      final afterFirst = folded;
      built.find('jinjir');
      built.find('opeth');
      expect(folded - afterFirst, 2,
          reason: 'a later search folds only the typed words, never the names');
    });

    test('a list that arrives again with the same names is not folded again',
        () {
      var folded = 0;
      String count(String s) {
        folded++;
        return fold(s);
      }

      ArtistTypoIndex<(String, int)> build(List<(String, int)> artists,
              {ArtistTypoIndex<(String, int)>? reusing}) =>
          ArtistTypoIndex<(String, int)>(artists,
              nameOf: (a) => a.$1, fold: count, reusing: reusing);

      final first = build([('Landmvrks', 1), ('Jinjer', 1)]);
      expect(first.find('landmarks'), [('Landmvrks', 1)]);
      final afterFirst = folded;

      // The same artists, one of them changed in another way (a new count of albums): new rows, the same names.
      final again = build([('Landmvrks', 2), ('Jinjer', 1)], reusing: first);
      expect(again.find('landmarks'), [('Landmvrks', 2)],
          reason: 'the answer is made of the rows of the new list');
      expect(folded - afterFirst, 1,
          reason: 'only the typed words were folded, not the names');

      // A name that changed (or a longer list) is folded again.
      final renamed = build([('Landmvrks', 2), ('Jinjir', 1)], reusing: again);
      final beforeRenamed = folded;
      expect(renamed.find('jinjer'), [('Jinjir', 1)]);
      expect(folded - beforeRenamed, 3, reason: '2 names and the typed words');
    });

    test('a list is never given the folded names of an index never searched',
        () {
      var folded = 0;
      final unused =
          ArtistTypoIndex<String>(['Landmvrks'], nameOf: (n) => n, fold: fold);
      final next = ArtistTypoIndex<String>(['Landmvrks'],
          nameOf: (n) => n,
          fold: (s) {
            folded++;
            return fold(s);
          },
          reusing: unused);
      expect(next.find('landmarks'), ['Landmvrks']);
      expect(folded, 2, reason: 'the name and the typed words');
    });

    test('5,000 names are scanned within the 10 ms budget', () {
      final random = Random(7);
      String name() => String.fromCharCodes(
          [for (var i = 0; i < 9; i++) 97 + random.nextInt(26)]);
      // The worst case for the length filter: every name has the length of the query.
      final names = [for (var i = 0; i < 5000; i++) name()];
      final built = index(names);
      // The first search folds the 5,000 names once (about 100 ms in a debug run, which is why it is kept); it is not what is timed.
      built.find('warmup');
      var best = 1 << 30;
      for (var run = 0; run < 7; run++) {
        final sw = Stopwatch()..start();
        built.find('landmarks');
        sw.stop();
        best = min(best, sw.elapsedMicroseconds);
      }
      // The budget is 10 ms; a run takes about 1.5 ms here (JIT). The best of 7 runs after a warm-up is taken, so that a busy machine
      // does not make it flaky: what it guards is that the scan is a loop over folded keys and not a fold, a query or an all-pairs
      // comparison per name.
      expect(best, lessThan(10000), reason: 'best of 7 runs: $best us');
    });
  });

  group('the scale of artistMatch', () {
    test('an exact name, then the start of a name, then a typo, then words',
        () {
      expect(artistMatch('landmvrks', 'Landmvrks'), 0.95);
      expect(artistMatch('landm', 'Landmvrks'), 0.7);
      expect(artistMatch('landmarks', 'Landmvrks'), typoArtistScore);
      expect(typoArtistScore, 0.6);
      expect(artistMatch('vrks', 'Landmvrks'), 0);
    });

    test('a typo is below every exact answer and above the loose ones', () {
      final exact = artistMatch('landmvrks', 'Landmvrks');
      final starts = artistMatch('landm', 'Landmvrks');
      final words = artistMatch('eilish', 'Billie Eilish');
      expect(typoArtistScore, lessThan(starts));
      expect(starts, lessThan(exact));
      expect(typoArtistScore, greaterThan(words),
          reason:
              'a word that is not the first of the name is only a loose answer');
      // It sits inside the band of the partial songs (0.5 to [partialSongCeiling]), not above it: a song whose title starts with the
      // typed word is a better answer than a name that is only close, a song that merely contains the word is not.
      expect(typoArtistScore, lessThan(partialSongCeiling));
      expect(
          songMatch('landmarks', artist: 'Someone', title: 'Landmarks Of Home'),
          greaterThan(typoArtistScore),
          reason: 'a title that starts with the typed word is above a typo');
      expect(
          songMatch('landmarks', artist: 'Someone', title: 'Home Landmarks Of'),
          lessThanOrEqualTo(typoArtistScore + 0.02),
          reason: 'a title that only contains the word is about level with it');
      expect(typoArtistScore, greaterThanOrEqualTo(0.5),
          reason: 'it is still a candidate for the Top result');
    });

    test('the one rule decides: a swap is found, a short name is not', () {
      expect(artistMatch('jinjre', 'Jinjer'), typoArtistScore,
          reason: 'Levenshtein calls a swap two edits (0.67), the rule one');
      expect(artistMatch('mose', 'Muse'), 0);
      expect(artistMatch('abca', 'Abba'), 0);
    });
  });
}

/// The textbook optimal string alignment distance, for the cross-check.
int _osa(String a, String b) {
  final d = List.generate(a.length + 1, (_) => List.filled(b.length + 1, 0));
  for (var i = 0; i <= a.length; i++) {
    d[i][0] = i;
  }
  for (var j = 0; j <= b.length; j++) {
    d[0][j] = j;
  }
  for (var i = 1; i <= a.length; i++) {
    for (var j = 1; j <= b.length; j++) {
      final cost = a[i - 1] == b[j - 1] ? 0 : 1;
      var best =
          min(min(d[i - 1][j] + 1, d[i][j - 1] + 1), d[i - 1][j - 1] + cost);
      if (i > 1 && j > 1 && a[i - 1] == b[j - 2] && a[i - 2] == b[j - 1]) {
        best = min(best, d[i - 2][j - 2] + 1);
      }
      d[i][j] = best;
    }
  }
  return d[a.length][b.length];
}
