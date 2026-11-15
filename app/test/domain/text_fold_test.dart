// The phone's twin of the server's text fold, tested against the SAME fixture
// the server's `tests/test_textnorm.py` reads (P2-25 slice 1, audit B-37).
//
// The rows are hand-written; the `corpus` section is generated
// (`tools/gen_text_fold_table.py`) and says how the fold of every code point
// and of 20,000 seeded strings is hashed (`tests/textfold_corpus.py` on the
// server): FNV-1a (32 bit) over UTF-8, pages of 256 code points, xorshift32.
// A digest that differs means the twin and Python disagree.
import 'dart:convert';
import 'dart:io';

import 'package:encore/domain/text_fold.dart';
import 'package:encore/domain/text_fold_table.g.dart';
import 'package:flutter_test/flutter_test.dart';

const int _mask = 0xffffffff;
const int _fnvOffset = 0x811c9dc5;
const int _fnvPrime = 0x01000193;

int _fnv(String record, int hash) {
  var h = hash;
  for (final byte in utf8.encode(record)) {
    h = ((h ^ byte) * _fnvPrime) & _mask;
  }
  return h;
}

String _hex8(int h) => h.toRadixString(16).padLeft(8, '0');

/// `[[page start, count, digest], ...]` for the pages that hold a record.
List<List<Object>> _pages(Iterable<MapEntry<int, String>> records) {
  final out = <List<Object>>[];
  var current = -1;
  var count = 0;
  var h = _fnvOffset;
  for (final record in records) {
    final page = record.key - record.key % 256;
    if (page != current) {
      if (current >= 0) out.add([current, count, _hex8(h)]);
      current = page;
      count = 0;
      h = _fnvOffset;
    }
    count++;
    h = _fnv('${record.key.toRadixString(16)}:${record.value}\n', h);
  }
  if (current >= 0) out.add([current, count, _hex8(h)]);
  return out;
}

Iterable<int> _codePoints() sync* {
  for (var cp = 0; cp < 0x110000; cp++) {
    if (cp >= 0xd800 && cp <= 0xdfff) continue;
    yield cp;
  }
}

Iterable<String> _randomStrings(
  List<int> pool,
  int seed,
  int count,
  int maxLength,
) sync* {
  var x = seed & _mask;
  int next() {
    x ^= (x << 13) & _mask;
    x ^= x >> 17;
    x ^= (x << 5) & _mask;
    return x;
  }

  for (var i = 0; i < count; i++) {
    final length = 1 + next() % maxLength;
    final text = StringBuffer();
    for (var j = 0; j < length; j++) {
      text.writeCharCode(pool[next() % pool.length]);
    }
    yield text.toString();
  }
}

/// The words joined; when there are none, the fold with its spaces collapsed
/// (enough for the fixture's rows: the server's `key_text` has the full rule).
String _keyText(String text) {
  final folded = textFold(text);
  final key = textWords(folded).join(' ');
  if (key.isNotEmpty) return key;
  return folded.split(RegExp(r'\s+')).where((w) => w.isNotEmpty).join(' ');
}

/// A text is compared by its key; a song `[artist, title]` by `artist|title|`.
String _keyOf(Object? value) {
  if (value is List<Object?>) {
    return '${_keyText(value[0]! as String)}|${_keyText(value[1]! as String)}|';
  }
  return _keyText(value! as String);
}

List<Map<String, Object?>> _rows(Map<String, Object?> data, String section) =>
    (data[section]! as List<Object?>).cast<Map<String, Object?>>();

const String _bump =
    "the fold changed: bump textnorm.TEXTNORM_REVISION, then run "
    "tools/gen_text_fold_table.py with the Python 3.12 the server runs on";

