/// Estimating the hub's clock from round trips (docs/22 section 3.3).
library;

import 'package:meta/meta.dart';

/// One question to the hub's clock: asked at local time [sentMs], answered at
/// local time [receivedMs], the hub said it was [hubMs].
@immutable
class ClockSample {
  const ClockSample({
    required this.sentMs,
    required this.receivedMs,
    required this.hubMs,
  });

  final int sentMs;
  final int receivedMs;
  final int hubMs;

  int get roundTripMs => receivedMs - sentMs;

  /// "hub time = local time + offset", assuming the answer took half the trip.
  int get offsetMs => hubMs + roundTripMs ~/ 2 - receivedMs;
}

/// Keeps the last few samples and answers "what time is it at the hub?".
///
/// The median of the offsets, after dropping samples whose round trip is much
/// slower than the best one (a slow trip is usually an uneven trip, which is
/// what makes the half-trip assumption wrong).
class ClockEstimator {
  ClockEstimator({this.window = 5, this.minSamples = 3});

  final int window;
  final int minSamples;
  final List<ClockSample> _samples = [];

  int get sampleCount => _samples.length;

  /// Enough samples to trust the estimate.
  bool get isReady => _samples.length >= minSamples;

  void add(ClockSample sample) {
    if (sample.roundTripMs < 0) return; // the local clock went backwards
    _samples.add(sample);
    if (_samples.length > window) _samples.removeAt(0);
  }

  void reset() => _samples.clear();

  /// Local time to hub time.
  int get offsetMs {
    if (_samples.isEmpty) return 0;
    var best = _samples.first.roundTripMs;
    for (final s in _samples) {
      if (s.roundTripMs < best) best = s.roundTripMs;
    }
    final limit = best * 2 + 20;
    final kept = [
      for (final s in _samples)
        if (s.roundTripMs <= limit) s.offsetMs
    ]..sort();
    return kept[kept.length ~/ 2];
  }

  int hubNow(int localNowMs) => localNowMs + offsetMs;
}
