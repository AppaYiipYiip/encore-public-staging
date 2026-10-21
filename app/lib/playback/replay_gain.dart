import 'dart:math' as math;

/// Which ReplayGain value to follow.
enum ReplayGainMode { off, track, album }

/// How loud to play a track: attenuation through the player volume (0..1)
/// and, when the track needs *more* than 0 dB, a boost for the platform
/// loudness enhancer.
class GainPlan {
  const GainPlan({required this.volume, this.boostDb = 0});

  /// Linear player volume, 0..1.
  final double volume;

  /// Extra gain in dB for the loudness enhancer (>= 0).
  final double boostDb;

  static const GainPlan unity = GainPlan(volume: 1);

  @override
  String toString() => 'GainPlan(volume: ${volume.toStringAsFixed(3)}, '
      'boost: ${boostDb.toStringAsFixed(1)} dB)';
}

/// Turns ReplayGain tags into a [GainPlan].
///
/// * `track` mode falls back to the album gain (and vice versa) when one of
///   them is missing; untagged tracks get [untaggedDb] so a library with
///   partial tagging does not jump in loudness.
/// * The result never pushes the signal's peak over 0 dBFS: with a known
///   [trackPeak]/[albumPeak] the allowed gain is `-20*log10(peak)`.
/// * Boosts are capped at [maxBoostDb] (loudness enhancers distort fast).
GainPlan planReplayGain({
  required ReplayGainMode mode,
  double? trackGain,
  double? albumGain,
  double? trackPeak,
  double? albumPeak,
  double preampDb = 0,
  double untaggedDb = 0,
  double maxBoostDb = 9,
}) {
  if (mode == ReplayGainMode.off) return GainPlan.unity;

  final useAlbum = mode == ReplayGainMode.album;
  final gain = useAlbum ? (albumGain ?? trackGain) : (trackGain ?? albumGain);
  final peak = useAlbum ? (albumPeak ?? trackPeak) : (trackPeak ?? albumPeak);

  var db = (gain ?? untaggedDb) + preampDb;
  if (peak != null && peak > 0) {
    final headroom = -20 * math.log(peak) / math.ln10;
    if (db > headroom) db = headroom;
  }

  if (db <= 0) {
    return GainPlan(volume: math.pow(10, db / 20).toDouble().clamp(0.0, 1.0));
  }
  return GainPlan(volume: 1, boostDb: math.min(db, maxBoostDb));
}
