import 'package:meta/meta.dart';

/// One song of a playlist somebody pasted (what `POST /fetch/api/playlist`
/// answers, or a row of a file the person picked).
@immutable
class ImportedTrack {
  const ImportedTrack({
    required this.title,
    required this.artist,
    this.album,
    this.durationSec,
    this.videoId,
    this.official = false,
  });

  factory ImportedTrack.fromJson(Map<String, dynamic> json) => ImportedTrack(
        title: '${json['title'] ?? ''}',
        artist: '${json['artist'] ?? ''}',
        album: json['album'] as String?,
        durationSec: (json['durationSec'] as num?)?.toInt(),
        videoId: json['videoId'] as String?,
        official: json['official'] == true,
      );

  final String title;
  final String artist;
  final String? album;
  final int? durationSec;

  /// The YouTube video a playlist saved: the server uses it only when
  /// searching by name finds nothing.
  final String? videoId;

  /// [videoId] is YouTube's own upload of the song: the server uses it at
  /// once instead of searching.
  final bool official;

  Map<String, Object?> toJson() => {
        'title': title,
        'artist': artist,
        if (album != null && album!.isNotEmpty) 'album': album,
        if (durationSec != null && durationSec! >= 5)
          'durationSec': durationSec,
        if (videoId != null) 'videoId': videoId,
        if (official && videoId != null) 'official': true,
      };
}

/// The list of songs behind a link, read but not yet added to anything.
@immutable
class ImportedPlaylist {
  const ImportedPlaylist({
    required this.name,
    required this.source,
    required this.kind,
    required this.tracks,
    this.truncated = false,
  });

  factory ImportedPlaylist.fromJson(Map<String, dynamic> json) =>
      ImportedPlaylist(
        name: '${json['name'] ?? ''}',
        source: '${json['source'] ?? ''}',
        kind: '${json['kind'] ?? 'playlist'}',
        truncated: json['truncated'] == true,
        tracks: [
          for (final t in (json['tracks'] as List? ?? const []))
            if (t is Map) ImportedTrack.fromJson(t.cast<String, dynamic>()),
        ],
      );

  final String name;

  /// `spotify` or `youtube` (a file says `file`).
  final String source;

  /// `playlist` or `album`.
  final String kind;
  final List<ImportedTrack> tracks;

  /// The list may be longer than what was read (Spotify shows 100 songs of a
  /// link, whatever the length).
  final bool truncated;

  String get sourceName => switch (source) {
        'spotify' => 'Spotify',
        'youtube' => 'YouTube',
        'file' => 'your file',
        _ => 'the link',
      };
}

/// A song an import could not put in the library, and why, in a sentence.
@immutable
class MissingSong {
  const MissingSong({
    required this.title,
    required this.artist,
    required this.reason,
    required this.message,
  });

  factory MissingSong.fromJson(Map<String, dynamic> json) => MissingSong(
        title: '${json['title'] ?? ''}',
        artist: '${json['artist'] ?? ''}',
        reason: '${json['reason'] ?? ''}',
        message: '${json['message'] ?? ''}',
      );

  final String title;
  final String artist;
  final String reason;
  final String message;
}

/// One song of an import and where it is: waiting to be fetched, in the
/// library, or not to be had (with the reason).
@immutable
class ImportSong {
  const ImportSong({
    required this.title,
    required this.artist,
    required this.state,
    this.album,
    this.durationSec,
    this.videoId,
    this.official = false,
    this.reason,
    this.message,
  });

  factory ImportSong.fromJson(Map<String, dynamic> json) => ImportSong(
        title: '${json['title'] ?? ''}',
        artist: '${json['artist'] ?? ''}',
        state: ImportSongState.byName(json['state'] as String?),
        album: json['album'] as String?,
        durationSec: (json['durationSec'] as num?)?.toInt(),
        videoId: json['videoId'] as String?,
        official: json['official'] == true,
        reason: json['reason'] as String?,
        message: json['message'] as String?,
      );

  final String title;
  final String artist;
  final ImportSongState state;
  final String? album;
  final int? durationSec;
  final String? videoId;
  final bool official;
  final String? reason;

  /// Why it is missing, in a sentence.
  final String? message;
}

enum ImportSongState {
  waiting,
  working,
  ready,
  missing;

  static ImportSongState byName(String? name) => values.firstWhere(
        (s) => s.name == name,
        orElse: () => ImportSongState.waiting,
      );
}

