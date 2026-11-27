// N-46 (P2-25 part 11, audit B-46): the phone compares names with the SAME fold as the server.
//
// `normalizeForMatch` used to be its own function: it lower-cased with the platform, folded a table of Latin accents and turned every character that is not a letter or a digit into a SPACE. The
// last rule splits a word at every combining mark: an Arabic word with harakat, a Hindi or Thai word with its vowel signs, a Hebrew word with niqqud, and any accent written as a base letter plus
// a mark (the way a Mac writes a file name) came apart into pieces and never met its plain spelling. These rows are real names; each one failed on the old function.
import 'package:encore/domain/text_match.dart';
import 'package:flutter_test/flutter_test.dart';

String n(String text) => normalizeForMatch(text);

void main() {
  group('names that are the same song spelled with and without decoration meet',
      () {
    test('Arabic with and without harakat', () {
      expect(n('سَأَلُونِي النَّاس'), n('سألوني الناس'));
      expect(n('سألوني الناس').split(' '), hasLength(2));
    });

    test('Arabic with each alef form, and the Persian and Arabic ye', () {
      expect(n('أم كلثوم'), n('ام كلثوم'));
      expect(n('إيمان'), n('ايمان'));
      expect(n('فیروز'), n('فيروز'));
    });

    test('digits of any script are the same digits', () {
      expect(n('٢٠٢٤'), n('2024'));
      expect(n('۱۲۳ حبیبی'), n('123 حبیبی'));
    });

    test('an accent written as a base letter and a mark is the accent', () {
      expect(n('Beyoncé'), n('Beyoncé'));
      expect(n('Beyoncé'), 'beyonce');
      expect(n('Sigur Rós'), 'sigur ros');
    });

    test('Russian with a stress mark, and the yo', () {
      expect(n('Мо́й друг'), n('мой друг'));
      expect(n('Ёлка'), n('елка'));
    });

    test(
        'a Hindi or Thai word keeps its vowel signs and is not cut into pieces',
        () {
      expect(n('तुम हो').split(' '), hasLength(2));
      expect(n('สวัสดี').split(' '), hasLength(1));
    });

    test('Hebrew with niqqud', () {
      expect(n('שָׁלוֹם'), n('שלום'));
    });

    test('halfwidth katakana and fullwidth Latin', () {
      expect(n('ｶﾞｰﾙ'), n('ガール'));
      expect(n('ＡＢＣ'), 'abc');
    });
  });

  group('different songs stay different', () {
    test('two Arabic titles', () {
      expect(n('سألوني الناس'), isNot(n('نسّم علينا الهوا')));
      expect(n('فيروز'), isNot(n('ام كلثوم')));
    });

    test('one letter of Russian', () {
      expect(n('мой'), isNot(n('мои')));
    });

    test('a voiced kana is another kana, and Korean is kept', () {
      expect(n('が'), isNot(n('か')));
      expect(n('아이유'), isNot(n('아이브')));
    });

    test('no name is folded to nothing', () {
      for (final name in [
        'فيروز',
        'Мой друг',
        '아이유',
        'アイドル',
        '夜に駆ける',
        'שלום',
        'สวัสดี',
        'तुम हो'
      ]) {
        expect(n(name), isNotEmpty, reason: name);
      }
    });
  });

  group('the phone keeps its own looser reading of Latin names', () {
    test('ligatures and the old Nordic letters', () {
      expect(n('Æon'), n('Aeon'));
      expect(n('Þór'), 'thor');
      expect(n('Bjørk'), 'bjork');
      expect(n('Łukasz'), 'lukasz');
      expect(n('Dvořák'), 'dvorak');
      expect(n('Straße'), 'strasse');
      expect(n('Mötley Crüe'), 'motley crue');
      expect(n('Cœur'), n('Coeur'));
      expect(n('Đorđe'), 'dorde');
    });

    test(
        'a leading "The", the ampersand, punctuation and the edition words still go',
        () {
      expect(n('The Weeknd'), 'weeknd');
      expect(n('Simon & Garfunkel'), n('Simon and Garfunkel'));
      expect(n("Guns N' Roses"), 'guns n roses');
      expect(n('AC/DC'), 'ac dc');
      expect(n('Folklore (Deluxe Edition)'), 'folklore');
    });
  });

  group('a search finds a name by the start of its words in any alphabet', () {
    test('Arabic, whatever the alef', () {
      expect(matchesQueryWords('سألوني الناس', 'سالو'), isTrue);
      expect(matchesQueryWords('أم كلثوم', 'ام كل'), isTrue);
      expect(matchesQueryWords('فيروز', 'ام'), isFalse);
    });

    test('Russian in either case, a decomposed accent', () {
      expect(matchesQueryWords('Мой Друг', 'мой дру'), isTrue);
      expect(matchesQueryWords('Beyoncé', 'beyoncé'), isTrue);
    });
  });
}
