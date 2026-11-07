import 'dart:async';
import 'dart:convert';

import 'package:drift/drift.dart';
import 'package:flutter/foundation.dart' show listEquals;

import '../../core/stream_utils.dart';
import '../../domain/household.dart';
import '../api/opensubsonic/models.dart';
import '../db/app_database.dart';
import '../sync/library_writer.dart';

/// How album lists are ordered in the Library.
enum AlbumSort { recentlyAdded, alphabetical, artist, year }

/// Read side of the local library. Every method returns a Drift stream that
/// re-emits when sync (or the user) changes the underlying rows - this is how
/// "the server changed, the phone follows" reaches the UI without any
/// refresh plumbing (ADR-003).
/// The picture a song stands for in a collage or a list of covers to keep: the catalogue's picture the server found for it when it has
/// one (an address), else its album's, else its own. (An album the music server has no art for shows a blank record: such a song must
/// not bring that into a playlist's collage.)
const _coverOfSong =
    "COALESCE(CASE WHEN t.cover_art LIKE 'https://%' THEN t.cover_art END, a.cover_art, t.cover_art)";

class LibraryRepository {
  LibraryRepository(this._db, this.serverId);

  final AppDatabase _db;
  final int serverId;

  // ---------------------------------------------------------------- albums

  Stream<List<AlbumRow>> watchAlbums({
    AlbumSort sort = AlbumSort.alphabetical,
    int? limit,
  }) {
    final q = _db.select(_db.albums)
      ..where((a) => a.serverId.equals(serverId) & a.deletedAtMs.isNull());
    switch (sort) {
      case AlbumSort.recentlyAdded:
        q.orderBy([
          (a) => OrderingTerm.desc(a.createdAtMs),
          (a) => OrderingTerm.asc(a.name),
        ]);
      case AlbumSort.alphabetical:
        q.orderBy([(a) => OrderingTerm.asc(a.name.lower())]);
      case AlbumSort.artist:
        q.orderBy([
          (a) => OrderingTerm.asc(a.artist.lower()),
          (a) => OrderingTerm.asc(a.year),
        ]);
      case AlbumSort.year:
        q.orderBy([
          (a) => OrderingTerm.desc(a.year),
          (a) => OrderingTerm.asc(a.name.lower()),
        ]);
    }
    if (limit != null) q.limit(limit);
    return q.watch();
  }

  /// Adds songs (and their album) that appeared on the server after the last
  /// sync - a song fetched on request - so they can be played and listed at
  /// once. Rows are upserted exactly as a sync would; the next sync finds
  /// them unchanged. [runId] 0 keeps them from being mistaken for "seen by
  /// the latest library dump" (ADR-006).
  Future<void> ingest(Iterable<SsSong> songs, {SsAlbum? album}) async {
    final writer = LibraryWriter(_db);
    if (album != null) await writer.upsertAlbums(serverId, 0, [album]);
    await writer.upsertTracks(serverId, null, songs);
  }

  /// The songs with these ids that the library has (a play of a song that has
  /// since left the library has no row). Asked in chunks: SQLite takes a
  /// limited number of variables in one statement.
  Future<Map<String, TrackRow>> tracksByIds(Iterable<String> ids) async {
    final wanted = ids.toSet().toList();
    final found = <String, TrackRow>{};
    for (var i = 0; i < wanted.length; i += 400) {
      final chunk =
          wanted.sublist(i, i + 400 > wanted.length ? wanted.length : i + 400);
      final rows = await (_db.select(_db.tracks)
            ..where((t) => t.serverId.equals(serverId) & t.id.isIn(chunk)))
          .get();
      for (final row in rows) {
        found[row.id] = row;
      }
    }
    return found;
  }

  /// What this phone saw played itself (the app's own log): the Year in Music
  /// of a server that keeps no history of its own.
  Future<List<PlayHistoryRow>> ownPlays() =>
      (_db.select(_db.playHistory)..where((p) => p.serverId.equals(serverId)))
          .get();

