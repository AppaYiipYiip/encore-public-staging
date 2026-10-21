/// Keeping a player aligned with the hub's clock (docs/22 section 3.3).
library;

import 'dart:math' as math;

import 'package:meta/meta.dart';

/// What the player should do about being early or late.
@immutable
sealed class DriftAction {
  const DriftAction();
}

/// Close enough; leave it.
class Hold extends DriftAction {
  const Hold();
}

/// Far off: jump to [targetMs].
class SeekTo extends DriftAction {
  const SeekTo(this.targetMs);
  final int targetMs;
}

/// Slightly off: play at [speed] (1.0 = normal) until it catches up.
class SetSpeed extends DriftAction {
  const SetSpeed(this.speed);
  final double speed;
}

/// Decides, every couple of seconds, how to bring a player back to the hub's
/// position without an audible jump.
class DriftController {
  const DriftController({
    this.seekAboveMs = 250,
    this.nudgeAboveMs = 40,
    this.settleBelowMs = 15,
    this.maxNudge = 0.02,
  });

  /// More than this off: seek.
  final int seekAboveMs;

  /// More than this off: change speed a little.
  final int nudgeAboveMs;

  /// Back within this: return to normal speed.
  final int settleBelowMs;

  /// The largest speed change, as a fraction (0.02 = 2 %).
  final double maxNudge;

  /// [playerMs] is where the player is, [targetMs] where the hub says it
  /// should be, [speed] what the player is doing now.
  DriftAction decide({
    required int playerMs,
    required int targetMs,
    required double speed,
  }) {
    final error = playerMs - targetMs; // positive: the player is ahead
    final size = error.abs();
    if (size > seekAboveMs) return SeekTo(targetMs);
    if (size > nudgeAboveMs) {
      final change = math.min(maxNudge, size / 5000);
      final next = error > 0 ? 1.0 - change : 1.0 + change;
      return (next - speed).abs() < 0.0005 ? const Hold() : SetSpeed(next);
    }
    if (size < settleBelowMs && (speed - 1.0).abs() > 0.0005) {
      return const SetSpeed(1.0);
    }
    return const Hold();
  }
}
