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
    this.sourceId,
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
        sourceId: readString(json['sourceId']),
      );

  final String id;
  final String name;

  /// Where the playlist came from (`nd:<the music server's playlist id>` for one brought over from it).
  final String? sourceId;
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

/// One address the server says it can be reached at (`GET /encore/api/v1/server`): `home` (on the home network) or `away` (over the internet).
class EncoreAddress {
  const EncoreAddress({required this.kind, required this.url});

  final String kind;
  final Uri url;
}

/// What a signed-in phone is told about its server (docs/11 ADR-R40): who it is and the addresses it has, so nobody types one.
class EncoreServerAddresses {
  const EncoreServerAddresses(
      {required this.serverId, required this.name, required this.addresses});

  factory EncoreServerAddresses.fromJson(Map<String, dynamic> json) =>
      EncoreServerAddresses(
        serverId: readString(json['serverId']),
        name: readString(json['name']) ?? '',
        addresses: [
          for (final a in (json['addresses'] as List? ?? const []))
            if (a is Map &&
                readString(a['url']) != null &&
                Uri.tryParse(readString(a['url'])!) != null)
              EncoreAddress(
                kind: readString(a['kind']) ?? '',
                url: Uri.parse(readString(a['url'])!),
              ),
        ],
      );

  final String? serverId;
  final String name;
  final List<EncoreAddress> addresses;
}

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

/// What bringing a person's library over from the music server did on the Encore server.
@immutable
class EncoreMigrationReport {
  const EncoreMigrationReport({
    this.likes = 0,
    this.albums = 0,
    this.artists = 0,
    this.playlists = 0,
    this.entries = 0,
    this.unmatched = 0,
  });

  factory EncoreMigrationReport.fromJson(Map<String, dynamic> json) =>
      EncoreMigrationReport(
        likes: readInt(json['likes']) ?? 0,
        albums: readInt(json['albums']) ?? 0,
        artists: readInt(json['artists']) ?? 0,
        playlists: readInt(json['playlists']) ?? 0,
        entries: readInt(json['entries']) ?? 0,
        unmatched: readInt(json['unmatched']) ?? 0,
      );

  final int likes;
  final int albums;
  final int artists;
  final int playlists;
  final int entries;
  final int unmatched;
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

/// `GET /me`: who this person is on the server.
@immutable
class EncoreMe {
  const EncoreMe({
    required this.id,
    required this.name,
    required this.username,
    required this.role,
  });

  factory EncoreMe.fromJson(Map<String, dynamic> json) => EncoreMe(
        id: readString(json['id']) ?? '',
        name: readString(json['name']) ?? '',
        username: readString(json['username']) ?? '',
        role: readString(json['role']) ?? 'member',
      );

  final String id;
  final String name;
  final String username;

  /// `owner` or `member`.
  final String role;

  bool get isOwner => role == 'owner';
}

/// One invitation. [code] is set only on the answer to making it: the server keeps a hash and never says it again.
@immutable
class EncoreInvite {
  const EncoreInvite({
    required this.id,
    required this.role,
    required this.createdAtMs,
    required this.expiresAtMs,
    this.code,
    this.note,
    this.state = 'open',
    this.usedBy,
    this.usedAtMs,
  });

  factory EncoreInvite.fromJson(Map<String, dynamic> json) => EncoreInvite(
        id: readString(json['id']) ?? '',
        role: readString(json['role']) ?? 'member',
        createdAtMs: readInt(json['createdAt']) ?? 0,
        expiresAtMs: readInt(json['expiresAt']) ?? 0,
        code: readString(json['code']),
        note: readString(json['note']),
        state: readString(json['state']) ?? 'open',
        usedBy: readString(json['usedBy']),
        usedAtMs: readInt(json['usedAt']),
      );

  final String id;
  final String role;
  final int createdAtMs;
  final int expiresAtMs;
  final String? code;
  final String? note;

  /// `open`, `used`, `expired` or `revoked`.
  final String state;
  final String? usedBy;
  final int? usedAtMs;
}

/// One person on the server, as an owner sees them: counts and dates only, never what anybody listens to.
@immutable
class EncorePerson {
  const EncorePerson({
    required this.id,
    required this.username,
    required this.name,
    required this.role,
    required this.createdAtMs,
    this.locked = false,
    this.invitedBy,
    this.devices = 0,
    this.lastSeenMs,
  });

  factory EncorePerson.fromJson(Map<String, dynamic> json) => EncorePerson(
        id: readString(json['id']) ?? '',
        username: readString(json['username']) ?? '',
        name: readString(json['name']) ?? '',
        role: readString(json['role']) ?? 'member',
        createdAtMs: readInt(json['createdAt']) ?? 0,
        locked: readBool(json['locked']),
        invitedBy: readString(json['invitedBy']),
        devices: readInt(json['devices']) ?? 0,
        lastSeenMs: readInt(json['lastSeen']),
      );

  final String id;
  final String username;
  final String name;
  final String role;
  final int createdAtMs;
  final bool locked;
  final String? invitedBy;
  final int devices;
  final int? lastSeenMs;
}

/// One import as the server counts it: every number comes from the server and from nowhere else.
@immutable
class EncoreImport {
  const EncoreImport({
    required this.id,
    required this.name,
    required this.source,
    required this.state,
    required this.total,
    required this.matched,
    required this.unmatched,
    required this.pending,
    required this.kept,
    this.playlistId,
    this.truncated = false,
    this.createdAtMs = 0,
  });