  Future<TrackRow?> trackOnce(String id) => (_db.select(_db.tracks)
        ..where((t) => t.serverId.equals(serverId) & t.id.equals(id)))
      .getSingleOrNull();

  Stream<AlbumRow?> watchAlbum(String id) => (_db.select(_db.albums)
        ..where((a) => a.serverId.equals(serverId) & a.id.equals(id)))
      .watchSingleOrNull();

  Stream<List<AlbumRow>> watchArtistAlbums(String artistId) =>
      (_db.select(_db.albums)
            ..where((a) =>
                a.serverId.equals(serverId) &
                a.artistId.equals(artistId) &
                a.deletedAtMs.isNull())
            ..orderBy([(a) => OrderingTerm.desc(a.year)]))
          .watch();

  /// Albums by id, in the given order (used for server-provided lists such as
  /// "recently played"). Missing/tombstoned ids are skipped.
  Stream<List<AlbumRow>> watchAlbumsByIds(List<String> ids) {
    if (ids.isEmpty) return Stream.value(const []);
    final q = _db.select(_db.albums)
      ..where((a) =>
          a.serverId.equals(serverId) &
          a.id.isIn(ids) &
          a.deletedAtMs.isNull());
    return q.watch().map((rows) {
      final byId = {for (final r in rows) r.id: r};
      return [
        for (final id in ids)
          if (byId[id] != null) byId[id]!,
      ];
    });
  }

  // --------------------------------------------------------------- artists

  /// The artists the library holds something of: an album or a song. The music
  /// server can keep listing an artist that another person's library once shared
  /// (an album count and nothing under it); to a person who has none of their
  /// music that is a ghost, not a part of their library.
  /// A picture for each artist that has none of its own: the cover of one of its songs (the first, by id, so it does not change between looks),
  /// for the Library's Artists list (owner, 7 Nov 2026: "most of the artists have no icon, even famous ones": the music server has a photo of an
  /// artist only when it found one, and an artist whose songs came from the catalogue has none). Keyed by artist id.
  Future<Map<String, String>> artistCoverFallbacks() async {
    final rows = await _db.customSelect(
      'SELECT t.artist_id AS id, t.cover_art AS cover FROM tracks t '
      'WHERE t.server_id = ?1 AND t.deleted_at_ms IS NULL AND t.artist_id IS NOT NULL AND t.cover_art IS NOT NULL '
      'AND t.id = (SELECT MIN(t2.id) FROM tracks t2 WHERE t2.server_id = t.server_id AND t2.artist_id = t.artist_id '
      'AND t2.deleted_at_ms IS NULL AND t2.cover_art IS NOT NULL)',
      variables: [Variable.withInt(serverId)],
      readsFrom: {_db.tracks},
    ).get();
    return {
      for (final r in rows) r.read<String>('id'): r.read<String>('cover')
    };
  }

  /// The artists of a song, each on its own, in order; empty when nothing is known.
  ///
  /// One file can be on the phone as two entries: one made from the file's own tags, which carries the artists as ONE joined string
  /// (`["Drake, Kanye West, Lil Wayne, Eminem"]`), and the catalogue's, which carries the real list (`["Drake","Kanye West","Lil Wayne","Eminem"]`).
  /// A song the person plays can be either, so the entries of the same file are read together and the longest list wins: names are never guessed by
  /// cutting a joined string at its commas ("Tyler, The Creator" is one artist). On a freshly signed-in phone 165 entries carried a joined string, and 160
  /// of them had the catalogue's entry beside them.
  Future<List<String>> songArtists(String trackId) async {
    final rows = await _db.customSelect(
      'SELECT artists_json FROM tracks WHERE server_id = ?1 AND deleted_at_ms IS NULL AND artists_json IS NOT NULL '
      'AND (id = ?2 OR file_id = ?2 OR (file_id IS NOT NULL AND file_id = '
      '(SELECT file_id FROM tracks WHERE server_id = ?1 AND id = ?2)))',
      variables: [Variable.withInt(serverId), Variable.withString(trackId)],
      readsFrom: {_db.tracks},
    ).get();
    var best = const <String>[];
    for (final row in rows) {
      final names = _namesIn(row.read<String>('artists_json'));
      if (names.length > best.length) best = names;
    }
    return best;
  }

