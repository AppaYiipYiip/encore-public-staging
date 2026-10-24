import 'dart:math';

import 'package:encore/design/tokens.dart';
import 'package:flutter/painting.dart';
import 'package:flutter_test/flutter_test.dart';

// WCAG 2.x relative luminance and contrast ratio (docs/design/02: the three light tokens failed this; the drawings' agents found it).
double _linear(double channel) => channel <= 0.03928
    ? channel / 12.92
    : pow((channel + 0.055) / 1.055, 2.4).toDouble();

double _luminance(Color c) =>
    0.2126 * _linear(c.r) + 0.7152 * _linear(c.g) + 0.0722 * _linear(c.b);

double contrast(Color a, Color b) {
  final la = _luminance(a);
  final lb = _luminance(b);
  return (max(la, lb) + 0.05) / (min(la, lb) + 0.05);
}

void main() {
  final themes = {
    'dark': EncoreColors.dark(),
    'dark (black background)': EncoreColors.dark(amoled: true),
    'light': EncoreColors.light(),
  };

  for (final entry in themes.entries) {
    final c = entry.value;
    final name = entry.key;
    // What a surface looks like to a pill of text: the colour over the background (an alpha is laid over it first).
    Color over(Color top, Color bottom) => Color.alphaBlend(top, bottom);

    group('contrast ($name theme)', () {
      test('text on the background and on a card is at least 4.5:1', () {
        for (final bg in [c.bg, c.surface, c.surfaceHigh]) {
          expect(contrast(over(c.onBg, bg), bg), greaterThanOrEqualTo(4.5),
              reason: 'onBg on $bg');
          expect(contrast(over(c.onBgMuted, bg), bg), greaterThanOrEqualTo(4.5),
              reason: 'onBgMuted on $bg');
        }
      });

      test('the label on an accent button is at least 4.5:1', () {
        expect(contrast(c.onAccent, c.accent), greaterThanOrEqualTo(4.5));
      });

      test(
          'the accent against the background (an icon, a link, a bar) is at least 3:1',
          () {
        expect(contrast(c.accent, c.bg), greaterThanOrEqualTo(3.0));
      });

      test('a warning or an error written in its colour is at least 4.5:1', () {
        for (final bg in [c.bg, c.surface]) {
          expect(contrast(c.danger, bg), greaterThanOrEqualTo(4.5),
              reason: 'danger on $bg');
          expect(contrast(c.warning, bg), greaterThanOrEqualTo(4.5),
              reason: 'warning on $bg');
        }
      });

      test('the outline against the background (a boundary) is visible', () {
        expect(contrast(c.outline, c.bg), greaterThanOrEqualTo(1.2));
      });
    });
  }
}
