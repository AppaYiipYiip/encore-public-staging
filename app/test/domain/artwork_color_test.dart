import 'dart:math' as math;
import 'dart:ui' show Color;

import 'package:encore/domain/artwork_color.dart';
import 'package:flutter/painting.dart' show HSLColor;
import 'package:flutter_test/flutter_test.dart';

/// WCAG contrast ratio of white text on [c].
double _contrastWithWhite(Color c) {
  double channel(double v) =>
      v <= 0.03928 ? v / 12.92 : math.pow((v + 0.055) / 1.055, 2.4).toDouble();
  final luminance =
      0.2126 * channel(c.r) + 0.7152 * channel(c.g) + 0.0722 * channel(c.b);
  return 1.05 / (luminance + 0.05);
}

void main() {
  group('backdropFor', () {
    test('a bright colour is darkened until white text reads on it', () {
      const yellow = Color(0xFFFFE600);
      final b = backdropFor(yellow);
      expect(HSLColor.fromColor(b).lightness, lessThanOrEqualTo(0.30 + 1e-6));
      expect(_contrastWithWhite(b), greaterThan(4.5));
    });

    test('keeps the hue of the artwork', () {
      const teal = Color(0xFF14B8A6);
      final b = backdropFor(teal);
      expect(HSLColor.fromColor(b).hue,
          closeTo(HSLColor.fromColor(teal).hue, 2.0));
    });

    test('near-black artwork is lifted a little so the page is not void', () {
      final b = backdropFor(const Color(0xFF000000));
      expect(HSLColor.fromColor(b).lightness, greaterThanOrEqualTo(0.10));
    });

    test('over-saturated colours are calmed', () {
      final b = backdropFor(const Color(0xFFFF0000));
      expect(HSLColor.fromColor(b).saturation, lessThanOrEqualTo(0.65 + 1e-6));
    });

    test('is deterministic and opaque', () {
      const c = Color(0xFF3355AA);
      expect(backdropFor(c), backdropFor(c));
      expect(backdropFor(c).a, 1.0);
    });
  });

  group('chooseSwatch', () {
    const vibrant = Color(0xFFE5392B);
    const dominant = Color(0xFF223344);
    const grey = Color(0xFF808080);

    test('prefers the vibrant swatch', () {
      expect(chooseSwatch(vibrant: vibrant, dominant: dominant), vibrant);
    });

    test('skips grey swatches in favour of a coloured one', () {
      expect(chooseSwatch(vibrant: grey, dominant: dominant), dominant);
    });

    test('an all-grey cover falls back to its dominant colour', () {
      expect(chooseSwatch(vibrant: grey, dominant: const Color(0xFF777777)),
          const Color(0xFF777777));
    });

    test('nothing in, nothing out', () {
      expect(chooseSwatch(), isNull);
    });
  });
}