  static List<String> _namesIn(String json) {
    try {
      final decoded = jsonDecode(json);
      if (decoded is! List) return const [];
      return [
        for (final name in decoded)
          if (name is String && name.trim().isNotEmpty) name.trim(),
      ];
    } on FormatException {
      return const [];
    }
  }

  Stream<List<ArtistRow>> watchArtists() => (_db.select(_db.artists)
        ..where((a) =>
            a.serverId.equals(serverId) &
            a.deletedAtMs.isNull() &
            (a.id.isInQuery(_db.selectOnly(_db.albums)
                  ..addColumns([_db.albums.artistId])
                  ..where(_db.albums.serverId.equals(serverId) &
                      _db.albums.deletedAtMs.isNull() &
                      _db.albums.artistId.isNotNull())) |
                a.id.isInQuery(_db.selectOnly(_db.tracks)
                  ..addColumns([_db.tracks.artistId])
                  ..where(_db.tracks.serverId.equals(serverId) &
                      _db.tracks.deletedAtMs.isNull() &
                      _db.tracks.artistId.isNotNull()))))
        ..orderBy([(a) => OrderingTerm.asc(a.name.lower())]))
      .watch();

  Stream<ArtistRow?> watchArtist(String id) => (_db.select(_db.artists)
        ..where((a) => a.serverId.equals(serverId) & a.id.equals(id)))
      .watchSingleOrNull();

  // ------------------------------------------------------------ my music

  /// The albums and artists this account has a relationship with: songs it
  /// played, liked, rated or downloaded, and songs in its own (not
  /// server-generated) playlists. The catalogue is shared by a household; this
  /// is the personal slice of it (ADR-049).
  ///
  /// Re-evaluated at most every few seconds: downloads and sync write to the
  /// tables involved continuously and the answer changes rarely.
  Stream<MyMusic> watchMyMusic(String? me) {
    // Hand-built rather than `async*`: a generator parked on `await for`
    // cannot be cancelled until the next table update, which would keep this
    // subscription (and a query) alive after its screen is gone.
    // Ends when the listener cancels; there is no natural end to close at.
    // ignore: close_sinks
    late final StreamController<MyMusic> controller;
    StreamSubscription<void>? changes;
    MyMusic? last;
    var running = false;
    var again = false;

    Future<void> refresh() async {
      if (running) {
        again = true; // a result is in flight; rerun once it lands
        return;
      }
      running = true;
      try {
        do {
          again = false;
          final next = await loadMyMusic(me);
          if (controller.isClosed || !controller.hasListener) return;
          if (next != last) {
            last = next;
            controller.add(next);
          }
        } while (again);
      } on StateError {
        // The database was closed underneath us (shutdown): nothing to report.
      } on Object catch (error, stack) {
        if (!controller.isClosed) controller.addError(error, stack);
      } finally {
        running = false;
      }
    }

    controller = StreamController<MyMusic>(
      onListen: () {
        unawaited(refresh());
        changes = _db
            .tableUpdates(TableUpdateQuery.onAllTables([
              _db.tracks,
              _db.albums,
              _db.artists,
              _db.downloads,
              _db.playHistory,
              _db.playlists,
              _db.playlistEntries,
            ]))
            .throttleLatest(const Duration(seconds: 3))
            .listen((_) => unawaited(refresh()));
      },
      onCancel: () async {
        await changes?.cancel();
        changes = null;
      },
    );
    return controller.stream;
  }

