import 'package:meta/meta.dart';

import 'json_read.dart';

/// Typed views of OpenSubsonic responses. Pure Dart, immutable, tolerant.
/// Only the fields the app uses are modelled.

@immutable
class SsArtist {
  const SsArtist({
    required this.id,
    required this.name,
    this.sortName,
    this.coverArt,
    this.albumCount = 0,
    this.musicBrainzId,
    this.imageUrl,
    this.starredAtMs,
  });

  factory SsArtist.fromJson(Map<String, dynamic> j) => SsArtist(
        id: readString(j['id']) ?? '',
        name: readString(j['name']) ?? 'Unknown artist',
        sortName: readString(j['sortName']),
        coverArt: readString(j['coverArt']),
        albumCount: readInt(j['albumCount']) ?? 0,
        musicBrainzId: readString(j['musicBrainzId']),
        imageUrl: readString(j['artistImageUrl']),
        starredAtMs: readDateMs(j['starred']),
      );

  final String id;
  final String name;
  final String? sortName;
  final String? coverArt;
  final int albumCount;
  final String? musicBrainzId;
  final String? imageUrl;
  final int? starredAtMs;
}

@immutable
class SsAlbum {
  const SsAlbum({
    required this.id,
    required this.name,
    this.artistId,
    this.artist,
    this.sortName,
    this.year,
    this.genre,
    this.coverArt,
    this.songCount = 0,
    this.durationSec = 0,
    this.musicBrainzId,
    this.recordLabel,
    this.isCompilation = false,
    this.createdAtMs,
    this.starredAtMs,
    this.userRating,
    this.playCount,
    this.songs = const [],
  });

  factory SsAlbum.fromJson(Map<String, dynamic> j) {
    final labels = readObjectList(j['recordLabels']);
    return SsAlbum(
      id: readString(j['id']) ?? '',
      name: readString(j['name']) ?? readString(j['title']) ?? 'Unknown album',
      artistId: readString(j['artistId']),
      artist: readString(j['displayArtist']) ?? readString(j['artist']),
      sortName: readString(j['sortName']),
      year: readInt(j['year']),
      genre: readString(j['genre']),
      coverArt: readString(j['coverArt']),
      songCount: readInt(j['songCount']) ?? 0,
      durationSec: readInt(j['duration']) ?? 0,
      musicBrainzId: readString(j['musicBrainzId']),
      recordLabel: labels.isEmpty ? null : readString(labels.first['name']),
      isCompilation: readBool(j['isCompilation']),
      createdAtMs: readDateMs(j['created']),
      starredAtMs: readDateMs(j['starred']),
      userRating: readInt(j['userRating']),
      playCount: readInt(j['playCount']),
      songs: [for (final s in readObjectList(j['song'])) SsSong.fromJson(s)],
    );
  }

  final String id;
  final String name;
  final String? artistId;
  final String? artist;
  final String? sortName;
  final int? year;
  final String? genre;
  final String? coverArt;
  final int songCount;
  final int durationSec;
  final String? musicBrainzId;
  final String? recordLabel;
  final bool isCompilation;
  final int? createdAtMs;
  final int? starredAtMs;
  final int? userRating;
  final int? playCount;

  /// Populated by `getAlbum`; empty for list/search results.
  final List<SsSong> songs;
}

@immutable
class SsSong {
  const SsSong({
    required this.id,
    required this.title,
    this.albumId,
    this.artistId,
    this.album,
    this.artist,
    this.trackNo,
    this.discNo,
    this.year,
    this.genre,
    this.coverArt,
    this.durationSec,
    this.size,
    this.suffix,
    this.contentType,
    this.bitRate,
    this.samplingRate,
    this.bitDepth,
    this.channels,
    this.path,
    this.musicBrainzId,
    this.isrc,
    this.rgTrackGain,
    this.rgAlbumGain,
    this.rgTrackPeak,
    this.rgAlbumPeak,
    this.starredAtMs,
    this.userRating,
    this.playCount,
    this.createdAtMs,
  });

  factory SsSong.fromJson(Map<String, dynamic> j) {
    final rg = readMap(j['replayGain']);
    final isrc = readStringList(j['isrc']);
    return SsSong(
      id: readString(j['id']) ?? '',
      title: readString(j['title']) ?? 'Unknown title',
      albumId: readString(j['albumId']) ?? readString(j['parent']),
      artistId: readString(j['artistId']),
      album: readString(j['album']),
      artist: readString(j['displayArtist']) ?? readString(j['artist']),
      trackNo: readInt(j['track']),
      discNo: readInt(j['discNumber']),
      year: readInt(j['year']),
      genre: readString(j['genre']),
      coverArt: readString(j['coverArt']),
      durationSec: readInt(j['duration']),
      size: readInt(j['size']),
      suffix: readString(j['suffix']),
      contentType: readString(j['contentType']),
      bitRate: readInt(j['bitRate']),
      samplingRate: readInt(j['samplingRate']),
      bitDepth: readInt(j['bitDepth']),
      channels: readInt(j['channelCount']),
      path: readString(j['path']),
      musicBrainzId: readString(j['musicBrainzId']),
      isrc: isrc.isEmpty ? null : isrc.first,
      rgTrackGain: readDouble(rg?['trackGain']),
      rgAlbumGain: readDouble(rg?['albumGain']),
      rgTrackPeak: readDouble(rg?['trackPeak']),
      rgAlbumPeak: readDouble(rg?['albumPeak']),
      starredAtMs: readDateMs(j['starred']),
      userRating: readInt(j['userRating']),
      playCount: readInt(j['playCount']),
      createdAtMs: readDateMs(j['created']),
    );
  }

