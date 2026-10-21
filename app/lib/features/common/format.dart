/// Small formatting helpers shared by screens (pure, tested).
library;

/// `3:07`, `1:02:45`.
String formatClock(Duration d) {
  final total = d.inSeconds < 0 ? 0 : d.inSeconds;
  final h = total ~/ 3600;
  final m = (total % 3600) ~/ 60;
  final s = total % 60;
  final ss = s.toString().padLeft(2, '0');
  if (h > 0) return '$h:${m.toString().padLeft(2, '0')}:$ss';
  return '$m:$ss';
}

/// `12 min`, `1 hr 5 min`, `2 hr`.
String formatTotalDuration(int seconds) {
  if (seconds <= 0) return '';
  final totalMin = (seconds / 60).round();
  if (totalMin < 60) return '$totalMin min';
  final h = totalMin ~/ 60;
  final m = totalMin % 60;
  return m == 0 ? '$h hr' : '$h hr $m min';
}

String plural(int n, String singular, [String? pluralForm]) =>
    '$n ${n == 1 ? singular : (pluralForm ?? '${singular}s')}';

/// "Good morning" / "Good afternoon" / "Good evening" by local hour.
String greetingFor(DateTime now) {
  final h = now.hour;
  if (h >= 5 && h < 12) return 'Good morning';
  if (h >= 12 && h < 18) return 'Good afternoon';
  return 'Good evening';
}

/// Human file-size: `842 KB`, `3.2 MB`, `1.40 GB`.
String formatBytes(int bytes) {
  if (bytes < 1024) return '$bytes B';
  if (bytes < 1024 * 1024) return '${(bytes / 1024).round()} KB';
  if (bytes < 1024 * 1024 * 1024) {
    return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
  }
  return '${(bytes / (1024 * 1024 * 1024)).toStringAsFixed(2)} GB';
}

/// Short "audio quality" label: `FLAC`, `MP3 320`, `Opus 160`.
String qualityLabel({String? suffix, int? bitRate}) {
  final s = (suffix ?? '').toUpperCase();
  if (s.isEmpty) return '';
  const lossless = {'FLAC', 'ALAC', 'WAV', 'AIFF', 'APE', 'WV'};
  if (lossless.contains(s)) return s;
  return bitRate != null && bitRate > 0 ? '$s $bitRate' : s;
}
