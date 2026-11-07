import 'package:encore/domain/lyrics.dart';
import 'package:flutter_test/flutter_test.dart';

/// Audit B-102 (the owner, 7 Nov 2026, Opeth "Benighted"): LRCLIB's record 1918075 holds "Here weÂ´ll be gone": the UTF-8 bytes of "´"
/// read as Latin-1 and saved again. The repair only ever answers with a shorter text that is valid UTF-8 once the bytes are put back.
void main() {
  group('repairMojibake', () {
    test('the owner\'s line: "weÂ´ll" is "we´ll"', () {
      expect(repairMojibake('Here weÂ´ll be gone'), 'Here we´ll be gone');
    });

    test('accents saved twice come back (Latin-1 pairs)', () {
      expect(repairMojibake('cafÃ©'), 'café');
      expect(
          repairMojibake('Ã  la maison, trÃ¨s bien'), 'à la maison, très bien');
    });

    test('quotes and dashes saved twice come back (Windows-1252 pairs)', () {
      expect(repairMojibake('donâ€™t stop â€“ never'), 'don’t stop – never');
    });

    test('a Cyrillic line saved twice comes back', () {
      expect(repairMojibake('Ð¿Ñ\u0080Ð¸Ð²ÐµÑ\u0082'), 'привет');
    });

    test('real text stays as it is', () {
      for (final text in [
        'café',
        'Ñandú y más',
        'Âge tendre',
        'مرحبا بالعالم',
        '你好，世界',
        "Here we'll be gone",
        'Ã',
        '',
      ]) {
        expect(repairMojibake(text), text, reason: text);
      }
    });

    test('a repair that would not make the text shorter is refused', () {
      // Valid in both readings, but the second is not shorter: leave it.
      expect(repairMojibake('Ã'), 'Ã');
    });
  });

  group('parseLrc repairs each line', () {
    test('plain text', () {
      final lyrics = parseLrc('Come into this night\nHere weÂ´ll be gone');

      expect(lyrics.synced, isFalse);
      expect(lyrics.lines.map((l) => l.text),
          ['Come into this night', 'Here we´ll be gone']);
    });

    test('synced text', () {
      final lyrics = parseLrc(
          '[00:01.00] Come into this night\n[00:05.00] Here weÂ´ll be gone');

      expect(lyrics.synced, isTrue);
      expect(lyrics.lines.last.text, 'Here we´ll be gone');
    });
  });
}