  final String id;
  final String title;
  final String? albumId;
  final String? artistId;
  final String? album;
  final String? artist;
  final int? trackNo;
  final int? discNo;
  final int? year;
  final String? genre;
  final String? coverArt;
  final int? durationSec;
  final int? size;
  final String? suffix;
  final String? contentType;
  final int? bitRate;
  final int? samplingRate;
  final int? bitDepth;
  final int? channels;
  final String? path;
  final String? musicBrainzId;
  final String? isrc;
  final double? rgTrackGain;
  final double? rgAlbumGain;
  final double? rgTrackPeak;
  final double? rgAlbumPeak;
  final int? starredAtMs;
  final int? userRating;
  final int? playCount;
  final int? createdAtMs;
}

@immutable
class SsPlaylist {
  const SsPlaylist({
    required this.id,
    required this.name,
    this.comment,
    this.owner,
    this.isPublic = false,
    this.readonly = false,
    this.validUntilMs,
    this.coverArt,
    this.songCount = 0,
    this.durationSec = 0,
    this.createdAtMs,
    this.changedAtMs,
    this.entries,
  });

  factory SsPlaylist.fromJson(Map<String, dynamic> j) {
    final hasEntries = j.containsKey('entry');
    return SsPlaylist(
      id: readString(j['id']) ?? '',
      name: readString(j['name']) ?? 'Untitled playlist',
      comment: readString(j['comment']),
      owner: readString(j['owner']),
      isPublic: readBool(j['public']),
      readonly: readBool(j['readonly']),
      validUntilMs: readDateMs(j['validUntil']),
      coverArt: readString(j['coverArt']),
      songCount: readInt(j['songCount']) ?? 0,
      durationSec: readInt(j['duration']) ?? 0,
      createdAtMs: readDateMs(j['created']),
      changedAtMs: readDateMs(j['changed']),
      entries: hasEntries
          ? [for (final s in readObjectList(j['entry'])) SsSong.fromJson(s)]
          : null,
    );
  }

  final String id;
  final String name;
  final String? comment;
  final String? owner;
  final bool isPublic;

  /// Server-generated (smart) playlist that the user cannot edit.
  final bool readonly;
  final int? validUntilMs;
  final String? coverArt;
  final int songCount;
  final int durationSec;
  final int? createdAtMs;
  final int? changedAtMs;

  /// `null` when the list endpoint was used (entries not included).
  final List<SsSong>? entries;
}

@immutable
class SsScanStatus {
  const SsScanStatus({
    required this.scanning,
    required this.count,
    this.folderCount,
    this.lastScanMs,
  });

  factory SsScanStatus.fromJson(Map<String, dynamic> j) => SsScanStatus(
        scanning: readBool(j['scanning']),
        count: readInt(j['count']) ?? 0,
        folderCount: readInt(j['folderCount']),
        lastScanMs: readDateMs(j['lastScan']),
      );

  final bool scanning;
  final int count;
  final int? folderCount;
  final int? lastScanMs;
}

@immutable
class SsPing {
  const SsPing({
    required this.apiVersion,
    this.type,
    this.serverVersion,
    this.openSubsonic = false,
  });

  factory SsPing.fromJson(Map<String, dynamic> j) => SsPing(
        apiVersion: readString(j['version']) ?? '',
        type: readString(j['type']),
        serverVersion: readString(j['serverVersion']),
        openSubsonic: readBool(j['openSubsonic']),
      );

  final String apiVersion;
  final String? type;
  final String? serverVersion;
  final bool openSubsonic;

  bool get isNavidrome => (type ?? '').toLowerCase() == 'navidrome';
}

/// One page of a `search3` call.
@immutable
class SsSearchPage {
  const SsSearchPage({
    this.artists = const [],
    this.albums = const [],
    this.songs = const [],
  });

  factory SsSearchPage.fromJson(Map<String, dynamic> j) => SsSearchPage(
        artists: [
          for (final a in readObjectList(j['artist'])) SsArtist.fromJson(a),
        ],
        albums: [
          for (final a in readObjectList(j['album'])) SsAlbum.fromJson(a),
        ],
        songs: [
          for (final s in readObjectList(j['song'])) SsSong.fromJson(s),
        ],
      );

  final List<SsArtist> artists;
  final List<SsAlbum> albums;
  final List<SsSong> songs;
}

@immutable
class SsStarred {
  const SsStarred({
    this.artists = const [],
    this.albums = const [],
    this.songs = const [],
  });

  final List<SsArtist> artists;
  final List<SsAlbum> albums;
  final List<SsSong> songs;
}

/// One line of synced lyrics.
@immutable
class SsLyricLine {
  const SsLyricLine({required this.startMs, required this.text});

  final int startMs;
  final String text;
}

@immutable
class SsLyrics {
  const SsLyrics({required this.lines, required this.synced, this.lang});

  final List<SsLyricLine> lines;
  final bool synced;
  final String? lang;
}
