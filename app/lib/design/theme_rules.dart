import 'package:flutter/material.dart';

/// Whether the dark theme is the one in use: [ThemeMode.dark], or [ThemeMode.system] on a phone that is dark. "True black background" only means
/// something then (AUDIT F42).
bool darkThemeInUse(ThemeMode mode, Brightness system) => switch (mode) {
      ThemeMode.dark => true,
      ThemeMode.light => false,
      ThemeMode.system => system == Brightness.dark,
    };
