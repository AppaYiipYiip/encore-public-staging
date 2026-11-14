import 'dart:convert';

import 'package:drift/drift.dart';

import '../db/app_database.dart';
import '../repos/release_store.dart';
import '../sync/fingerprint.dart';
import '../sync/pending_intent.dart';
import 'encore_merge.dart';
import 'encore_models.dart';
import 'pending_playlist_edits.dart';

/// Writes what the Encore server says into the local database (docs/18 section 2).
///
/// A song is a **ref**: its row in `tracks` has the ref's id, whether or not the server keeps a file of it, and the file (when there is
/// one) is only a column. Likes, playlist entries, downloads and history all point at that id, so a file that is renamed, replaced or
/// deleted on the server changes nothing a person has.
///
/// Same rules as the music-server writer (ADR-006): upsert only, one transaction per page, a re-seen tombstone comes back, and a like or
/// unlike still waiting in the outbox is never overwritten by what the server last knew.
class EncoreWriter {
  EncoreWriter(this._db, this.serverId,
      {required this.ownerName, MergedFiles files = const DiskFiles()})
      : _merger = RefMerger(_db, serverId),
        _files = files;

  final AppDatabase _db;
  final int serverId;
  final RefMerger _merger;
  final MergedFiles _files;

  /// The account's name on the server: playlists of this phone's person carry it as owner, so "mine" is decided the same way as before.
  final String ownerName;

  static TracksCompanion _companion(int serverId, EncoreRef ref) {
    final file = ref.file;
    final replay = file?.replayGain;
    double? gain(String key) {
      final v = replay?[key];
      return v is num ? v.toDouble() : null;
    }

    return TracksCompanion.insert(
      serverId: serverId,
      id: ref.id,
      title: ref.title,
      isRef: const Value(true),
      fileId: Value(file?.navidromeSongId),
      artistsJson: Value(jsonEncode(ref.artists)),
      videoId: Value(ref.videoId),
      coverUrl: Value(ref.coverUrl),
      explicit: Value(ref.explicit),
      albumId: Value(file?.albumId),
      artistId: Value(file?.artistId),
      album: Value(ref.album),
      artist: Value(ref.artist.isEmpty ? null : ref.artist),
      trackNo: Value(ref.trackNo),
      discNo: Value(ref.discNo),
      year: Value(ref.year),
      genre: Value(file?.genre),
      // The catalogue's picture when the server found one (the same image on every screen, and it never shows the music server's
      // blank-record placeholder for a file that came without art); otherwise the music server's own.
      coverArt: Value(ref.coverUrl ?? file?.coverArt),
      durationSec: Value(ref.durationSec),
      size: Value(file?.size),
      suffix: Value(file?.suffix),
      contentType: Value(file?.contentType),
      bitRate: Value(file?.bitrateKbps),
      samplingRate: Value(file?.samplingRate),
      bitDepth: Value(file?.bitDepth),
      channels: Value(file?.channels),
      musicBrainzId: Value(ref.mbid),
      isrc: Value(ref.isrc),
      rgTrackGain: Value(gain('trackGain')),
      rgAlbumGain: Value(gain('albumGain')),
      rgTrackPeak: Value(gain('trackPeak')),
      rgAlbumPeak: Value(gain('albumPeak')),
      createdAtMs: Value(file?.createdAtMs),
      missing: const Value(false),
      fingerprint: Value(refFingerprint(ref)),
      audioKey: Value(refAudioKey(ref)),
      deletedAtMs: const Value(null),
    );
  }

  /// Gives every ref its row.
  Future<void> upsertRefs(Iterable<EncoreRef> refs) async {
    final list = refs.where((r) => r.id.isNotEmpty).toList();
    if (list.isEmpty) return;
    await _db.batch((b) => b.insertAllOnConflictUpdate(
        _db.tracks, [for (final r in list) _companion(serverId, r)]));
  }

  /// Songs the server merged into another (N-11 part B): everything the phone has under the old id moves to the survivor, and the old row goes
  /// (see [RefMerger]). Call it in the transaction of the files page, BEFORE [upsertRefs], then [settleMerges]; after the commit, [finishMerges].
  Future<MergeOutcome> applyMerges(List<EncoreMerge> merges) =>
      _merger.apply(merges);

  /// In the same transaction, after the refs were written: the moved downloads take the survivor's audio key (so they are not downloaded again).
  Future<void> settleMerges(MergeOutcome outcome) => _merger.settle(outcome);

  /// After the commit: renames the moved files to the survivor's name and deletes the copies that were not kept. Never throws.
  Future<void> finishMerges(MergeOutcome outcome) =>
      _merger.finish(outcome, _files);

