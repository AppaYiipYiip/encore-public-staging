import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../design/tokens.dart';
import '../providers.dart';
import 'playback_facade.dart';

final sleepTimerProvider = StreamProvider.autoDispose<SleepTimerStatus>((ref) {
  final facade = ref.watch(playbackFacadeProvider);
  return Stream.multi((controller) {
    controller.add(facade.sleepTimer);
    final sub = facade.sleepTimerStream.listen(controller.add);
    controller.onCancel = sub.cancel;
  });
});

/// Human text for the remaining time ("12 min", "0:45").
String sleepRemainingLabel(SleepTimerStatus s) {
  switch (s.mode) {
    case SleepTimerMode.off:
      return 'Off';
    case SleepTimerMode.endOfTrack:
      return 'End of song';
    case SleepTimerMode.countdown:
      final total = s.remaining.inSeconds;
      if (total >= 60) return '${(total / 60).ceil()} min';
      return '0:${total.toString().padLeft(2, '0')}';
  }
}

Future<void> showSleepTimerSheet(BuildContext context) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    builder: (_) => const _SleepSheet(),
  );
}

class _SleepSheet extends ConsumerWidget {
  const _SleepSheet();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final facade = ref.watch(playbackFacadeProvider);
    final status = ref.watch(sleepTimerProvider).value ?? facade.sleepTimer;
    final c = context.colors;

    Widget option(String label, VoidCallback onTap, {bool selected = false}) =>
        ListTile(
          title: Text(label),
          trailing:
              selected ? Icon(Icons.check_rounded, color: c.accent) : null,
          onTap: () {
            onTap();
            Navigator.of(context).pop();
          },
        );

    return SafeArea(
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(
                  Space.gutter, Space.lg, Space.gutter, Space.sm),
              child: Text('Sleep timer', style: context.text.titleLarge),
            ),
            if (status.mode != SleepTimerMode.off)
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: Space.gutter),
                child: Text(
                  'Music stops in ${sleepRemainingLabel(status)}.',
                  style: context.text.bodyMedium,
                ),
              ),
            for (final minutes in const [5, 10, 15, 30, 45, 60])
              option(
                '$minutes minutes',
                () =>
                    unawaited(facade.setSleepTimer(Duration(minutes: minutes))),
              ),
            option(
              'End of this song',
              () => unawaited(facade.setSleepAtEndOfTrack(true)),
              selected: status.mode == SleepTimerMode.endOfTrack,
            ),
            if (status.mode != SleepTimerMode.off)
              option('Turn off', () => unawaited(facade.setSleepTimer(null))),
            const SizedBox(height: Space.md),
          ],
        ),
      ),
    );
  }
}
