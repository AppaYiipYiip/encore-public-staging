import 'package:meta/meta.dart';

import 'audio_quality.dart';

/// Why downloads may not start another file.
enum StorageVerdict {
  /// There is room.
  ok,

  /// The user's cap for offline music would be exceeded.
  limitReached,

  /// The phone itself is nearly full; offline music must never be the reason
  /// the camera or the system cannot write.
  lowSpace,
}

/// Decides whether one more file may be downloaded (pure; the manager feeds
/// it numbers). Two independent rules:
///
/// * an optional user cap on the space offline music may use ([limitBytes]);
/// * a floor of free space on the phone that downloads never go below
///   ([minFreeBytes]).
@immutable
class StorageGuard {
  const StorageGuard({
    this.limitBytes,
    this.minFreeBytes = defaultMinFreeBytes,
  });

  /// Keep one GiB free by default.
  static const int defaultMinFreeBytes = 1 << 30;

  /// `null` = no cap.
  final int? limitBytes;
  final int minFreeBytes;

  /// [usedBytes]: finished downloads. [inFlightBytes]: estimated size of
  /// transfers already running. [nextBytes]: estimated size of the file that
  /// would start. [freeBytes]: free space on the phone, `null` if unknown
  /// (then only the cap is enforced).
  StorageVerdict check({
    required int usedBytes,
    required int inFlightBytes,
    required int nextBytes,
    int? freeBytes,
  }) {
    final cap = limitBytes;
    if (cap != null && usedBytes + inFlightBytes + nextBytes > cap) {
      return StorageVerdict.limitReached;
    }
    if (freeBytes != null &&
        freeBytes - inFlightBytes - nextBytes < minFreeBytes) {
      return StorageVerdict.lowSpace;
    }
    return StorageVerdict.ok;
  }
}

/// Rough size of a download, good enough to leave headroom.
///
/// Original files have a known size; a transcode is estimated from its bit
/// rate and the song's length; with neither, 8 MiB (a typical 4-minute
/// 256 kbit/s song).
int estimateDownloadBytes({
  required AudioQuality quality,
  int? sourceSize,
  int? durationSec,
  int? sourceBitRate,
}) {
  const fallback = 8 * 1024 * 1024;
  final cap = quality.bitRate;
  if (quality.isOriginal || cap == null) {
    return sourceSize ?? fallback;
  }
  if (durationSec == null || durationSec <= 0) return fallback;
  // A source already below the cap is downloaded as is.
  final kbit =
      sourceBitRate != null && sourceBitRate < cap ? sourceBitRate : cap;
  return kbit * 125 * durationSec;
}
