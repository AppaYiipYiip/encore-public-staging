import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../design/tokens.dart';
import '../common/format.dart';
import '../providers.dart';

/// Seek bar + times. Position comes from its own stream so the rest of the
/// screen does not rebuild four times a second.
class Scrubber extends ConsumerStatefulWidget {
  const Scrubber({super.key});

  @override
  ConsumerState<Scrubber> createState() => _ScrubberState();
}

class _ScrubberState extends ConsumerState<Scrubber> {
  double? _dragValue;

  @override
  Widget build(BuildContext context) {
    final facade = ref.watch(playbackFacadeProvider);
    final snapshot = ref.watch(playbackSnapshotProvider).value;
    final position = ref.watch(playbackPositionProvider).value ?? Duration.zero;
    final total = snapshot?.duration ?? Duration.zero;
    final maxMs = math.max(1.0, total.inMilliseconds.toDouble());
    final value =
        (_dragValue ?? position.inMilliseconds.toDouble()).clamp(0.0, maxMs);
    final shown = Duration(milliseconds: value.round());

    return Column(
      children: [
        Semantics(
          label: 'Seek',
          value: '${formatClock(shown)} of ${formatClock(total)}',
          child: SliderTheme(
            data: SliderTheme.of(context).copyWith(trackHeight: 4),
            child: Slider(
              value: value,
              max: maxMs,
              onChanged: (v) => setState(() => _dragValue = v),
              onChangeEnd: (v) {
                setState(() => _dragValue = null);
                facade.seek(Duration(milliseconds: v.round()));
              },
            ),
          ),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: Space.lg),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(formatClock(shown), style: context.text.bodySmall),
              Text(formatClock(total), style: context.text.bodySmall),
            ],
          ),
        ),
      ],
    );
  }
}