  /// The artists this account plays most, best first: server play counts of
  /// their songs, plus 3 per liked song, plus plays recorded on this phone,
  /// plus 10 when the artist itself is liked. Whose news is worth a
  /// notification (ADR-051).
  Future<List<({String id, String name, int score})>> topArtists({
    int limit = 15,
    int minScore = 5,
  }) async {
    final rows = await _db.customSelect(
      '''
      SELECT ar.id AS id, ar.name AS name,
             COALESCE(SUM(COALESCE(t.play_count, 0)), 0)
           + 3 * COALESCE(SUM(CASE WHEN t.starred_at_ms IS NOT NULL
                                   THEN 1 ELSE 0 END), 0)
           + COALESCE(hist.n, 0)
           + CASE WHEN ar.starred_at_ms IS NOT NULL THEN 10 ELSE 0 END
             AS score
      FROM artists ar
      JOIN tracks t
        ON t.server_id = ar.server_id AND t.artist_id = ar.id
       AND t.deleted_at_ms IS NULL
      LEFT JOIN (
        SELECT ht.artist_id AS artist_id, COUNT(*) AS n
        FROM play_history h
        JOIN tracks ht
          ON ht.server_id = h.server_id AND ht.id = h.track_id
        WHERE h.server_id = ?1
        GROUP BY ht.artist_id
      ) hist ON hist.artist_id = ar.id
      WHERE ar.server_id = ?1 AND ar.deleted_at_ms IS NULL
      GROUP BY ar.id
      HAVING score >= ?2
      ORDER BY score DESC, ar.name ASC
      LIMIT ?3
      ''',
      variables: [
        Variable<int>(serverId),
        Variable<int>(minScore),
        Variable<int>(limit),
      ],
      readsFrom: {_db.artists, _db.tracks, _db.playHistory},
    ).get();
    return [
      for (final r in rows)
        (
          id: r.read<String>('id'),
          name: r.read<String>('name'),
          score: r.read<int>('score'),
        ),
    ];
  }

  Future<MyMusic> loadMyMusic(String? me) async {
    final rows = await _db.customSelect(
      '''
      WITH mine_tracks AS (
        SELECT t.album_id, t.artist_id
        FROM tracks t
        WHERE t.server_id = ?1 AND t.deleted_at_ms IS NULL AND (
              t.starred_at_ms IS NOT NULL
           OR COALESCE(t.play_count, 0) > 0
           OR COALESCE(t.user_rating, 0) > 0
           OR EXISTS (SELECT 1 FROM downloads d
                      WHERE d.server_id = t.server_id AND d.track_id = t.id
                        AND d.orphaned_at_ms IS NULL)
           OR EXISTS (SELECT 1 FROM play_history h
                      WHERE h.server_id = t.server_id AND h.track_id = t.id)
           OR EXISTS (SELECT 1 FROM playlist_entries e
                      JOIN playlists p
                        ON p.server_id = e.server_id AND p.id = e.playlist_id
                      WHERE e.server_id = t.server_id AND e.track_id = t.id
                        AND p.deleted_at_ms IS NULL AND p.readonly = 0
                        AND (p.owner IS NULL OR ?2 = ''
                             OR LOWER(TRIM(p.owner)) = ?2)))
      ),
      mine_albums AS (
        SELECT a.id, a.artist_id FROM albums a
        WHERE a.server_id = ?1 AND a.deleted_at_ms IS NULL
          AND (a.starred_at_ms IS NOT NULL
               OR COALESCE(a.play_count, 0) > 0
               OR COALESCE(a.user_rating, 0) > 0)
      )
      SELECT 'album' AS kind, album_id AS id FROM mine_tracks
        WHERE album_id IS NOT NULL
      UNION SELECT 'artist', artist_id FROM mine_tracks
        WHERE artist_id IS NOT NULL
      UNION SELECT 'album', id FROM mine_albums
      UNION SELECT 'artist', artist_id FROM mine_albums
        WHERE artist_id IS NOT NULL
      UNION SELECT 'artist', r.id FROM artists r
        WHERE r.server_id = ?1 AND r.deleted_at_ms IS NULL
          AND r.starred_at_ms IS NOT NULL
      ''',
      variables: [
        Variable<int>(serverId),
        Variable<String>((me ?? '').trim().toLowerCase()),
      ],
      readsFrom: {
        _db.tracks,
        _db.albums,
        _db.artists,
        _db.downloads,
        _db.playHistory,
        _db.playlists,
        _db.playlistEntries,
      },
    ).get();
    final albums = <String>{};
    final artists = <String>{};
    for (final r in rows) {
      final id = r.read<String>('id');
      (r.read<String>('kind') == 'album' ? albums : artists).add(id);
    }
    return MyMusic(albumIds: albums, artistIds: artists);
  }