void main() {
  final data =
      jsonDecode(File('test/fixtures/text/fold-cases.json').readAsStringSync())
          as Map<String, Object?>;
  final corpus = data['corpus']! as Map<String, Object?>;

  group("the fixture and the table name one version", () {
    test("the table, the fixture header and the corpus agree", () {
      expect(data['unidata_version'], kTextFoldUnidataVersion);
      expect(corpus['unidata_version'], kTextFoldUnidataVersion);
      expect(data['revision'], kTextFoldRevision);
    });
  });

  group("the hand-written rows", () {
    for (final row in _rows(data, 'fold')) {
      test("fold: ${row['note']}", () {
        final folded = textFold(row['input']! as String);
        expect(folded, row['fold']! as String);
        expect(
            textWords(folded), (row['words']! as List<Object?>).cast<String>());
        expect(_keyText(row['input']! as String), row['key']! as String);
      });
    }

    for (final row in _rows(data, 'meet')) {
      test("meet: ${row['note']}", () {
        expect(_keyOf(row['a']), _keyOf(row['b']));
      });
    }

    for (final row in _rows(data, 'differ')) {
      test("differ: ${row['note']}", () {
        expect(_keyOf(row['a']), isNot(_keyOf(row['b'])));
      });
    }
  });

  group("properties", () {
    test("the fold is idempotent over every code point", () {
      final bad = <String>[];
      for (final cp in _codePoints()) {
        final once = textFold(String.fromCharCode(cp));
        if (textFold(once) != once) bad.add(cp.toRadixString(16));
      }
      expect(bad, isEmpty);
    });

    test("a format character between a base and its mark still composes", () {
      expect(textFold('か‍゙'), 'が');
    });

    test("ASCII is only lower-cased and words are cut at punctuation", () {
      expect(textFold("Don't STOP"), "don't stop");
      expect(textWords("don't stop"), ['don', 't', 'stop']);
      expect(textWords('Hello World-2'), ['Hello', 'World', '2']);
    });

    test("a run made only of marks is not a word", () {
      expect(textWords('ก่า ่'), ['ก่า']);
      expect(textWords('️'), isEmpty);
    });
  });

  group("the generated corpus (a digest that differs: $_bump)", () {
    test("the fold of every code point is the one Python computed", () {
      final records = <MapEntry<int, String>>[];
      for (final cp in _codePoints()) {
        final ch = String.fromCharCode(cp);
        final folded = textFold(ch);
        if (folded != ch) records.add(MapEntry(cp, folded));
      }
      final have = _pages(records);
      final want =
          (corpus['fold_pages']! as List<Object?>).cast<List<Object?>>();
      expect(have.length, want.length, reason: _bump);
      for (var i = 0; i < want.length; i++) {
        expect(have[i], want[i], reason: "page ${want[i][0]}: $_bump");
      }
    });

    test(
        "the classes words reads (letter, number, mark) are the ones Python has",
        () {
      final records = <MapEntry<int, String>>[];
      for (final cp in _codePoints()) {
        final klass = textClassOf(cp);
        if (klass.isNotEmpty) records.add(MapEntry(cp, klass));
      }
      final have = _pages(records);
      final want =
          (corpus['class_pages']! as List<Object?>).cast<List<Object?>>();
      expect(have.length, want.length, reason: _bump);
      for (var i = 0; i < want.length; i++) {
        expect(have[i], want[i], reason: "page ${want[i][0]}: $_bump");
      }
    });

    test("20,000 seeded strings fold and cut into words as in Python", () {
      final random = corpus['random']! as Map<String, Object?>;
      final pool = (random['pool']! as List<Object?>).cast<int>();
      var h = _fnvOffset;
      var i = 0;
      for (final text in _randomStrings(
        pool,
        random['seed']! as int,
        random['count']! as int,
        random['max_length']! as int,
      )) {
        final folded = textFold(text);
        h = _fnv('$i:$folded|${textWords(folded).join('/')}\n', h);
        i++;
      }
      expect(_hex8(h), random['digest']! as String, reason: _bump);
    });
  });
}
