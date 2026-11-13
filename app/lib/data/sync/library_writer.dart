import 'package:drift/drift.dart';

import '../api/opensubsonic/models.dart';
import '../db/app_database.dart';
import 'fingerprint.dart';
import 'pending_intent.dart';

/// Writes server DTOs into the local database.
///
/// Rules (ADR-006):
/// * **Upsert only.** Existing rows are updated in place; nothing is deleted
///   here. Removal is a separate, verified tombstone step.
/// * Every page is one transaction.
/// * A re-seen tombstoned row is resurrected (`deletedAtMs = null`).
class LibraryWriter {
  LibraryWriter(this._db);

  final AppDatabase _db;

  /// The server's star state, unless a like/unlike of this id is still waiting
  /// in the outbox: then the column is left alone (absent), so a new row starts
  /// unstarred and an existing one keeps the person's choice (B7).
  static Value<int?> _star(Set<String> pending, String id, int? server) =>
      pending.contains(id) ? const Value.absent() : Value(server);

  Future<void> upsertArtists(
    int serverId,
    int runId,
    Iterable<SsArtist> artists,
  ) async {
    final pending = await pendingStarTargets(_db, serverId);
    final rows = [
      for (final a in artists)
        if (a.id.isNotEmpty)
          ArtistsCompanion.insert(
            serverId: serverId,
            id: a.id,
            name: a.name,
            sortName: Value(a.sortName),
            coverArt: Value(a.coverArt),
            albumCount: Value(a.albumCount),
            musicBrainzId: Value(a.musicBrainzId),
            imageUrl: Value(a.imageUrl),
            starredAtMs: _star(pending, a.id, a.starredAtMs),
            fingerprint: Value(artistFingerprint(a)),
            syncRun: Value(runId),
            deletedAtMs: const Value(null),
          ),
    ];
    if (rows.isEmpty) return;
    await _db.batch((b) => b.insertAllOnConflictUpdate(_db.artists, rows));
  }

  Future<void> upsertAlbums(
    int serverId,
    int runId,
    Iterable<SsAlbum> albums,
  ) async {
    final pending = await pendingStarTargets(_db, serverId);
    final rows = [
      for (final a in albums)
        if (a.id.isNotEmpty)
          AlbumsCompanion.insert(
            serverId: serverId,
            id: a.id,
            name: a.name,
            artistId: Value(a.artistId),
            sortName: Value(a.sortName),
            artist: Value(a.artist),
            year: Value(a.year),
            genre: Value(a.genre),
            coverArt: Value(a.coverArt),
            songCount: Value(a.songCount),
            durationSec: Value(a.durationSec),
            musicBrainzId: Value(a.musicBrainzId),
            recordLabel: Value(a.recordLabel),
            isCompilation: Value(a.isCompilation),
            createdAtMs: Value(a.createdAtMs),
            starredAtMs: _star(pending, a.id, a.starredAtMs),
            userRating: Value(a.userRating),
            playCount: Value(a.playCount),
            fingerprint: Value(albumFingerprint(a)),
            syncRun: Value(runId),
            deletedAtMs: const Value(null),
          ),
    ];
    if (rows.isEmpty) return;
    await _db.batch((b) => b.insertAllOnConflictUpdate(_db.albums, rows));
  }