  // ---------------------------------------------------------------- tracks

  Stream<List<TrackRow>> watchAlbumTracks(String albumId) =>
      (_db.select(_db.tracks)
            ..where((t) =>
                t.serverId.equals(serverId) &
                t.albumId.equals(albumId) &
                t.deletedAtMs.isNull())
            ..orderBy([
              (t) => OrderingTerm.asc(t.discNo),
              (t) => OrderingTerm.asc(t.trackNo),
              (t) => OrderingTerm.asc(t.title),
            ]))
          .watch();

  Stream<TrackRow?> watchTrack(String id) => (_db.select(_db.tracks)
        ..where((t) => t.serverId.equals(serverId) & t.id.equals(id)))
      .watchSingleOrNull();

  Stream<List<TrackRow>> watchLikedTracks() => (_db.select(_db.tracks)
        ..where((t) =>
            t.serverId.equals(serverId) &
            t.starredAtMs.isNotNull() &
            t.deletedAtMs.isNull())
        ..orderBy([(t) => OrderingTerm.desc(t.starredAtMs)]))
      .watch();

  Stream<int> watchTrackCount() {
    final count = _db.tracks.id.count();
    final q = _db.selectOnly(_db.tracks)
      ..addColumns([count])
      ..where(_db.tracks.serverId.equals(serverId) &
          _db.tracks.deletedAtMs.isNull());
    return q.watchSingle().map((r) => r.read(count) ?? 0);
  }

  Future<List<TrackRow>> randomTracks(int limit) => _db
      .customSelect(
        'SELECT * FROM tracks WHERE server_id = ?1 AND deleted_at_ms IS NULL '
        'ORDER BY RANDOM() LIMIT ?2',
        variables: [Variable<int>(serverId), Variable<int>(limit)],
        readsFrom: {_db.tracks},
      )
      .map((r) => _db.tracks.map(r.data))
      .get();

  /// Tracks of every album of [artistId], album order then track order.
  Future<List<TrackRow>> artistTracks(String artistId) =>
      (_db.select(_db.tracks)
            ..where((t) =>
                t.serverId.equals(serverId) &
                t.artistId.equals(artistId) &
                t.deletedAtMs.isNull())
            ..orderBy([
              (t) => OrderingTerm.asc(t.album),
              (t) => OrderingTerm.asc(t.discNo),
              (t) => OrderingTerm.asc(t.trackNo),
            ]))
          .get();

  // ------------------------------------------------------------- playlists

  Stream<List<PlaylistRow>> watchPlaylists() => (_db.select(_db.playlists)
        ..where((p) => p.serverId.equals(serverId) & p.deletedAtMs.isNull())
        ..orderBy([
          (p) => OrderingTerm.asc(p.readonly), // user playlists first
          (p) => OrderingTerm.asc(p.name.lower()),
        ]))
      .watch();

  Stream<PlaylistRow?> watchPlaylist(String id) => (_db.select(_db.playlists)
        ..where((p) => p.serverId.equals(serverId) & p.id.equals(id)))
      .watchSingleOrNull();

  /// Tracks of a playlist in playlist order.
  Stream<List<TrackRow>> watchPlaylistTracks(String playlistId) =>
      watchPlaylistEntries(playlistId)
          .map((entries) => [for (final e in entries) e.track]);

