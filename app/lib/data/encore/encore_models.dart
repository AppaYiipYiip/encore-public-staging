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

/// What the server already knows about a song it cannot get (N-13, docs/17 "Songs the server cannot get"): a "no" the source answered, remembered for a
/// window. It comes on a ref (`unavailable`) and from `POST refs/unavailable`. Optional everywhere: an older server never sends it, and then nothing is
/// marked.
@immutable
class EncoreUnavailable {
  const EncoreUnavailable({
    required this.reason,
    required this.message,
    required this.retryAfter,
  });

  /// `null` when the object is not a memory of a refusal (a missing or odd value), never an exception.
  static EncoreUnavailable? fromJson(Object? raw) {
    final json = readMap(raw);
    if (json == null) return null;
    final reason = readString(json['reason']);
    final retryAfterMs = readInt(json['retryAfter']);
    if (reason == null || retryAfterMs == null) return null;
    return EncoreUnavailable(
      reason: reason,
      message: readString(json['message']) ?? _fallbackMessage(reason),
      retryAfter: DateTime.fromMillisecondsSinceEpoch(retryAfterMs),
    );
  }

  /// `not_found` (the search answered and nothing matched), `removed` (the upload is gone) or `age_restricted`; a newer server may say more.
  final String reason;

  /// The server's own sentence for the reason (the one the stream answers with).
  final String message;

  /// When the server stops believing it (its clock): from then on a tap tries for real.
  final DateTime retryAfter;

  /// Whether it still holds. A phone whose clock is far off marks a song too long or too short; it cannot do worse than that.
  bool liveAt(DateTime now) => now.isBefore(retryAfter);

  /// What a tap on the marked song says: the server's sentence and, for "not found", when to try again (the memory goes by itself).
  String get sentence =>
      reason == 'not_found' ? '$message Try again in a few days.' : message;

  static String _fallbackMessage(String reason) => switch (reason) {
        'removed' => 'YouTube has no copy of that song that can be played.',
        'age_restricted' =>
          'That song needs an age check, so it cannot be played here.',
        _ => 'Nothing matching that song was found.',
      };
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
    this.unavailable,
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
      unavailable: EncoreUnavailable.fromJson(json['unavailable']),
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

  /// The server already knows it cannot get this song (N-13); null when it knows nothing, and always null from a server that predates the field.
  final EncoreUnavailable? unavailable;

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

/// One song the server folded into another (N-11 part B, docs/17 "Songs merged into another"): [from] no longer exists on the server, [into]
/// is the survivor (a live ref), and [seq] is the place in the server's own list of merges (the cursor a phone sends next time).
@immutable
class EncoreMerge {
  const EncoreMerge(
      {required this.from, required this.into, required this.seq});

  /// Null for an entry that names no song or that merges a song into itself: it would change nothing, and one odd entry must not stop a sync.
  static EncoreMerge? tryParse(Map<String, dynamic> json) {
    final from = readString(json['from']);
    final into = readString(json['into']);
    if (from == null || into == null || from.isEmpty || into.isEmpty) {
      return null;
    }
    if (from == into) return null;
    return EncoreMerge(from: from, into: into, seq: readInt(json['seq']) ?? 0);
  }

  final String from;
  final String into;
  final int seq;

  @override
  String toString() => 'EncoreMerge($seq: $from -> $into)';
}

/// The songs whose file changed (the browse index of what the server keeps), and the songs that were merged into another.
@immutable
class EncoreFiles {
  const EncoreFiles({
    required this.refs,
    required this.cursor,
    required this.more,
    this.merges = const [],
    this.mergesCursor,
    this.mergesMore = false,
  });

  factory EncoreFiles.fromJson(Map<String, dynamic> json) {
    final merges = [
      for (final m in readObjectList(json['merges']))
        if (EncoreMerge.tryParse(m) case final merge?) merge
    ]..sort((a, b) => a.seq.compareTo(b.seq));
    return EncoreFiles(
      refs: [
        for (final r in readObjectList(json['refs'])) EncoreRef.fromJson(r)
      ],
      cursor: readString(json['cursor']) ?? '0',
      more: readBool(json['more']),
      merges: merges,
      mergesCursor: readString(json['mergesCursor']),
      mergesMore: readBool(json['mergesMore']),
    );
  }

  final List<EncoreRef> refs;
  final String cursor;
  final bool more;

  /// The merges after the cursor that was sent, oldest first. Empty from a server that predates merges.
  final List<EncoreMerge> merges;

  /// Where to ask from next time. Null when the server did not say (one that predates merges): the phone then keeps the cursor it has.
  final String? mergesCursor;
  final bool mergesMore;
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

  /// The server keeps songs of its own and tells a phone how it goes (`keep/progress`, `keep/watch`, `keep/retry`).
  bool get hasKeep => features.contains('keep');

  /// The server can be asked for a whole download at once (`keep/ask`). An app does without a feature that is not listed; it never tries a route to
  /// find out (docs/17 "Versions").
  bool get hasKeepAsk => features.contains('keep-ask');
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

// ---------------------------------------------------------------------------------------------------------------------------- how the server keeps

/// One download as the server knows it, by the kind and id the phone pinned (docs/17 "Keep progress"): a playlist (`pl_...`), the liked songs
/// (`liked`), or a catalogue release (`cat:<id>`, with the songs the phone knows, which the server uses only for a release saved before it stored them).
@immutable
class KeepGroupKey {
  const KeepGroupKey(this.kind, this.id, {this.refs = const []});

