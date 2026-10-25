import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../design/tokens.dart';
import '../common/format.dart';
import '../providers.dart';

/// Seek bar + times. Position comes from its own stream so the rest of the
/// screen does not rebuild four times a second.
class Scrubber extends ConsumerStatefulWidget {
  const Scrubber({super.key, this.waiting = false});

  /// The song is waiting for its server (docs/33 PB-F7, docs/design/03 row 9): the part still to play is dashed, in the warning colour, and
  /// the thumb is hollow, so a waiting song is told apart from a playing one by shape and not by colour alone.
  final bool waiting;

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
            data: widget.waiting
                ? SliderTheme.of(context).copyWith(
                    trackHeight: 4,
                    trackShape: _DashedTrack(context.colors.warning),
                    thumbShape: _HollowThumb(context.colors.warning),
                    activeTrackColor: context.colors.warning,
                  )
                : SliderTheme.of(context).copyWith(trackHeight: 4),
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

/// The seek bar of a waiting song: the played part solid, the rest dashed.
class _DashedTrack extends RoundedRectSliderTrackShape {
  const _DashedTrack(this.colour);

  final Color colour;

  @override
  void paint(
    PaintingContext context,
    Offset offset, {
    required RenderBox parentBox,
    required SliderThemeData sliderTheme,
    required Animation<double> enableAnimation,
    required TextDirection textDirection,
    required Offset thumbCenter,
    Offset? secondaryOffset,
    bool isDiscrete = false,
    bool isEnabled = false,
    double additionalActiveTrackHeight = 2,
  }) {
    final rect = getPreferredRect(
        parentBox: parentBox,
        offset: offset,
        sliderTheme: sliderTheme,
        isEnabled: isEnabled,
        isDiscrete: isDiscrete);
    final canvas = context.canvas;
    final played = Paint()..color = colour;
    final dash = Paint()..color = colour.withValues(alpha: 0.9);
    final rtl = textDirection == TextDirection.rtl;
    final start = rtl ? thumbCenter.dx : rect.left;
    final end = rtl ? rect.right : thumbCenter.dx;
    canvas.drawRRect(
        RRect.fromLTRBR(
            rtl ? thumbCenter.dx : rect.left,
            rect.top,
            rtl ? rect.right : thumbCenter.dx,
            rect.bottom,
            Radius.circular(rect.height / 2)),
        played);
    // The rest, in dashes 6 wide with 5 between.
    final from = rtl ? rect.left : end;
    final to = rtl ? start : rect.right;
    for (var x = from; x < to; x += 11) {
      canvas.drawRRect(
          RRect.fromLTRBR(x, rect.top, (x + 6).clamp(from, to), rect.bottom,
              Radius.circular(rect.height / 2)),
          dash);
    }
  }
}

/// A ring instead of a dot: nothing is being heard.
class _HollowThumb extends SliderComponentShape {
  const _HollowThumb(this.colour);

  final Color colour;

  @override
  Size getPreferredSize(bool isEnabled, bool isDiscrete) => const Size(18, 18);

  @override
  void paint(
    PaintingContext context,
    Offset center, {
    required Animation<double> activationAnimation,
    required Animation<double> enableAnimation,
    required bool isDiscrete,
    required TextPainter labelPainter,
    required RenderBox parentBox,
    required SliderThemeData sliderTheme,
    required TextDirection textDirection,
    required double value,
    required double textScaleFactor,
    required Size sizeWithOverflow,
  }) {
    context.canvas.drawCircle(
        center,
        7,
        Paint()
          ..color = colour
          ..style = PaintingStyle.stroke
          ..strokeWidth = 2.5);
  }
}
