import 'package:flutter/material.dart';

import '../../design/tokens.dart';
import '../../domain/audio_quality.dart';
import '../common/encore_sheet.dart';

/// Scaffold shared by every settings sub-page: title, one-line description,
/// then the rows (docs/06-ux-spec.md 4.9).
class SettingsPage extends StatelessWidget {
  const SettingsPage({
    super.key,
    required this.title,
    this.description,
    required this.children,
    this.onRefresh,
  });

  final String title;
  final String? description;
  final List<Widget> children;

  /// When set, pulling the page down runs it (Your server asks its addresses again).
  final Future<void> Function()? onRefresh;

  @override
  Widget build(BuildContext context) {
    final list = ListView(
      physics: onRefresh == null ? null : const AlwaysScrollableScrollPhysics(),
      children: [
        if (description != null)
          Padding(
            padding: const EdgeInsets.fromLTRB(
                Space.gutter, Space.sm, Space.gutter, Space.md),
            child: Text(description!, style: context.text.bodyMedium),
          ),
        ...children,
        const SizedBox(height: Space.xxl),
      ],
    );
    return Scaffold(
      appBar: AppBar(title: Text(title)),
      body: onRefresh == null
          ? list
          : RefreshIndicator(onRefresh: onRefresh!, child: list),
    );
  }
}

/// Small coloured heading between groups of rows.
class SettingsSection extends StatelessWidget {
  const SettingsSection(this.label, {super.key});

  final String label;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(
          Space.gutter, Space.xl, Space.gutter, Space.xs),
      child: Text(
        label.toUpperCase(),
        style: context.text.labelMedium?.copyWith(
          color: context.colors.accent,
          letterSpacing: 1.1,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }
}

/// Row that shows the current [AudioQuality] and opens a chooser.
class QualityTile extends StatelessWidget {
  const QualityTile({
    super.key,
    required this.title,
    required this.value,
    required this.onChanged,
    this.options = AudioQuality.values,
    this.subtitle,
  });

  final String title;
  final String? subtitle;
  final AudioQuality value;
  final ValueChanged<AudioQuality> onChanged;
  final List<AudioQuality> options;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      title: Text(title),
      subtitle: Text(subtitle ?? value.detail),
      trailing: Text(value.label, style: context.text.labelLarge),
      onTap: () async {
        final picked = await showEncoreSheet<AudioQuality>(
          context: context,
          builder: (sheet) => SafeArea(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Padding(
                  padding: const EdgeInsets.fromLTRB(
                      Space.gutter, Space.lg, Space.gutter, Space.sm),
                  child: Text(title, style: context.text.titleLarge),
                ),
                for (final q in options)
                  ListTile(
                    leading: Icon(
                      q == value
                          ? Icons.radio_button_checked_rounded
                          : Icons.radio_button_unchecked_rounded,
                      color: q == value ? context.colors.accent : null,
                    ),
                    title: Text(q.label),
                    subtitle: Text(q.detail),
                    onTap: () => Navigator.of(sheet).pop(q),
                  ),
                const SizedBox(height: Space.md),
              ],
            ),
          ),
        );
        if (picked != null) onChanged(picked);
      },
    );
  }
}
