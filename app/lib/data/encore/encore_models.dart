import 'package:meta/meta.dart';

import '../api/opensubsonic/json_read.dart';

/// What the Encore server says (docs/17). Parsing is tolerant: an odd value is a null, never an exception, so one strange song cannot stop a
/// sync.

/// The server's copy of a song, when it keeps one, with what the music server knows about the file (so the app can show and play it
/// without asking the music server again).
@immutable
class EncoreFile {
  const EncoreFile({
    required this.id,
    required this.navidromeSongId,
    this.codec,
    this.bitrateKbps,
    this.meta = const {},
  });

  factory EncoreFile.fromJson(Map<String, dynamic> json) => EncoreFile(
        id: readString(json['id']) ?? '',
        navidromeSongId: readString(json['navidromeSongId']),
        codec: readString(json['codec']),
        bitrateKbps: readInt(json['bitrateKbps']),
        meta: readMap(json['meta']) ?? const {},
      );

  final String id;

  /// The music server's id of the file: what the stream and download addresses are made of. Null while the music server has not found the file yet.
  final String? navidromeSongId;
  final String? codec;
  final int? bitrateKbps;
  final Map<String, dynamic> meta;

  String? get albumId => readString(meta['albumId']);
  String? get artistId => readString(meta['artistId']);
  String? get coverArt => readString(meta['coverArt']);
  String? get suffix => readString(meta['suffix']);
  String? get contentType => readString(meta['contentType']);
  int? get size => readInt(meta['size']);
  int? get samplingRate => readInt(meta['samplingRate']);
  int? get bitDepth => readInt(meta['bitDepth']);
  int? get channels => readInt(meta['channels']);
  String? get genre => readString(meta['genre']);
  int? get createdAtMs => readDateMs(meta['created']);

  Map<String, dynamic>? get replayGain => readMap(meta['replayGain']);
}

/// One recording (docs/04 section 3): the identity used for likes, playlists, queues and history, owned or not.
@immutable
class EncoreRef {
  const EncoreRef({
    required this.id,
    required this.title,
    required this.artists,
    this.album,
    this.albumArtist,
    this.trackNo,
    this.discNo,
    this.year,
    this.durationMs,
    this.isrc,
    this.mbid,
    this.deezerId,
    this.videoId,
    this.coverUrl,
    this.explicit = false,
    this.file,
  });

  factory EncoreRef.fromJson(Map<String, dynamic> json) {
    final artists = [
      for (final a in (json['artists'] as List? ?? const []))
        if (readString(a) != null) readString(a)!,
    ];
    final file = readMap(json['file']);
    return EncoreRef(
      id: readString(json['id']) ?? '',
      title: readString(json['title']) ?? '',
      artists: artists,
      album: readString(json['album']),
      albumArtist: readString(json['albumArtist']),
      trackNo: readInt(json['trackNo']),
      discNo: readInt(json['discNo']),
      year: readInt(json['year']),
      durationMs: readInt(json['durationMs']),
      isrc: readString(json['isrc']),
      mbid: readString(json['mbid']),
      deezerId: readString(json['deezerId']),
      videoId: readString(json['videoId']),
      coverUrl: readString(json['coverUrl']),
      explicit: readBool(json['explicit']),
      file: file == null ? null : EncoreFile.fromJson(file),
    );
  }

  final String id;
  final String title;
  final List<String> artists;
  final String? album;
  final String? albumArtist;
  final int? trackNo;
  final int? discNo;
  final int? year;
  final int? durationMs;
  final String? isrc;
  final String? mbid;
  final String? deezerId;
  final String? videoId;
  final String? coverUrl;
  final bool explicit;
  final EncoreFile? file;

  String get artist => artists.isEmpty ? '' : artists.first;
  int? get durationSec =>
      durationMs == null ? null : (durationMs! / 1000).round();
}

@immutable
class EncoreLike {
  const EncoreLike(
      {required this.ref, required this.atMs, required this.removed});

  factory EncoreLike.fromJson(Map<String, dynamic> json) => EncoreLike(
        ref: readString(json['ref']) ?? '',
        atMs: readInt(json['at']),
        removed: readBool(json['removed']),
      );

  final String ref;
  final int? atMs;
  final bool removed;
}

/// A saved album or a followed artist.
@immutable
class EncoreSetItem {
  const EncoreSetItem(
      {required this.id, required this.atMs, required this.removed});

  factory EncoreSetItem.fromJson(Map<String, dynamic> json) => EncoreSetItem(
        id: readString(json['id']) ?? '',
        atMs: readInt(json['at']),
        removed: readBool(json['removed']),
      );

  final String id;
  final int? atMs;
  final bool removed;
}

@immutable
class EncorePlaylist {
  const EncorePlaylist({
    required this.id,
    required this.name,
    this.cover,
    this.collaborative = false,
    this.createdAtMs,
    this.updatedAtMs,
    this.deleted = false,
    this.entries = const [],
  });

  factory EncorePlaylist.fromJson(Map<String, dynamic> json) => EncorePlaylist(
        id: readString(json['id']) ?? '',
        name: readString(json['name']) ?? '',
        cover: readString(json['cover']),
        collaborative: readBool(json['collaborative']),
        createdAtMs: readInt(json['createdAt']),
        updatedAtMs: readInt(json['updatedAt']),
        deleted: readBool(json['deleted']),
        entries: [
          for (final e in readObjectList(json['entries']))
            EncoreEntry.fromJson(e)
        ],
      );