enum ImportState {
  running,
  done,
  cancelled,
  failed;

  static ImportState byName(String? name) => values.firstWhere(
        (s) => s.name == name,
        orElse: () => ImportState.running,
      );
}

/// One import as the server reports it (`GET /fetch/api/import/<id>`).
@immutable
class ImportJob {
  const ImportJob({
    required this.id,
    required this.name,
    required this.kind,
    required this.state,
    required this.total,
    required this.done,
    required this.added,
    required this.missing,
    this.skipped = 0,
    this.playlistId,
    this.playlistReady = false,
    this.message,
    this.paused,
    this.pausedMessage,
    this.etaSec,
    this.missingSongs = const [],
    this.songs = const [],
    this.updatedAt,
  });

  factory ImportJob.fromJson(Map<String, dynamic> json) => ImportJob(
        id: '${json['id'] ?? ''}',
        name: '${json['name'] ?? ''}',
        kind: '${json['kind'] ?? 'playlist'}',
        state: ImportState.byName(json['state'] as String?),
        total: (json['total'] as num?)?.toInt() ?? 0,
        done: (json['done'] as num?)?.toInt() ?? 0,
        added: (json['added'] as num?)?.toInt() ?? 0,
        missing: (json['missing'] as num?)?.toInt() ?? 0,
        skipped: (json['skipped'] as num?)?.toInt() ?? 0,
        playlistId: json['playlistId'] as String?,
        playlistReady: json['playlistReady'] == true,
        message: json['message'] as String?,
        paused: json['paused'] as String?,
        pausedMessage: json['pausedMessage'] as String?,
        etaSec: (json['etaSec'] as num?)?.toInt(),
        missingSongs: [
          for (final m in (json['missingSongs'] as List? ?? const []))
            if (m is Map) MissingSong.fromJson(m.cast<String, dynamic>()),
        ],
        songs: [
          for (final s in (json['songs'] as List? ?? const []))
            if (s is Map) ImportSong.fromJson(s.cast<String, dynamic>()),
        ],
        updatedAt: (json['updated'] as num?)?.toDouble(),
      );

  final String id;
  final String name;

  /// `playlist`, or `liked` (every song is liked, no playlist is made).
  final String kind;
  final ImportState state;
  final int total;

  /// Songs settled so far: added or not found.
  final int done;
  final int added;

  /// Songs that could not be had (not the ones the person dropped).
  final int missing;

  /// Songs the person chose not to import.
  final int skipped;

  /// The playlist on the music server (its id), once it exists.
  final String? playlistId;
  final bool playlistReady;
  final String? message;

  /// Why a running import is resting: `waiting_for_app`, `cooling_off`,
  /// `disk_full`; [pausedMessage] says it in words.
  final String? paused;
  final String? pausedMessage;
  final int? etaSec;
  final List<MissingSong> missingSongs;

  /// Every song in the playlist's order with where it is (only when asked for).
  final List<ImportSong> songs;

  /// Seconds since 1970 of the server's last change (for ordering).
  final double? updatedAt;

  bool get isLiked => kind == 'liked';
  bool get isRunning => state == ImportState.running;
  bool get isFinished => !isRunning;

  /// 0..1 for a progress bar.
  double get fraction => total <= 0 ? 0 : (done / total).clamp(0.0, 1.0);

  /// "About 12 minutes left", `null` when nothing useful can be said.
  String? get etaText {
    final eta = etaSec;
    if (!isRunning || eta == null || eta <= 0) return null;
    if (eta < 90) return 'about a minute left';
    final minutes = (eta / 60).round();
    if (minutes < 90) return 'about $minutes minutes left';
    final hours = eta / 3600;
    return 'about ${hours.toStringAsFixed(hours < 10 ? 1 : 0)} hours left';
  }
}

/// What a person sees before agreeing to an import: how long it will take,
/// from what the server measured on 2026-10-18 (10 to 14 seconds a song
/// overall, two at a time). Honest and rounded; the real number comes back from the server
/// once the import has started.
String importEstimate(int songs) {
  final seconds = songs * 12;
  if (seconds < 90) return 'about a minute';
  final minutes = (seconds / 60).round();
  if (minutes < 90) return 'about $minutes minutes';
  final hours = seconds / 3600;
  return 'about ${hours.toStringAsFixed(hours < 10 ? 1 : 0)} hours';
}