  /// Upserts songs. When [runId] is `null` (songs discovered through a
  /// playlist rather than the library dump) the row's `syncRun` is left alone,
  /// so such tracks are not mistaken for "seen by the library dump".
  Future<void> upsertTracks(
    int serverId,
    int? runId,
    Iterable<SsSong> songs,
  ) async {
    final pending = await pendingStarTargets(_db, serverId);
    final rows = [
      for (final s in songs)
        if (s.id.isNotEmpty)
          TracksCompanion.insert(
            serverId: serverId,
            id: s.id,
            title: s.title,
            albumId: Value(s.albumId),
            artistId: Value(s.artistId),
            album: Value(s.album),
            artist: Value(s.artist),
            trackNo: Value(s.trackNo),
            discNo: Value(s.discNo),
            year: Value(s.year),
            genre: Value(s.genre),
            coverArt: Value(s.coverArt),
            durationSec: Value(s.durationSec),
            size: Value(s.size),
            suffix: Value(s.suffix),
            contentType: Value(s.contentType),
            bitRate: Value(s.bitRate),
            samplingRate: Value(s.samplingRate),
            bitDepth: Value(s.bitDepth),
            channels: Value(s.channels),
            path: Value(s.path),
            musicBrainzId: Value(s.musicBrainzId),
            isrc: Value(s.isrc),
            rgTrackGain: Value(s.rgTrackGain),
            rgAlbumGain: Value(s.rgAlbumGain),
            rgTrackPeak: Value(s.rgTrackPeak),
            rgAlbumPeak: Value(s.rgAlbumPeak),
            starredAtMs: _star(pending, s.id, s.starredAtMs),
            userRating: Value(s.userRating),
            playCount: Value(s.playCount),
            createdAtMs: Value(s.createdAtMs),
            missing: const Value(false),
            fingerprint: Value(trackFingerprint(s)),
            audioKey: Value(audioKeyOf(s)),
            syncRun: runId == null ? const Value.absent() : Value(runId),
            deletedAtMs: const Value(null),
          ),
    ];
    if (rows.isEmpty) return;
    await _db.batch((b) => b.insertAllOnConflictUpdate(_db.tracks, rows));
    await linkSongsToListedArtists(serverId);
  }

  /// A song whose artist the music server does not list is linked to the artist of its album instead; returns how many songs were changed.
  ///
  /// A file tagged "Post Malone, Swae Lee" (the keeper writes the artists of a song joined into one tag) belongs, for the music server, to an artist
  /// of that whole name. That artist has no album of its own and is not in the server's artist index, so the phone never receives it, and every
  /// screen that follows the song's artist link (the player's artist name, "Go to artist", the artist's own songs, what is played most) met a link to
  /// nothing: the page spun for ever (owner, 7 Nov 2026). On a freshly signed-in phone 382 of 4,719 songs (145 such artists) were in that state, 159 of
  /// them showing a single artist ("Busta Rhymes", "Drake"); every one has an album whose artist the phone does have. A song with no such album keeps
  /// its link (the artist page then finds the artist by name).
  Future<int> linkSongsToListedArtists(int serverId) => _db.customUpdate(
        'UPDATE tracks SET artist_id = ('
        'SELECT a.artist_id FROM albums a '
        'JOIN artists r ON r.server_id = a.server_id AND r.id = a.artist_id AND r.deleted_at_ms IS NULL '
        'WHERE a.server_id = tracks.server_id AND a.id = tracks.album_id AND a.deleted_at_ms IS NULL) '
        'WHERE server_id = ?1 AND deleted_at_ms IS NULL AND artist_id IS NOT NULL '
        'AND NOT EXISTS (SELECT 1 FROM artists r WHERE r.server_id = tracks.server_id AND r.id = tracks.artist_id AND r.deleted_at_ms IS NULL) '
        'AND EXISTS (SELECT 1 FROM albums a '
        'JOIN artists r ON r.server_id = a.server_id AND r.id = a.artist_id AND r.deleted_at_ms IS NULL '
        'WHERE a.server_id = tracks.server_id AND a.id = tracks.album_id AND a.deleted_at_ms IS NULL)',
        variables: [Variable.withInt(serverId)],
        updates: {_db.tracks},
        updateKind: UpdateKind.update,
      );