  final String id;
  final String name;
  final String? cover;
  final bool collaborative;
  final int? createdAtMs;
  final int? updatedAtMs;
  final bool deleted;
  final List<EncoreEntry> entries;
}

@immutable
class EncoreEntry {
  const EncoreEntry({
    required this.id,
    required this.playlist,
    required this.ref,
    required this.position,
    this.addedAtMs,
    this.deleted = false,
  });

  factory EncoreEntry.fromJson(Map<String, dynamic> json) => EncoreEntry(
        id: readString(json['id']) ?? '',
        playlist: readString(json['playlist']) ?? '',
        ref: readString(json['ref']) ?? '',
        position: readDouble(json['position']) ?? 0,
        addedAtMs: readInt(json['addedAt']),
        deleted: readBool(json['deleted']),
      );

  final String id;
  final String playlist;
  final String ref;

  /// Fractional (docs/17 section 5): two devices' moves merge. Only the order matters.
  final double position;
  final int? addedAtMs;
  final bool deleted;
}

/// What changed for this person after a cursor, as the state it is in now.
@immutable
class EncoreChanges {
  const EncoreChanges({
    required this.refs,
    required this.likes,
    required this.savedAlbums,
    required this.follows,
    required this.playlists,
    required this.entries,
    required this.cursor,
    required this.more,
  });

  factory EncoreChanges.fromJson(Map<String, dynamic> json) => EncoreChanges(
        refs: [
          for (final r in readObjectList(json['refs'])) EncoreRef.fromJson(r)
        ],
        likes: [
          for (final r in readObjectList(json['likes'])) EncoreLike.fromJson(r)
        ],
        savedAlbums: [
          for (final r in readObjectList(json['savedAlbums']))
            EncoreSetItem.fromJson(r)
        ],
        follows: [
          for (final r in readObjectList(json['follows']))
            EncoreSetItem.fromJson(r)
        ],
        playlists: [
          for (final r in readObjectList(json['playlists']))
            EncorePlaylist.fromJson(r)
        ],
        entries: [
          for (final r in readObjectList(json['entries']))
            EncoreEntry.fromJson(r)
        ],
        cursor: readString(json['cursor']) ?? '0',
        more: readBool(json['more']),
      );

  final List<EncoreRef> refs;
  final List<EncoreLike> likes;
  final List<EncoreSetItem> savedAlbums;
  final List<EncoreSetItem> follows;
  final List<EncorePlaylist> playlists;
  final List<EncoreEntry> entries;
  final String cursor;
  final bool more;
}

/// The songs whose file changed (the browse index of what the server keeps).
@immutable
class EncoreFiles {
  const EncoreFiles(
      {required this.refs, required this.cursor, required this.more});

  factory EncoreFiles.fromJson(Map<String, dynamic> json) => EncoreFiles(
        refs: [
          for (final r in readObjectList(json['refs'])) EncoreRef.fromJson(r)
        ],
        cursor: readString(json['cursor']) ?? '0',
        more: readBool(json['more']),
      );

  final List<EncoreRef> refs;
  final String cursor;
  final bool more;
}

/// `GET /encore/api/v1/info`: what this server is and can do.
@immutable
class EncoreInfo {
  const EncoreInfo({
    required this.apiVersion,
    required this.minAppVersion,
    required this.serverVersion,
    required this.name,
    required this.features,
    this.youtubeState = 'off',
    this.youtubeResumesInSec = 0,
  });

  factory EncoreInfo.fromJson(Map<String, dynamic> json) {
    final youtube = readMap(json['youtube']);
    return EncoreInfo(
      apiVersion: readString(json['apiVersion']) ?? '',
      minAppVersion: readString(json['minAppVersion']) ?? '',
      serverVersion: readString(json['serverVersion']) ?? '',
      name: readString(json['name']) ?? '',
      features: {
        for (final f in (json['features'] as List? ?? const [])) f.toString()
      },
      youtubeState: readString(youtube?['state']) ?? 'off',
      youtubeResumesInSec: readInt(youtube?['resumesInSec']) ?? 0,
    );
  }

  final String apiVersion;
  final String minAppVersion;
  final String serverVersion;
  final String name;
  final Set<String> features;

  /// `ok`, `resting` (YouTube refused this server's address; songs not yet kept may not start for a while) or `off`.
  final String youtubeState;
  final int youtubeResumesInSec;

  bool get hasRefs => features.contains('refs');
}

/// The device token a sign-in returns (the live channel authenticates with it).
@immutable
class EncoreDeviceLogin {
  const EncoreDeviceLogin(
      {required this.deviceToken,
      required this.deviceId,
      required this.personId});

  factory EncoreDeviceLogin.fromJson(Map<String, dynamic> json) =>
      EncoreDeviceLogin(
        deviceToken: readString(json['deviceToken']) ?? '',
        deviceId: readString(readMap(json['device'])?['id']) ?? '',
        personId: readString(readMap(json['person'])?['id']) ?? '',
      );

  final String deviceToken;
  final String deviceId;
  final String personId;
}
