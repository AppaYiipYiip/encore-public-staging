import 'dart:ui' show Color;

import 'package:flutter/painting.dart' show HSLColor;

/// Turns an artwork swatch into a screen backdrop (Now Playing, album
/// header, mini player): the swatch's hue, kept dark enough that white text
/// always reads on it (contrast >= 7:1 at lightness 0.30) and calm enough to
/// sit next to the cover without competing with it.
///
/// Pure and deterministic so every screen derives the same colour from the
/// same artwork and goldens stay stable.
Color backdropFor(Color swatch, {double maxLightness = 0.30}) {
  final hsl = HSLColor.fromColor(swatch);
  final saturation = hsl.saturation.clamp(0.0, 0.65);
  final lightness = hsl.lightness.clamp(0.10, maxLightness);
  return HSLColor.fromAHSL(1, hsl.hue, saturation, lightness).toColor();
}

/// Picks the swatch that best represents an album's artwork from the
/// candidates a palette extractor produced (any may be null).
///
/// Prefers a clearly coloured swatch (vibrant, then dominant, then the dark
/// and muted variants) over a grey one: a black-and-white cover then gets a
/// neutral backdrop instead of a random tint.
Color? chooseSwatch({
  Color? vibrant,
  Color? dominant,
  Color? darkVibrant,
  Color? muted,
}) {
  const minSaturation = 0.18;
  final candidates = [vibrant, dominant, darkVibrant, muted];
  for (final c in candidates) {
    if (c != null && HSLColor.fromColor(c).saturation >= minSaturation) {
      return c;
    }
  }
  return dominant ?? vibrant ?? darkVibrant ?? muted;
}
