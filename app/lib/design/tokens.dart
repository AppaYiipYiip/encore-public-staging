import 'package:flutter/material.dart';

/// Design tokens (docs/06-ux-spec.md section 2). Everything visual in the new
/// UI derives from these values, so a rebrand or accent change is one edit.
abstract final class Space {
  static const double xxs = 2;
  static const double xs = 4;
  static const double sm = 8;
  static const double md = 12;
  static const double lg = 16;
  static const double xl = 24;
  static const double xxl = 32;

  /// Horizontal page gutter.
  static const double gutter = 16;
}

abstract final class Radii {
  /// Artwork in rows and queues.
  static const double art = 4;
  static const double card = 8;
  static const double sheet = 20;
  static const double hero = 12;
  static const double pill = 999;
}

abstract final class Motion {
  static const Duration quick = Duration(milliseconds: 120);
  static const Duration standard = Duration(milliseconds: 220);
  static const Duration emphasized = Duration(milliseconds: 320);
  static const Duration colour = Duration(milliseconds: 450);
  static const Curve curve = Curves.easeOutCubic;
}

/// Brand accent (ADR-020: placeholder identity, easy to change).
const Color kDefaultAccent = Color(0xFF19E68C);

/// Semantic colours exposed through the theme so widgets never hard-code.
@immutable
class EncoreColors extends ThemeExtension<EncoreColors> {
  const EncoreColors({
    required this.bg,
    required this.surface,
    required this.surfaceHigh,
    required this.outline,
    required this.onBg,
    required this.onBgMuted,
    required this.onBgFaint,
    required this.accent,
    required this.onAccent,
    required this.danger,
    required this.warning,
  });

  factory EncoreColors.dark(
      {Color accent = kDefaultAccent, bool amoled = false}) {
    return EncoreColors(
      bg: amoled ? const Color(0xFF000000) : const Color(0xFF0E0E10),
      surface: const Color(0xFF18181B),
      surfaceHigh: const Color(0xFF26262B),
      outline: const Color(0xFF34343A),
      onBg: const Color(0xFFFFFFFF),
      onBgMuted: const Color(0xFFFFFFFF).withValues(alpha: 0.70),
      onBgFaint: const Color(0xFFFFFFFF).withValues(alpha: 0.45),
      accent: accent,
      onAccent: const Color(0xFF05140D),
      danger: const Color(0xFFFF5C5C),
      warning: const Color(0xFFFFB020),
    );
  }

  factory EncoreColors.light({Color accent = const Color(0xFF0BA862)}) {
    return EncoreColors(
      bg: const Color(0xFFFFFFFF),
      surface: const Color(0xFFF4F4F6),
      surfaceHigh: const Color(0xFFE9E9ED),
      outline: const Color(0xFFD7D7DD),
      onBg: const Color(0xFF0E0E10),
      onBgMuted: const Color(0xFF0E0E10).withValues(alpha: 0.65),
      onBgFaint: const Color(0xFF0E0E10).withValues(alpha: 0.42),
      accent: accent,
      onAccent: const Color(0xFFFFFFFF),
      danger: const Color(0xFFD92D20),
      warning: const Color(0xFFB54708),
    );
  }

  final Color bg;
  final Color surface;
  final Color surfaceHigh;
  final Color outline;
  final Color onBg;
  final Color onBgMuted;
  final Color onBgFaint;
  final Color accent;
  final Color onAccent;
  final Color danger;
  final Color warning;

  @override
  EncoreColors copyWith({
    Color? bg,
    Color? surface,
    Color? surfaceHigh,
    Color? outline,
    Color? onBg,
    Color? onBgMuted,
    Color? onBgFaint,
    Color? accent,
    Color? onAccent,
    Color? danger,
    Color? warning,
  }) =>
      EncoreColors(
        bg: bg ?? this.bg,
        surface: surface ?? this.surface,
        surfaceHigh: surfaceHigh ?? this.surfaceHigh,
        outline: outline ?? this.outline,
        onBg: onBg ?? this.onBg,
        onBgMuted: onBgMuted ?? this.onBgMuted,
        onBgFaint: onBgFaint ?? this.onBgFaint,
        accent: accent ?? this.accent,
        onAccent: onAccent ?? this.onAccent,
        danger: danger ?? this.danger,
        warning: warning ?? this.warning,
      );

  @override
  EncoreColors lerp(ThemeExtension<EncoreColors>? other, double t) {
    if (other is! EncoreColors) return this;
    return EncoreColors(
      bg: Color.lerp(bg, other.bg, t)!,
      surface: Color.lerp(surface, other.surface, t)!,
      surfaceHigh: Color.lerp(surfaceHigh, other.surfaceHigh, t)!,
      outline: Color.lerp(outline, other.outline, t)!,
      onBg: Color.lerp(onBg, other.onBg, t)!,
      onBgMuted: Color.lerp(onBgMuted, other.onBgMuted, t)!,
      onBgFaint: Color.lerp(onBgFaint, other.onBgFaint, t)!,
      accent: Color.lerp(accent, other.accent, t)!,
      onAccent: Color.lerp(onAccent, other.onAccent, t)!,
      danger: Color.lerp(danger, other.danger, t)!,
      warning: Color.lerp(warning, other.warning, t)!,
    );
  }
}

extension EncoreTheme on BuildContext {
  EncoreColors get colors => Theme.of(this).extension<EncoreColors>()!;
  TextTheme get text => Theme.of(this).textTheme;
}

/// Returns [fg] adjusted until it has at least [minRatio] contrast against
/// [bg] (WCAG relative luminance). Used for artwork-derived accents.
Color ensureContrast(Color fg, Color bg, {double minRatio = 4.5}) {
  double ratio(Color a, Color b) {
    final la = a.computeLuminance();
    final lb = b.computeLuminance();
    final hi = la > lb ? la : lb;
    final lo = la > lb ? lb : la;
    return (hi + 0.05) / (lo + 0.05);
  }

  if (ratio(fg, bg) >= minRatio) return fg;
  final hsl = HSLColor.fromColor(fg);
  final bgIsDark = bg.computeLuminance() < 0.5;
  var lightness = hsl.lightness;
  for (var i = 0; i < 40; i++) {
    lightness =
        (bgIsDark ? lightness + 0.02 : lightness - 0.02).clamp(0.0, 1.0);
    final candidate = hsl.withLightness(lightness).toColor();
    if (ratio(candidate, bg) >= minRatio) return candidate;
  }
  return bgIsDark ? const Color(0xFFFFFFFF) : const Color(0xFF000000);
}

/// Deterministic, pleasant background tint for an item (album/playlist name)
/// used until its real artwork colour is known (ADR-011). Same input -> same
/// colour, so the UI never "flickers" between sessions.
Color tintFor(String? seed,
    {double saturation = 0.48, double lightness = 0.28}) {
  const hues = [158.0, 200.0, 262.0, 320.0, 12.0, 38.0, 96.0, 226.0];
  final text = (seed ?? '').trim();
  final h = text.isEmpty
      ? 0
      : text.codeUnits.fold<int>(7, (a, b) => (a * 31 + b) & 0x7fffffff);
  return HSLColor.fromAHSL(1, hues[h % hues.length], saturation, lightness)
      .toColor();
}
