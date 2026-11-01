import 'package:encore/domain/lyrics.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('parseLrc', () {
    test('parses timestamps with 1-3 fraction digits', () {
      final l = parseLrc('[00:12.5] a\n[00:13.50] b\n[01:02.345] c');
      expect(l.synced, isTrue);
      expect(l.lines.map((e) => e.startMs), [12500, 13500, 62345]);
      expect(l.lines.map((e) => e.text), ['a', 'b', 'c']);
    });

    test('supports multiple stamps per line and sorts', () {
      final l = parseLrc('[00:30.00][00:10.00] chorus\n[00:20.00] verse');
      expect(l.lines.map((e) => e.startMs), [10000, 20000, 30000]);
      expect(l.lines.map((e) => e.text), ['chorus', 'verse', 'chorus']);
    });

    test('ignores metadata tags when synced', () {
      final l = parseLrc('[ar:Alcest]\n[ti:Autre temps]\n[00:01.00] hi');
      expect(l.lines, hasLength(1));
      expect(l.lines.single.text, 'hi');
    });

    test('keeps empty lyric lines (instrumental breaks)', () {
      final l = parseLrc('[00:01.00] sing\n[00:05.00]\n[00:09.00] again');
      expect(l.lines[1].isBlank, isTrue);
      expect(l.lines[1].startMs, 5000);
    });

    test('plain text becomes unsynced lines, headers dropped', () {
      final l = parseLrc('[ar:X]\nfirst\n\nsecond\n');
      expect(l.synced, isFalse);
      expect(l.lines.map((e) => e.text), ['first', '', 'second']);
      expect(l.lines.every((e) => e.startMs == null), isTrue);
    });

    test(
        'a catalogue entry that is only the details of the song is no lyrics (QA round 1, R1-3: "Any Colour You Like")',
        () {
      final l =
          parseLrc('[ti:Any Colour You Like (1973)]\r\n[ar:Pink Floyd]\r\n'
              '[al:The Dark Side Of The Moon (Japan 1st 1983)]\r\n[by:]\r\n'
              '[offset:0]\r\n\r\nArtist: Pink Floyd\r\n'
              'Album: The Dark Side of the Moon\r\nTitle: Any Colour You Like');

      expect(l.isEmpty, isTrue);
    });

    test('words that happen to contain a colon are lyrics', () {
      final l = parseLrc('Title: of nobility\nI said: no\nand then: nothing');

      expect(l.isEmpty, isFalse);
    });

    test('empty input -> empty lyrics', () {
      expect(parseLrc('   \n ').isEmpty, isTrue);
    });
  });

  group('activeIndex', () {
    final lyrics = parseLrc('[00:10.00] a\n[00:20.00] b\n[00:30.00] c');

    test('before first line', () {
      expect(lyrics.activeIndex(5000), -1);
    });
    test('on boundaries and between lines', () {
      expect(lyrics.activeIndex(10000), 0);
      expect(lyrics.activeIndex(19999), 0);
      expect(lyrics.activeIndex(20000), 1);
      expect(lyrics.activeIndex(99999), 2);
    });
    test('offset shifts the highlight', () {
      expect(lyrics.activeIndex(19000), 0);
      expect(lyrics.activeIndex(19000, offsetMs: 1500), 1);
    });
    test('unsynced lyrics never highlight', () {
      expect(parseLrc('plain').activeIndex(1000), -1);
    });
  });
}