  /// Retires the rows of songs that have no file on the server and that nothing of the person's points at (no like, no playlist entry, no
  /// download): the browse index lists only what the server has and what the person uses. Called after likes and entries were applied.
  Future<void> dropUnused(Iterable<String> ids, {required int nowMs}) async {
    final all = ids.toSet().toList();
    for (var i = 0; i < all.length; i += 400) {
      final chunk = all.sublist(i, i + 400 > all.length ? all.length : i + 400);
      final marks = List.filled(chunk.length, '?').join(',');
      await _db.customUpdate(
        'UPDATE tracks SET deleted_at_ms = ?1 WHERE server_id = ?2 AND file_id IS NULL AND is_ref = 1 AND deleted_at_ms IS NULL '
        'AND id IN ($marks) AND starred_at_ms IS NULL '
        'AND NOT EXISTS (SELECT 1 FROM playlist_entries e WHERE e.server_id = tracks.server_id AND e.track_id = tracks.id) '
        'AND NOT EXISTS (SELECT 1 FROM downloads d WHERE d.server_id = tracks.server_id AND d.track_id = tracks.id)',
        variables: [
          Variable<int>(nowMs),
          Variable<int>(serverId),
          for (final id in chunk) Variable<String>(id),
        ],
        updates: {_db.tracks},
        updateKind: UpdateKind.update,
      );
    }
  }

  /// The person's likes: a set. A like still waiting in the outbox (the person's intent is newer than the server's view) is left alone.
  Future<void> applyLikes(Iterable<EncoreLike> likes,
      {required int nowMs}) async {
    final pending = await pendingStarTargets(_db, serverId);
    for (final like in likes) {
      if (like.ref.isEmpty || pending.contains(like.ref)) continue;
      await (_db.update(_db.tracks)
            ..where((t) => t.serverId.equals(serverId) & t.id.equals(like.ref)))
          .write(
        TracksCompanion(
            starredAtMs: Value(like.removed ? null : (like.atMs ?? nowMs))),
      );
    }
  }

  /// Saved albums and followed artists (the ids are the music server's album and artist ids).
  Future<void> applySets({
    required Iterable<EncoreSetItem> albums,
    required Iterable<EncoreSetItem> follows,
    required int nowMs,
  }) async {
    // The releases the person saved from the catalogue (`cat:<id>`) are no row of the library, so they are remembered by id: it is what keeps
    // "In your library" true after a restart and on a second phone (D-35).
    await ReleaseStore(_db, serverId).applySaved(albums);
    final pending = await pendingStarTargets(_db, serverId);
    for (final a in albums) {
      if (a.id.isEmpty || pending.contains(a.id)) continue;
      await (_db.update(_db.albums)
            ..where((t) => t.serverId.equals(serverId) & t.id.equals(a.id)))
          .write(AlbumsCompanion(
              starredAtMs: Value(a.removed ? null : (a.atMs ?? nowMs))));
    }
    for (final a in follows) {
      if (a.id.isEmpty || pending.contains(a.id)) continue;
      await (_db.update(_db.artists)
            ..where((t) => t.serverId.equals(serverId) & t.id.equals(a.id)))
          .write(ArtistsCompanion(
              starredAtMs: Value(a.removed ? null : (a.atMs ?? nowMs))));
    }
  }

