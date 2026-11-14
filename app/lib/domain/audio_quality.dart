/// Audio quality policies for streaming and downloads (ADR-036).
///
/// A policy is just `(container format, max bit rate)` handed to the server's
/// transcoder (`stream?format=&maxBitRate=`), or "original" which asks for the
/// untouched file. The same ids are stored in `Pins.quality` /
/// `Downloads.quality` and in settings, so they must stay stable.
enum AudioQuality {
  original(
    id: 'original',
    label: 'Original',
    detail: 'Untouched file from your server (FLAC stays FLAC)',
    format: null,
    bitRate: null,
    rank: 100,
  ),
  high(
    id: 'opus160',
    label: 'High',
    detail: 'Opus 160 kbps - transparent for most listening',
    format: 'opus',
    bitRate: 160,
    rank: 80,
  ),
  normal(
    id: 'opus96',
    label: 'Normal',
    detail: 'Opus 96 kbps - great on headphones, small files',
    format: 'opus',
    bitRate: 96,
    rank: 60,
  ),
  dataSaver(
    id: 'opus48',
    label: 'Data saver',
    detail: 'Opus 48 kbps - for slow or metered connections',
    format: 'opus',
    bitRate: 48,
    rank: 40,
  ),
  compatible(
    id: 'mp3_192',
    label: 'Compatible',
    detail: 'MP3 192 kbps - plays everywhere',
    format: 'mp3',
    bitRate: 192,
    rank: 70,
  );

  const AudioQuality({
    required this.id,
    required this.label,
    required this.detail,
    required this.format,
    required this.bitRate,
    required this.rank,
  });

  /// Stable identifier persisted in the database and settings.
  final String id;
  final String label;
  final String detail;

  /// Target container/codec for the server transcoder; `null` = original.
  final String? format;

  /// Target bit rate in kbps; `null` = original.
  final int? bitRate;

  /// Higher = better. Used when several pins want the same track.
  final int rank;

  bool get isOriginal => format == null;

  /// What Data saver holds this choice to while it is in force (P4-24): the person's own choice is not changed, only held below
  /// [dataSaver] for as long as the phone is on mobile data with the switch on.
  ///
  /// The cap never changes the codec. Original is the untouched file and has no codec of its own, so Data saver is its cap. Any other level
  /// goes down to the lowest level of its own codec that exists in this list (Opus 160 and 96 go to Opus 48). A codec with nothing below
  /// the level chosen (Compatible: the only MP3 level is 192 kbps) is not capped at all: a car or an old phone that needs MP3 is never
  /// handed Opus, and no level is invented here (the Settings line says it).
  AudioQuality cappedForDataSaver() {
    if (isOriginal) return dataSaver;
    var lowest = this;
    for (final q in values) {
      if (q.format == format && q.bitRate! < lowest.bitRate!) lowest = q;
    }
    return lowest;
  }

  /// Whether [cappedForDataSaver] changes anything, which is when Settings may say that Data saver is limiting this choice.
  bool get isLoweredByDataSaver => cappedForDataSaver() != this;

  static AudioQuality byId(String? id, {AudioQuality fallback = original}) {
    for (final q in values) {
      if (q.id == id) return q;
    }
    return fallback;
  }

  /// The higher quality of [a] and [b] (a track pinned twice keeps the best).
  static AudioQuality best(AudioQuality a, AudioQuality b) =>
      a.rank >= b.rank ? a : b;

  /// File extension for a download made with this policy.
  String fileExtension({String? sourceSuffix}) {
    final f = format ?? sourceSuffix;
    if (f == null || f.isEmpty) return 'audio';
    return f == 'opus' ? 'opus' : f;
  }

  /// Rough size of a downloaded track, for storage estimates before the
  /// download starts. Exact bytes are recorded once the file exists.
  int estimateBytes({required int? durationSec, required int? sourceBytes}) {
    final rate = bitRate;
    if (rate == null) return sourceBytes ?? ((durationSec ?? 240) * 40 * 1000);
    final seconds = durationSec ?? 240;
    final estimate = seconds * rate * 1000 ~/ 8;
    // A transcode never grows beyond the original it came from.
    if (sourceBytes != null && sourceBytes > 0 && estimate > sourceBytes) {
      return sourceBytes;
    }
    return estimate;
  }
}