  /// Tracks of a playlist with the position of each entry. Entries whose
  /// track is unknown or deleted are skipped, so list index and position can
  /// differ - editing must use the position.
  Stream<List<({int position, TrackRow track})>> watchPlaylistEntries(
      String playlistId) {
    final e = _db.playlistEntries;
    final t = _db.tracks;
    final query = _db.select(e).join([
      innerJoin(
        t,
        t.serverId.equalsExp(e.serverId) & t.id.equalsExp(e.trackId),
      ),
    ])
      ..where(e.serverId.equals(serverId) &
          e.playlistId.equals(playlistId) &
          t.deletedAtMs.isNull())
      ..orderBy([OrderingTerm.asc(e.position)]);
    // The query runs again whenever anything in either table is written (a sync pass or a keep writes songs all the time while the server saves a
    // playlist), and a page of 2,000 songs rebuilt for a list that did not change is the slowness the owner felt: say nothing when nothing changed.
    return query
        .watch()
        .map((rows) => [
              for (final r in rows)
                (position: r.readTable(e).position, track: r.readTable(t)),
            ])
        .distinct((a, b) => listEquals(a, b));
  }

  /// Distinct album-cover ids of a playlist's tracks, most frequent first -
  /// the input to the collage fallback (R-09). One entry per album.
  Stream<List<String>> watchPlaylistCoverIds(String playlistId,
      {int limit = 9}) {
    return _db
        .customSelect(
          'SELECT $_coverOfSong AS cover, COUNT(*) AS n, '
          'MIN(e.position) AS first_pos '
          'FROM playlist_entries e '
          'JOIN tracks t ON t.server_id = e.server_id AND t.id = e.track_id '
          'LEFT JOIN albums a ON a.server_id = t.server_id AND a.id = t.album_id '
          'WHERE e.server_id = ?1 AND e.playlist_id = ?2 '
          'AND t.deleted_at_ms IS NULL '
          'AND $_coverOfSong IS NOT NULL '
          'GROUP BY COALESCE(t.album_id, t.id) '
          'ORDER BY n DESC, first_pos ASC LIMIT ?3',
          variables: [
            Variable<int>(serverId),
            Variable<String>(playlistId),
            Variable<int>(limit),
          ],
          readsFrom: {_db.playlistEntries, _db.tracks, _db.albums},
        )
        .watch()
        .map((rows) => [for (final r in rows) r.read<String>('cover')]);
  }

