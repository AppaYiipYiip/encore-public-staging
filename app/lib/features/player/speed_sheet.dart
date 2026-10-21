import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../design/tokens.dart';
import '../providers.dart';
import '../settings/settings_controller.dart';

/// Speeds offered in the sheet (the engine accepts 0.5x - 2x).
const List<double> kPlaybackSpeeds = [0.75, 1.0, 1.25, 1.5, 1.75, 2.0];

/// `1x`, `1.25x`, `0.75x`.
String speedLabel(double speed) {
  final text = speed == speed.roundToDouble()
      ? speed.toStringAsFixed(0)
      : speed
          .toStringAsFixed(2)
          .replaceFirst(RegExp(r'0+$'), '')
          .replaceFirst(RegExp(r'\.$'), '');
  return '${text}x';
}

Future<void> showSpeedSheet(BuildContext context) {
  return showModalBottomSheet<void>(
    context: context,
    builder: (_) => const _SpeedSheet(),
  );
}

class _SpeedSheet extends ConsumerWidget {
  const _SpeedSheet();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final current = ref.watch(settingsProvider.select((s) => s.playbackSpeed));
    final c = context.colors;

    void choose(double speed) {
      unawaited(HapticFeedback.selectionClick());
      // The setting is persisted and applied by the engine; the call keeps
      // the running player in step at once.
      ref.read(settingsProvider.notifier).setPlaybackSpeed(speed);
      unawaited(ref.read(playbackFacadeProvider).setSpeed(speed));
      Navigator.of(context).pop();
    }

    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(
            Space.gutter, Space.lg, Space.gutter, Space.xl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Playback speed', style: context.text.titleLarge),
            const SizedBox(height: Space.xs),
            Text(
              'Pitch stays the same. Applies to everything you play.',
              style: context.text.bodyMedium,
            ),
            const SizedBox(height: Space.lg),
            Wrap(
              spacing: Space.sm,
              runSpacing: Space.sm,
              children: [
                for (final speed in kPlaybackSpeeds)
                  ChoiceChip(
                    label: Text(speedLabel(speed)),
                    selected: speed == current,
                    onSelected: (_) => choose(speed),
                    labelStyle: context.text.labelLarge?.copyWith(
                      color: speed == current ? c.onAccent : c.onBg,
                    ),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