  final String kind;
  final String id;
  final List<String> refs;

  Map<String, Object?> toJson() =>
      {'kind': kind, 'id': id, if (refs.isNotEmpty) 'refs': refs};

  @override
  bool operator ==(Object other) =>
      other is KeepGroupKey && other.kind == kind && other.id == id;

  @override
  int get hashCode => Object.hash(kind, id);

  @override
  String toString() => '$kind:$id';
}

/// A song the server could not get, with the sentence for the person (the cause for the Host, the plain fact for a member) and whether asking
/// again can help.
@immutable
class KeepFailure {
  const KeepFailure({
    required this.ref,
    required this.title,
    required this.artist,
    required this.reason,
    required this.retry,
  });

  factory KeepFailure.fromJson(Map<String, dynamic> json) => KeepFailure(
        ref: readString(json['ref']) ?? '',
        title: readString(json['title']) ?? '',
        artist: readString(json['artist']) ?? '',
        reason: readString(json['reason']) ?? '',
        retry: readBool(json['retry']),
      );

  final String ref;
  final String title;
  final String artist;
  final String reason;
  final bool retry;
}

/// How far the server is with the songs of ONE download. Every song is in exactly one of [ready], [keeping], [queued] and [failed], so they add up to
/// [total].
@immutable
class KeepGroup {
  const KeepGroup({
    required this.kind,
    required this.id,
    required this.total,
    required this.ready,
    required this.keeping,
    required this.queued,
    required this.failed,
    required this.retryable,
    required this.failures,
  });

  factory KeepGroup.fromJson(Map<String, dynamic> json) => KeepGroup(
        kind: readString(json['kind']) ?? '',
        id: readString(json['id']) ?? '',
        total: readInt(json['total']) ?? 0,
        ready: readInt(json['ready']) ?? 0,
        keeping: readInt(json['keeping']) ?? 0,
        queued: readInt(json['queued']) ?? 0,
        failed: readInt(json['failed']) ?? 0,
        retryable: readInt(json['retryable']) ?? 0,
        failures: [
          for (final f in readObjectList(json['failures']))
            KeepFailure.fromJson(f)
        ],
      );

  final String kind;
  final String id;
  final int total;

  /// The server holds the file.
  final int ready;

  /// Being fetched this moment.
  final int keeping;

  /// Waiting its turn (or for YouTube's rest).
  final int queued;

  /// Not coming: named in [failures] (at most the first few; the count is all of them).
  final int failed;

  /// Of the failed, how many asking again can help.
  final int retryable;
  final List<KeepFailure> failures;

  KeepGroupKey get key => KeepGroupKey(kind, id);

  /// On its way to the server: being fetched or waiting.
  int get waiting => keeping + queued;

  bool get serverHasAll => total > 0 && ready >= total;
}

/// YouTube as the server describes it while it keeps songs: `ok`, `resting` (it will go on after [resumesInSec]) or `off`.
@immutable
class KeepYoutube {
  const KeepYoutube({this.state = 'off', this.resumesInSec = 0});

  factory KeepYoutube.fromJson(Object? json) {
    final m = readMap(json);
    return KeepYoutube(
        state: readString(m?['state']) ?? 'off',
        resumesInSec: readInt(m?['resumesInSec']) ?? 0);
  }

  final String state;
  final int resumesInSec;

  bool get resting => state == 'resting';
}

/// The answer of `keep/watch`, and what `keep.progress` pushes: the downloads the person has, in the order asked.
@immutable
class KeepProgress {
  const KeepProgress(
      {required this.groups, this.youtube = const KeepYoutube()});

  factory KeepProgress.fromJson(Map<String, dynamic> json) => KeepProgress(
        groups: [
          for (final g in readObjectList(json['groups']))
            if ((readString(g['kind']) ?? '').isNotEmpty &&
                (readString(g['id']) ?? '').isNotEmpty)
              KeepGroup.fromJson(g)
        ],
        youtube: KeepYoutube.fromJson(json['youtube']),
      );

  final List<KeepGroup> groups;
  final KeepYoutube youtube;

  KeepGroup? of(KeepGroupKey key) {
    for (final g in groups) {
      if (g.kind == key.kind && g.id == key.id) return g;
    }
    return null;
  }
}

/// The answer of `keep/ask`: how many songs the server was asked for, and how the downloads go now.
@immutable
class KeepAsked {
  const KeepAsked({required this.asked, required this.progress});

  factory KeepAsked.fromJson(Map<String, dynamic> json) => KeepAsked(
      asked: readInt(json['asked']) ?? 0,
      progress: KeepProgress.fromJson(json));

  final int asked;
  final KeepProgress progress;
}

/// The answer of `keep/retry`: how many songs were asked for again, and how that download goes now.
@immutable
class KeepRetried {
  const KeepRetried(
      {required this.retried, required this.group, required this.youtube});

  factory KeepRetried.fromJson(Map<String, dynamic> json) {
    final g = readMap(json['group']);
    return KeepRetried(
      retried: readInt(json['retried']) ?? 0,
      group: g == null ? null : KeepGroup.fromJson(g),
      youtube: KeepYoutube.fromJson(json['youtube']),
    );
  }

  final int retried;
  final KeepGroup? group;
  final KeepYoutube youtube;
}