  /// The cover ids a person is most likely to see, in the order they matter: playlists (their own picture, then the albums of
  /// their first songs), downloaded songs, liked songs, the newest albums, the biggest artists. [limit] bounds the list; the
  /// rest of the library's covers load when they are first shown. The input to the background cover fetch (E3: offline shows
  /// covers, not letters).
  Future<List<String>> coverIdsToKeepOffline({int limit = 600}) async {
    const cover = _coverOfSong;
    const live = 't.deleted_at_ms IS NULL AND $cover IS NOT NULL';
    // A song's row shows the song's own cover id (`mf-...`), the collage and the album page the album's: the same picture under two
    // names, and offline a row without it is a letter. So the song's own id is fetched too when it differs.
    const own =
        't.deleted_at_ms IS NULL AND t.cover_art IS NOT NULL AND t.cover_art IS NOT a.cover_art';
    final rows = await _db.customSelect(
      'SELECT cover FROM ('
      // 0: the picture a playlist has of its own
      'SELECT cover_art AS cover, 0 AS rank, 0 AS ord FROM playlists '
      'WHERE server_id = ?1 AND deleted_at_ms IS NULL AND cover_art IS NOT NULL '
      'UNION ALL '
      // 1: the albums of each playlist's first songs (its collage)
      'SELECT $cover, 1, e.position FROM playlist_entries e '
      'JOIN tracks t ON t.server_id = e.server_id AND t.id = e.track_id '
      'LEFT JOIN albums a ON a.server_id = t.server_id AND a.id = t.album_id '
      'WHERE e.server_id = ?1 AND e.position < 12 AND $live '
      'UNION ALL '
      'SELECT t.cover_art, 1, e.position FROM playlist_entries e '
      'JOIN tracks t ON t.server_id = e.server_id AND t.id = e.track_id '
      'LEFT JOIN albums a ON a.server_id = t.server_id AND a.id = t.album_id '
      'WHERE e.server_id = ?1 AND e.position < 60 AND $own '
      'UNION ALL '
      // 2: songs on the phone
      'SELECT $cover, 2, 0 FROM downloads d '
      'JOIN tracks t ON t.server_id = d.server_id AND t.id = d.track_id '
      'LEFT JOIN albums a ON a.server_id = t.server_id AND a.id = t.album_id '
      'WHERE d.server_id = ?1 AND d.state = 2 AND $live '
      'UNION ALL '
      'SELECT t.cover_art, 2, 0 FROM downloads d '
      'JOIN tracks t ON t.server_id = d.server_id AND t.id = d.track_id '
      'LEFT JOIN albums a ON a.server_id = t.server_id AND a.id = t.album_id '
      'WHERE d.server_id = ?1 AND d.state = 2 AND $own '
      'UNION ALL '
      // 3: liked songs
      'SELECT $cover, 3, 0 FROM tracks t '
      'LEFT JOIN albums a ON a.server_id = t.server_id AND a.id = t.album_id '
      'WHERE t.server_id = ?1 AND t.starred_at_ms IS NOT NULL AND $live '
      'UNION ALL '
      'SELECT t.cover_art, 3, 0 FROM tracks t '
      'LEFT JOIN albums a ON a.server_id = t.server_id AND a.id = t.album_id '
      'WHERE t.server_id = ?1 AND t.starred_at_ms IS NOT NULL AND $own '
      'UNION ALL '
      // 4: the newest albums
      'SELECT cover, 4, ord FROM (SELECT cover_art AS cover, -COALESCE(created_at_ms, 0) AS ord FROM albums '
      'WHERE server_id = ?1 AND deleted_at_ms IS NULL AND cover_art IS NOT NULL '
      'ORDER BY ord LIMIT 200) '
      'UNION ALL '
      // 5: artists with the most albums
      'SELECT cover, 5, ord FROM (SELECT cover_art AS cover, -album_count AS ord FROM artists '
      'WHERE server_id = ?1 AND deleted_at_ms IS NULL AND cover_art IS NOT NULL '
      'ORDER BY ord LIMIT 100)'
      ') ORDER BY rank, ord',
      variables: [Variable<int>(serverId)],
      readsFrom: {
        _db.playlists,
        _db.playlistEntries,
        _db.tracks,
        _db.albums,
        _db.artists,
        _db.downloads,
      },
    ).get();
    final seen = <String>{};
    return [
      for (final r in rows)
        if (seen.add(r.read<String>('cover'))) r.read<String>('cover'),
    ].take(limit).toList();
  }

  /// Genres present in the library with their album counts (Search > Browse).
  ///
  /// Tags are typed by people and tools, so "Progressive Rock" and
  /// "progressive rock" are one genre: counted together and shown under the
  /// spelling most albums use (a tie goes to the one that sorts first, so the
  /// tile never flips between two names). The number of distinct spellings is
  /// small, so the merge is done here, after the cheap per-spelling count.
  Stream<List<({String name, int albums})>> watchGenres({int limit = 24}) {
    return _db
        .customSelect(
          'SELECT genre, COUNT(*) AS n FROM albums '
          "WHERE server_id = ?1 AND deleted_at_ms IS NULL AND genre IS NOT NULL "
          "AND genre != '' GROUP BY genre",
          variables: [Variable<int>(serverId)],
          readsFrom: {_db.albums},
        )
        .watch()
        .map((rows) {
          final byKey = <String, ({String name, int top, int total})>{};
          for (final r in rows) {
            final spelling = r.read<String>('genre');
            final n = r.read<int>('n');
            final key = spelling.toLowerCase();
            final seen = byKey[key];
            if (seen == null) {
              byKey[key] = (name: spelling, top: n, total: n);
            } else {
              final wins = n > seen.top ||
                  (n == seen.top && spelling.compareTo(seen.name) < 0);
              byKey[key] = (
                name: wins ? spelling : seen.name,
                top: wins ? n : seen.top,
                total: seen.total + n,
              );
            }
          }
          final merged = [
            for (final g in byKey.values) (name: g.name, albums: g.total),
          ]..sort((a, b) {
              final byCount = b.albums.compareTo(a.albums);
              return byCount != 0 ? byCount : a.name.compareTo(b.name);
            });
          return merged.take(limit).toList();
        });
  }