  /// Playlists as the server has them now (a deleted one is tombstoned with its entries), then their entries; the order of each affected
  /// playlist is counted again from the server's fractional positions.
  Future<void> applyPlaylists(
    Iterable<EncorePlaylist> playlists,
    Iterable<EncoreEntry> entries, {
    required int nowMs,
  }) async {
    // What the person did on this phone and the server has not heard yet is not undone by what the server last knew (P2-28, B-61): a rename,
    // a delete and a removal that wait in the outbox. Each is protected on its own field, never by skipping the whole playlist: another device's
    // entries arrive one touched entry at a time, each with its own older sequence number, so skipping a pull for a playlist would lose them.
    final waiting = await pendingPlaylistEdits(_db, serverId);
    final touched = <String>{};
    for (final p in playlists) {
      if (p.id.isEmpty) continue;
      touched.add(p.id);
      if (p.deleted) {
        await (_db.update(_db.playlists)
              ..where((t) => t.serverId.equals(serverId) & t.id.equals(p.id)))
            .write(PlaylistsCompanion(deletedAtMs: Value(nowMs)));
        await (_db.delete(_db.playlistEntries)
              ..where((e) =>
                  e.serverId.equals(serverId) & e.playlistId.equals(p.id)))
            .go();
        continue;
      }
      // A server that deleted it wins over a waiting rename (docs/34 CF-21: the tombstone branch above). A waiting rename keeps the person's
      // name until it was delivered (then the feed brings the same name back); a waiting delete does not bring the playlist back from the tombstone.
      final keepName = waiting.renamed.contains(p.id);
      final keepDeleted = waiting.deleted.contains(p.id);
      final existing = keepName || keepDeleted
          ? await (_db.select(_db.playlists)
                ..where((t) => t.serverId.equals(serverId) & t.id.equals(p.id)))
              .getSingleOrNull()
          : null;
      if (existing != null) {
        // The row is there and part of it is the person's: write the other columns only (an upsert would need every required column, the name
        // too, so a protected column is left out of an UPDATE instead).
        await (_db.update(_db.playlists)
              ..where((t) => t.serverId.equals(serverId) & t.id.equals(p.id)))
            .write(PlaylistsCompanion(
          name: keepName ? const Value.absent() : Value(p.name),
          owner: Value(ownerName),
          readonly: const Value(false),
          coverArt: Value(p.cover),
          createdAtMs: Value(p.createdAtMs),
          changedAtMs: Value(p.updatedAtMs),
          entriesFetchedAtMs: Value(nowMs),
          deletedAtMs: keepDeleted ? const Value.absent() : const Value(null),
        ));
      } else {
        await _db
            .into(_db.playlists)
            .insertOnConflictUpdate(PlaylistsCompanion.insert(
              serverId: serverId,
              id: p.id,
              name: p.name,
              owner: Value(ownerName),
              readonly: const Value(false),
              coverArt: Value(p.cover),
              createdAtMs: Value(p.createdAtMs),
              changedAtMs: Value(p.updatedAtMs),
              entriesFetchedAtMs: Value(nowMs),
              deletedAtMs: const Value(null),
            ));
      }
    }
    for (final e in entries) {
      if (e.id.isEmpty || e.playlist.isEmpty) continue;
      touched.add(e.playlist);
      await (_db.delete(_db.playlistEntries)
            ..where(
                (t) => t.serverId.equals(serverId) & t.entryId.equals(e.id)))
          .go();
      // A removal that waits stays removed: the entry comes back from the server until the removal was delivered. By the entry's own id.
      if (e.deleted || waiting.removedEntries.contains(e.id)) continue;
      final playlist = await (_db.select(_db.playlists)
            ..where(
                (t) => t.serverId.equals(serverId) & t.id.equals(e.playlist)))
          .getSingleOrNull();
      if (playlist == null || playlist.deletedAtMs != null) continue;
      // At the end for now (a place no other entry has); the order is counted again below.
      final last = await _db.customSelect(
        'SELECT COALESCE(MAX(position), -1) AS p FROM playlist_entries WHERE server_id = ?1 AND playlist_id = ?2',
        variables: [Variable<int>(serverId), Variable<String>(e.playlist)],
        readsFrom: {_db.playlistEntries},
      ).getSingle();
      await _db
          .into(_db.playlistEntries)
          .insert(PlaylistEntriesCompanion.insert(
            serverId: serverId,
            playlistId: e.playlist,
            position: last.read<int>('p') + 1,
            trackId: e.ref,
            entryId: Value(e.id),
            serverPosition: Value(e.position),
          ));
    }
    for (final id in touched) {
      await _renumber(id, nowMs: nowMs);
    }
  }

  /// Counts a playlist's live entries again, 0..n-1, in the server's order, and refreshes what the playlist row says about them.
  Future<void> _renumber(String playlistId, {required int nowMs}) async {
    // Entries of the old kind of server (no id of the server's own) have no place in a playlist of this one.
    await (_db.delete(_db.playlistEntries)
          ..where((e) =>
              e.serverId.equals(serverId) &
              e.playlistId.equals(playlistId) &
              e.entryId.isNull()))
        .go();
    final rows = await (_db.select(_db.playlistEntries)
          ..where((e) =>
              e.serverId.equals(serverId) & e.playlistId.equals(playlistId))
          ..orderBy([
            (e) => OrderingTerm.asc(e.serverPosition),
            (e) => OrderingTerm.asc(e.entryId)
          ]))
        .get();
    if (rows.isNotEmpty) {
      await _db.customUpdate(
        'UPDATE playlist_entries SET position = position + 100000000 WHERE server_id = ?1 AND playlist_id = ?2',
        variables: [Variable<int>(serverId), Variable<String>(playlistId)],
        updates: {_db.playlistEntries},
        updateKind: UpdateKind.update,
      );
      for (var i = 0; i < rows.length; i++) {
        await _db.customUpdate(
          'UPDATE playlist_entries SET position = ?1 WHERE server_id = ?2 AND playlist_id = ?3 AND entry_id = ?4',
          variables: [
            Variable<int>(i),
            Variable<int>(serverId),
            Variable<String>(playlistId),
            Variable<String>(rows[i].entryId ?? '')
          ],
          updates: {_db.playlistEntries},
          updateKind: UpdateKind.update,
        );
      }
    }
    final seconds = await _db.customSelect(
      'SELECT COALESCE(SUM(t.duration_sec), 0) AS s FROM playlist_entries e '
      'JOIN tracks t ON t.server_id = e.server_id AND t.id = e.track_id '
      'WHERE e.server_id = ?1 AND e.playlist_id = ?2',
      variables: [Variable<int>(serverId), Variable<String>(playlistId)],
      readsFrom: {_db.playlistEntries, _db.tracks},
    ).getSingle();
    await (_db.update(_db.playlists)
          ..where((p) => p.serverId.equals(serverId) & p.id.equals(playlistId)))
        .write(PlaylistsCompanion(
      songCount: Value(rows.length),
      durationSec: Value(seconds.read<int>('s')),
      entriesFetchedAtMs: Value(nowMs),
    ));
  }
}
