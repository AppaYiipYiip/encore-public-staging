import 'package:flutter/cupertino.dart' show CupertinoPageTransitionsBuilder;
import 'package:flutter/material.dart';

import 'tokens.dart';

/// Bundled font family (ADR-010: never fetched at runtime).
const String kFontFamily = 'Figtree';

/// Builds the Material 3 theme from tokens (ADR-010).
ThemeData buildEncoreTheme(EncoreColors c, {required Brightness brightness}) {
  final textTheme = _textTheme(c);
  final scheme = ColorScheme(
    brightness: brightness,
    primary: c.accent,
    onPrimary: c.onAccent,
    secondary: c.accent,
    onSecondary: c.onAccent,
    error: c.danger,
    onError: Colors.white,
    surface: c.bg,
    onSurface: c.onBg,
    surfaceContainerLowest: c.bg,
    surfaceContainerLow: c.surface,
    surfaceContainer: c.surface,
    surfaceContainerHigh: c.surfaceHigh,
    surfaceContainerHighest: c.surfaceHigh,
    outline: c.outline,
    outlineVariant: c.outline,
  );

  return ThemeData(
    useMaterial3: true,
    brightness: brightness,
    colorScheme: scheme,
    scaffoldBackgroundColor: c.bg,
    canvasColor: c.bg,
    fontFamily: kFontFamily,
    textTheme: textTheme,
    primaryTextTheme: textTheme,
    extensions: [c],
    splashFactory: InkSparkle.splashFactory,
    visualDensity: VisualDensity.standard,
    dividerTheme: DividerThemeData(color: c.outline, thickness: 0.5, space: 0),
    iconTheme: IconThemeData(color: c.onBg, size: 24),
    // A hint (an example) is visibly quieter than what a person typed, in every theme (AUDIT F38).
    inputDecorationTheme: InputDecorationTheme(
      hintStyle: TextStyle(color: c.onBgMuted.withValues(alpha: 0.7)),
    ),
    appBarTheme: AppBarTheme(
      backgroundColor: c.bg,
      foregroundColor: c.onBg,
      elevation: 0,
      scrolledUnderElevation: 0,
      centerTitle: false,
      titleTextStyle: textTheme.titleLarge,
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: c.bg.withValues(alpha: 0.96),
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      height: 64,
      indicatorColor: Colors.transparent,
      labelTextStyle: WidgetStateProperty.resolveWith((states) {
        final selected = states.contains(WidgetState.selected);
        return textTheme.labelSmall!.copyWith(
          color: selected ? c.onBg : c.onBgFaint,
          fontWeight: selected ? FontWeight.w700 : FontWeight.w500,
        );
      }),
      iconTheme: WidgetStateProperty.resolveWith((states) {
        final selected = states.contains(WidgetState.selected);
        return IconThemeData(
          color: selected ? c.onBg : c.onBgFaint,
          size: 26,
        );
      }),
    ),
    chipTheme: ChipThemeData(
      backgroundColor: c.surfaceHigh,
      selectedColor: c.accent,
      disabledColor: c.surface,
      labelStyle: textTheme.labelLarge!.copyWith(color: c.onBg),
      secondaryLabelStyle: textTheme.labelLarge!.copyWith(color: c.onAccent),
      side: BorderSide.none,
      shape: const StadiumBorder(),
      padding: const EdgeInsets.symmetric(horizontal: 6),
      showCheckmark: false,
    ),
    sliderTheme: SliderThemeData(
      trackHeight: 4,
      activeTrackColor: c.onBg,
      inactiveTrackColor: c.onBgFaint.withValues(alpha: 0.35),
      thumbColor: c.onBg,
      overlayColor: c.onBg.withValues(alpha: 0.12),
      thumbShape: const RoundSliderThumbShape(enabledThumbRadius: 6),
      overlayShape: const RoundSliderOverlayShape(overlayRadius: 16),
    ),
    bottomSheetTheme: BottomSheetThemeData(
      backgroundColor: c.surface,
      surfaceTintColor: Colors.transparent,
      showDragHandle: true,
      dragHandleColor: c.onBgFaint,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(Radii.sheet)),
      ),
    ),
    dialogTheme: DialogThemeData(
      backgroundColor: c.surfaceHigh,
      surfaceTintColor: Colors.transparent,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(Radii.sheet),
      ),
    ),
    snackBarTheme: SnackBarThemeData(
      backgroundColor: c.surfaceHigh,
      contentTextStyle: textTheme.bodyMedium!.copyWith(color: c.onBg),
      behavior: SnackBarBehavior.floating,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
    ),
    listTileTheme: ListTileThemeData(
      iconColor: c.onBgMuted,
      textColor: c.onBg,
      contentPadding: const EdgeInsets.symmetric(horizontal: Space.gutter),
    ),
    switchTheme: SwitchThemeData(
      thumbColor: WidgetStateProperty.resolveWith(
          (s) => s.contains(WidgetState.selected) ? c.onAccent : c.onBgMuted),
      trackColor: WidgetStateProperty.resolveWith(
          (s) => s.contains(WidgetState.selected) ? c.accent : c.surfaceHigh),
      trackOutlineColor: WidgetStateProperty.all(Colors.transparent),
    ),
    progressIndicatorTheme: ProgressIndicatorThemeData(
      color: c.accent,
      linearTrackColor: c.surfaceHigh,
    ),
    pageTransitionsTheme: const PageTransitionsTheme(
      builders: {
        TargetPlatform.android: FadeForwardsPageTransitionsBuilder(),
        TargetPlatform.iOS: CupertinoPageTransitionsBuilder(),
      },
    ),
  );
}

TextTheme _textTheme(EncoreColors c) {
  TextStyle s(double size, FontWeight w,
          {double? h, double? ls, Color? color}) =>
      TextStyle(
        fontFamily: kFontFamily,
        fontSize: size,
        fontWeight: w,
        height: h == null ? null : h / size,
        letterSpacing: ls,
        color: color ?? c.onBg,
      );

  return TextTheme(
    displaySmall: s(32, FontWeight.w800, h: 38, ls: -0.5),
    headlineMedium: s(26, FontWeight.w800, h: 32, ls: -0.3),
    headlineSmall: s(22, FontWeight.w700, h: 28),
    titleLarge: s(20, FontWeight.w700, h: 26),
    titleMedium: s(16, FontWeight.w600, h: 22),
    titleSmall: s(14, FontWeight.w600, h: 20),
    bodyLarge: s(16, FontWeight.w500, h: 22),
    bodyMedium: s(14, FontWeight.w400, h: 20, color: c.onBgMuted),
    bodySmall: s(12, FontWeight.w400, h: 16, color: c.onBgMuted),
    labelLarge: s(14, FontWeight.w600, h: 20),
    labelMedium: s(12, FontWeight.w600, h: 16),
    labelSmall: s(11, FontWeight.w700, h: 14, ls: 0.4),
  );
}