  /// The albums of a genre, whichever way its tags are cased.
  Stream<List<AlbumRow>> watchGenreAlbums(String genre, {int limit = 100}) =>
      (_db.select(_db.albums)
            ..where((a) =>
                a.serverId.equals(serverId) &
                a.genre.lower().equals(genre.toLowerCase()) &
                a.deletedAtMs.isNull())
            ..orderBy([(a) => OrderingTerm.asc(a.name.lower())])
            ..limit(limit))
          .watch();

  // ------------------------------------------------------------- downloads

  /// What is on the phone, by album and by playlist: those with at least one finished download among their songs. Built from the same
  /// `downloads` rows as [watchDownloadedTrackIds] (state done), so a song, an album and a playlist can never disagree about what is
  /// there. This is the one fact behind every "Not downloaded" and "Plays offline" (P1-15).
  Stream<OnPhone> watchOnPhone() => _db
      .customSelect(
        '''
SELECT 'album' AS kind, t.album_id AS id
FROM tracks t
JOIN downloads d ON d.server_id = t.server_id AND d.track_id = t.id AND d.state = 2
WHERE t.server_id = ?1 AND t.album_id IS NOT NULL AND t.deleted_at_ms IS NULL
UNION
SELECT 'playlist' AS kind, e.playlist_id AS id
FROM playlist_entries e
JOIN downloads d ON d.server_id = e.server_id AND d.track_id = e.track_id AND d.state = 2
WHERE e.server_id = ?1
''',
        variables: [Variable<int>(serverId)],
        readsFrom: {_db.downloads, _db.tracks, _db.playlistEntries},
      )
      .watch()
      .map((rows) => OnPhone(
            albums: {
              for (final r in rows)
                if (r.read<String>('kind') == 'album') r.read<String>('id'),
            },
            playlists: {
              for (final r in rows)
                if (r.read<String>('kind') == 'playlist') r.read<String>('id'),
            },
          ));

  Stream<Set<String>> watchDownloadedTrackIds() => (_db.select(_db.downloads)
        ..where((d) => d.serverId.equals(serverId) & d.state.equals(2)))
      .watch()
      .map((rows) => {for (final r in rows) r.trackId});

  // ----------------------------------------------------------- server lists

  /// Ordered ids stored by the sync engine for server-provided lists
  /// (`recent`, `frequent`).
  Stream<List<String>> watchServerList(String key) =>
      (_db.select(_db.recommendationsCache)
            ..where((r) => r.serverId.equals(serverId) & r.key.equals(key)))
          .watchSingleOrNull()
          .map((row) {
        if (row == null) return const <String>[];
        try {
          final decoded = jsonDecode(row.payloadJson);
          if (decoded is List) return decoded.map((e) => e.toString()).toList();
        } on FormatException {
          // Corrupt cache entry: treat as empty, it is rewritten by sync.
        }
        return const <String>[];
      });
}

/// The albums and playlists that have at least one song on the phone ([LibraryRepository.watchOnPhone]).
class OnPhone {
  const OnPhone({this.albums = const {}, this.playlists = const {}});

  static const OnPhone none = OnPhone();

  final Set<String> albums;
  final Set<String> playlists;

  @override
  bool operator ==(Object other) =>
      other is OnPhone &&
      other.albums.length == albums.length &&
      other.playlists.length == playlists.length &&
      other.albums.containsAll(albums) &&
      other.playlists.containsAll(playlists);

  @override
  int get hashCode => Object.hash(albums.length, playlists.length);
}
