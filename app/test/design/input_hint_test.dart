import 'package:encore/design/theme.dart';
import 'package:encore/design/theme_rules.dart';
import 'package:encore/design/tokens.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// AUDIT F38: an example in a text field (the "Add an address" hint) was drawn in the colour of typed text, so a person took it for something
/// already filled in. A hint must be visibly quieter than an entry, in every theme.
/// AUDIT F42: "True black background" could be switched on in light mode; it only means something in a dark theme.
void main() {
  final themes = {
    'dark': (EncoreColors.dark(), Brightness.dark),
    'light': (EncoreColors.light(), Brightness.light),
  };

  for (final entry in themes.entries) {
    test(
        'F38: in the ${entry.key} theme a hint is not the colour of typed text',
        () {
      final (colors, brightness) = entry.value;
      final theme = buildEncoreTheme(colors, brightness: brightness);

      final hint = theme.inputDecorationTheme.hintStyle?.color;

      expect(hint, isNotNull, reason: 'the theme styles hints at all');
      expect(hint, isNot(colors.onBg));
      expect(hint == colors.onBgMuted || hint!.a < 1.0, isTrue,
          reason: 'a muted colour, not the entry colour');
    });

    testWidgets(
        'F38: a hint on screen differs from what was typed (${entry.key})',
        (tester) async {
      final (colors, brightness) = entry.value;
      await tester.pumpWidget(MaterialApp(
        theme: buildEncoreTheme(colors, brightness: brightness),
        home: const Scaffold(
          body: Column(children: [
            TextField(
                decoration:
                    InputDecoration(hintText: 'For example 192.168.1.10')),
          ]),
        ),
      ));

      final hint = tester.widget<Text>(find.text('For example 192.168.1.10'));

      expect(hint.style?.color, isNot(colors.onBg));
    });
  }

  test('F42: true black only means something in a dark theme', () {
    expect(darkThemeInUse(ThemeMode.dark, Brightness.light), isTrue);
    expect(darkThemeInUse(ThemeMode.light, Brightness.dark), isFalse,
        reason: 'light means light, whatever the phone is');
    expect(darkThemeInUse(ThemeMode.system, Brightness.dark), isTrue);
    expect(darkThemeInUse(ThemeMode.system, Brightness.light), isFalse);
  });
}