  factory EncoreImport.fromJson(Map<String, dynamic> json) => EncoreImport(
        id: readString(json['id']) ?? '',
        name: readString(json['name']) ?? '',
        source: readString(json['source']) ?? '',
        state: readString(json['state']) ?? 'running',
        total: readInt(json['total']) ?? 0,
        matched: readInt(json['matched']) ?? 0,
        unmatched: readInt(json['unmatched']) ?? 0,
        pending: readInt(json['pending']) ?? 0,
        kept: readInt(json['kept']) ?? 0,
        playlistId: readString(json['playlistId']),
        truncated: readBool(json['truncated']),
        createdAtMs: readInt(json['createdAt']) ?? 0,
      );

  final String id;
  final String name;

  /// `youtube`, `spotify` or `file`.
  final String source;

  /// `running`, `done`, `stopped` or `failed`.
  final String state;
  final int total;

  /// Songs found, songs not found, songs not looked at yet.
  final int matched;
  final int unmatched;
  final int pending;

  /// Songs the server has a copy of by now.
  final int kept;

  /// `null` for a list that was liked instead of made a playlist.
  final String? playlistId;

  /// The list was longer than what could be read.
  final bool truncated;
  final int createdAtMs;

  bool get isRunning => state == 'running';
}

/// The answer to starting an import: the import, and the playlist it made.
@immutable
class EncoreImportMade {
  const EncoreImportMade({required this.import, this.playlistId});

  factory EncoreImportMade.fromJson(Map<String, dynamic> json) =>
      EncoreImportMade(
        import: EncoreImport.fromJson(readMap(json['import']) ?? const {}),
        playlistId: readString(json['playlistId']),
      );

  final EncoreImport import;
  final String? playlistId;
}

/// The four kinds of news the bell has and no others (docs/design S-24, ADR-R44): a release from an artist the person plays, a Jam
/// invitation, an invitation of theirs that was used, an import that finished.
enum EncoreNewsKind {
  release('release'),
  jam('jam'),
  inviteUsed('invite_used'),
  importDone('import_done');

  const EncoreNewsKind(this.wire);

  /// The word the server uses.
  final String wire;

  static EncoreNewsKind? fromWire(String? word) {
    for (final kind in values) {
      if (kind.wire == word) return kind;
    }
    return null;
  }
}

/// One piece of news, written by the server in words (so every client shows the same).
@immutable
class EncoreNews {
  const EncoreNews({
    required this.id,
    required this.kind,
    required this.title,
    this.body,
    this.route,
    required this.createdAtMs,
    required this.read,
  });

  /// `null` for a kind this app does not know (a newer server): such news is left out, not shown wrongly.
  static EncoreNews? fromJson(Map<String, dynamic> json) {
    final kind = EncoreNewsKind.fromWire(readString(json['kind']));
    final id = readInt(json['id']);
    final title = readString(json['title']);
    if (kind == null || id == null || title == null) return null;
    return EncoreNews(
      id: id,
      kind: kind,
      title: title,
      body: readString(json['body']),
      route: readString(json['route']),
      createdAtMs: readInt(json['createdAt']) ?? 0,
      read: readBool(json['read']),
    );
  }

  final int id;
  final EncoreNewsKind kind;
  final String title;
  final String? body;

  /// Where a tap goes in the app (`/settings/import`), when it goes anywhere.
  final String? route;
  final int createdAtMs;
  final bool read;

  EncoreNews asRead() => EncoreNews(
        id: id,
        kind: kind,
        title: title,
        body: body,
        route: route,
        createdAtMs: createdAtMs,
        read: true,
      );
}

/// The bell's list, newest first, with how many are unread in all and the cursor to ask "only what is newer" with.
@immutable
class EncoreNewsList {
  const EncoreNewsList(
      {required this.items, required this.unread, required this.cursor});

  factory EncoreNewsList.fromJson(Map<String, dynamic> json) => EncoreNewsList(
        items: [
          for (final r in readObjectList(json['items']))
            if (EncoreNews.fromJson(r) case final news?) news
        ],
        unread: readInt(json['unread']) ?? 0,
        cursor: readString(json['cursor']) ?? '0',
      );

  final List<EncoreNews> items;
  final int unread;
  final String cursor;
}

/// How the server is getting one song of a saved release (`GET refs/{id}/keep`, and the answer to saving a release): `queued`, `keeping`,
/// `kept`, `failed`, `none` or `unavailable` (a server that does not keep songs).
@immutable
class EncoreKeep {
  const EncoreKeep(this.state, {this.reason});

  factory EncoreKeep.fromJson(Map<String, dynamic> json) => EncoreKeep(
        readString(json['state']) ?? 'none',
        reason: readString(json['reason']),
      );

  final String state;

  /// A sentence for a person when [state] is `failed` or `unavailable`.
  final String? reason;

  bool get isKept => state == 'kept';
  bool get isFailed => state == 'failed' || state == 'unavailable';
}

/// The answer to saving a release (`PUT saved-albums/{id}` with the songs, docs/17 "Saving a release"): whether the save was new, and how
/// the server goes about each song.
@immutable
class EncoreReleaseSave {
  const EncoreReleaseSave({required this.changed, required this.keep});

  factory EncoreReleaseSave.fromJson(Map<String, dynamic> json) {
    final keep = <String, EncoreKeep>{};
    final raw = readMap(json['keep']);
    if (raw != null) {
      for (final entry in raw.entries) {
        final one = readMap(entry.value);
        if (one != null) keep[entry.key] = EncoreKeep.fromJson(one);
      }
    }
    return EncoreReleaseSave(
        changed: readBool(json['changed']), keep: Map.unmodifiable(keep));
  }

  final bool changed;

  /// By song id.
  final Map<String, EncoreKeep> keep;
}