  /// Marks rows not seen by run [runId] as removed, for the tables whose flag
  /// is set. Returns how many rows were tombstoned per table. Must only be
  /// called after a **complete** dump; the caller decides per table whether the
  /// answer for that table is trustworthy (the shrink guard, B6).
  Future<TombstoneCounts> tombstoneUnseen({
    required int serverId,
    required int runId,
    required int nowMs,
    bool tracks = true,
    bool albums = true,
    bool artists = true,
  }) async {
    final t = !tracks
        ? 0
        : await (_db.update(_db.tracks)
              ..where((t) =>
                  t.serverId.equals(serverId) &
                  t.deletedAtMs.isNull() &
                  t.syncRun.isSmallerThanValue(runId)))
            .write(TracksCompanion(deletedAtMs: Value(nowMs)));
    final a = !albums
        ? 0
        : await (_db.update(_db.albums)
              ..where((t) =>
                  t.serverId.equals(serverId) &
                  t.deletedAtMs.isNull() &
                  t.syncRun.isSmallerThanValue(runId)))
            .write(AlbumsCompanion(deletedAtMs: Value(nowMs)));
    final r = !artists
        ? 0
        : await (_db.update(_db.artists)
              ..where((t) =>
                  t.serverId.equals(serverId) &
                  t.deletedAtMs.isNull() &
                  t.syncRun.isSmallerThanValue(runId)))
            .write(ArtistsCompanion(deletedAtMs: Value(nowMs)));
    return TombstoneCounts(tracks: t, albums: a, artists: r);
  }

  Future<int> _count<T extends HasResultSet, D>(
    ResultSetImplementation<T, D> table,
    Expression<bool> where,
  ) async {
    final c = countAll();
    final q = _db.selectOnly(table)
      ..addColumns([c])
      ..where(where);
    return (await q.getSingle()).read(c) ?? 0;
  }

  /// Live (non-tombstoned) rows per table.
  Future<LibraryCounts> liveCounts(int serverId) async {
    return LibraryCounts(
      tracks: await _count(
          _db.tracks,
          _db.tracks.serverId.equals(serverId) &
              _db.tracks.deletedAtMs.isNull()),
      albums: await _count(
          _db.albums,
          _db.albums.serverId.equals(serverId) &
              _db.albums.deletedAtMs.isNull()),
      artists: await _count(
          _db.artists,
          _db.artists.serverId.equals(serverId) &
              _db.artists.deletedAtMs.isNull()),
    );
  }

  /// Rows the dump of run [runId] saw, per table.
  Future<LibraryCounts> seenCounts(int serverId, int runId) async {
    return LibraryCounts(
      tracks: await _count(
          _db.tracks,
          _db.tracks.serverId.equals(serverId) &
              _db.tracks.syncRun.equals(runId)),
      albums: await _count(
          _db.albums,
          _db.albums.serverId.equals(serverId) &
              _db.albums.syncRun.equals(runId)),
      artists: await _count(
          _db.artists,
          _db.artists.serverId.equals(serverId) &
              _db.artists.syncRun.equals(runId)),
    );
  }

  /// Live (non-tombstoned) track count.
  Future<int> liveTrackCount(int serverId) async =>
      (await liveCounts(serverId)).tracks;

  Future<int> seenByRunCount(int serverId, int runId) async =>
      (await seenCounts(serverId, runId)).tracks;

  /// Flags downloaded copies whose source audio changed on the server.
  Future<int> markStaleDownloads({
    required int serverId,
    required int nowMs,
  }) {
    return _db.customUpdate(
      'UPDATE downloads SET stale = 1, updated_at_ms = ?2 '
      'WHERE server_id = ?1 AND state = 2 AND stale = 0 '
      "AND source_audio_key != '' AND EXISTS ("
      '  SELECT 1 FROM tracks t WHERE t.server_id = downloads.server_id '
      '  AND t.id = downloads.track_id AND t.deleted_at_ms IS NULL '
      '  AND t.audio_key != downloads.source_audio_key)',
      variables: [Variable<int>(serverId), Variable<int>(nowMs)],
      updates: {_db.downloads},
      updateKind: UpdateKind.update,
    );
  }
}

class TombstoneCounts {
  const TombstoneCounts({
    required this.tracks,
    required this.albums,
    required this.artists,
  });

  final int tracks;
  final int albums;
  final int artists;
}

/// How many rows each catalogue table holds (or how many a dump saw).
class LibraryCounts {
  const LibraryCounts({
    required this.tracks,
    required this.albums,
    required this.artists,
  });

  final int tracks;
  final int albums;
  final int artists;

  /// `tracks|albums|artists`: one comparable value for "the same answer".
  String get signature => '$tracks|$albums|$artists';
}
