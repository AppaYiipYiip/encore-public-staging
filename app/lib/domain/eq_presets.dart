import 'dart:math' as math;

/// A named equaliser curve defined at five reference frequencies, so it can
/// be applied to whatever bands a device exposes (5 on most phones, 10 on
/// some) by interpolating on a log-frequency axis.
class EqPreset {
  const EqPreset(this.id, this.label, this.gains);

  final String id;
  final String label;

  /// dB at [referenceHz].
  final List<double> gains;

  static const List<double> referenceHz = [60, 230, 910, 3600, 14000];

  static const flat = EqPreset('flat', 'Flat', [0, 0, 0, 0, 0]);

  static const all = <EqPreset>[
    flat,
    EqPreset('bass_boost', 'Bass boost', [6, 4, 0, 0, 0]),
    EqPreset('bass_reduce', 'Bass reducer', [-6, -3, 0, 0, 0]),
    EqPreset('treble_boost', 'Treble boost', [0, 0, 0, 3, 6]),
    EqPreset('vocal', 'Vocal', [-3, -1, 2, 4, 1]),
    EqPreset('rock', 'Rock', [4, 2, -2, 2, 4]),
    EqPreset('metal', 'Metal', [3, 1, -3, 3, 4]),
    EqPreset('pop', 'Pop', [-1, 2, 4, 2, -1]),
    EqPreset('electronic', 'Electronic', [4, 2, 0, 2, 5]),
    EqPreset('hiphop', 'Hip-hop', [5, 3, 0, 1, 3]),
    EqPreset('acoustic', 'Acoustic', [3, 2, 1, 2, 2]),
    EqPreset('classical', 'Classical', [3, 2, -1, 2, 3]),
    EqPreset('late_night', 'Late night', [-2, 0, 2, 1, -3]),
  ];

  static EqPreset? byId(String? id) {
    for (final p in all) {
      if (p.id == id) return p;
    }
    return null;
  }

  /// Gain for each device band centre (Hz), clamped to [min, max] dB.
  List<double> forBands(
    List<double> centreHz, {
    double min = -15,
    double max = 15,
  }) {
    double at(double hz) {
      final x = math.log(hz.clamp(referenceHz.first, referenceHz.last));
      for (var i = 0; i < referenceHz.length - 1; i++) {
        final a = math.log(referenceHz[i]);
        final b = math.log(referenceHz[i + 1]);
        if (x <= b) {
          final t = b == a ? 0.0 : (x - a) / (b - a);
          return gains[i] + (gains[i + 1] - gains[i]) * t;
        }
      }
      return gains.last;
    }

    return [for (final hz in centreHz) at(hz).clamp(min, max)];
  }
}

/// "60 Hz" / "3.6 kHz" labels for band sliders.
String formatHz(double hz) {
  if (hz >= 1000) {
    final k = hz / 1000;
    return '${k.toStringAsFixed(k >= 10 || k == k.roundToDouble() ? 0 : 1)} kHz';
  }
  return '${hz.round()} Hz';
}
