import 'dart:convert';
import 'dart:io';

import 'package:drift/drift.dart';
import 'package:path/path.dart' as p;

import '../../core/logger.dart';
import '../../domain/audio_quality.dart';
import '../../playback/playback_state_store.dart' show DbPlaybackStateStore;
import '../db/app_database.dart';
import '../downloads/download_planner.dart' show DownloadState;
import '../repos/release_store.dart';
import '../sync/sync_state_store.dart';
import 'encore_models.dart';

/// The files of downloaded songs, as far as a merge touches them. A seam so a test can use a temporary folder (or fail on purpose); the phone
/// uses [DiskFiles].
abstract interface class MergedFiles {
  Future<bool> exists(String path);

  /// Moves [from] to [to] in one step, replacing [to] if it is there.
  Future<void> rename(String from, String to);
  Future<void> delete(String path);
}

class DiskFiles implements MergedFiles {
  const DiskFiles();

  @override
  Future<bool> exists(String path) async => File(path).existsSync();

  @override
  Future<void> rename(String from, String to) async {
    // rename(2) replaces an existing file in one step, like the download manager's swap of a refreshed copy.
    File(from).renameSync(to);
  }

  @override
  Future<void> delete(String path) async {
    final file = File(path);
    if (file.existsSync()) file.deleteSync();
  }
}

/// A downloaded copy that became the survivor's: its row was re-keyed (inside the transaction, still naming the file where it is), and the
/// file is renamed to the survivor's name afterwards.
class MovedDownload {
  const MovedDownload(
      {required this.nameId, required this.survivorId, required this.path});

  /// The id the file is named after now (the loser's, or the first of a chain).
  final String nameId;
  final String survivorId;

  /// Where the file is.
  final String path;

  MovedDownload toSurvivor(String id) =>
      MovedDownload(nameId: nameId, survivorId: id, path: path);
}

/// What applying a page of merges did, and the file work that must wait until the transaction has committed (a file cannot be rolled back).
class MergeOutcome {
  const MergeOutcome(
      {this.folded = 0, this.moves = const [], this.deletes = const []});

  static const none = MergeOutcome();

  /// How many merges found something of the phone's to fold (a row, an entry, a download, a like...).
  final int folded;
  final List<MovedDownload> moves;

  /// Files of copies that were not kept (the survivor already had its own).
  final List<String> deletes;
}

/// Folds a song the server merged into another (`from` -> `into`) into the phone's own database, so one song is one entry, one like and one
/// download (N-11 part B, docs/17 "Songs merged into another", docs/34 CF-43).
///
/// Everything that names the loser by id is moved to the survivor in ONE transaction (the caller's): playlist entries, play history, the like,
/// the download (the copy is MOVED, never deleted when it is the only one), single-song pins, lyrics, the saved queue with its resume
/// position and the releases saved on this phone. Then the loser's row is deleted, or renamed when the phone does not have the survivor's.
///
/// Why not `EncoreUpgrade._rekey`: its `UPDATE OR IGNORE` skips a row whenever the new id already exists, and then deletes what is left. In a
/// merge the survivor exists, so that is a silent loss. Every move here is a plain `UPDATE`, or an explicit rule for the two rows that would
/// meet (pins, lyrics, downloads).
///
/// Idempotent: a loser that is gone and names nothing changes nothing, so a repeated or re-sent merge is harmless. Applied one merge at a
/// time in `seq` order, so a chain (A into B, then B into C) in one page, or across two pages, ends at C.
///
/// Outbox payloads are not rewritten: the server resolves an old id at every route that takes a song id (docs/17), so a queued edit that
/// names the loser still works.
class RefMerger {
  RefMerger(this._db, this.serverId) : _state = SyncStateStore(_db, serverId);

  final AppDatabase _db;
  final int serverId;
  final SyncStateStore _state;

  /// Applies [merges] (oldest first). Call inside the transaction of the page, before its refs are written.
  Future<MergeOutcome> apply(List<EncoreMerge> merges) async {
    if (merges.isEmpty) return MergeOutcome.none;
    final ordered = [...merges]..sort((a, b) => a.seq.compareTo(b.seq));
    final moves = <MovedDownload>[];
    final deletes = <String>[];
    final redirect = <String, String>{};
    var folded = 0;
    for (final m in ordered) {
      if (m.from.isEmpty || m.into.isEmpty || m.from == m.into) continue;
      if (await _fold(m.from, m.into, moves, deletes)) folded++;
      // A song folded earlier into the loser follows it to its new survivor.
      redirect.updateAll((k, v) => v == m.from ? m.into : v);
      redirect[m.from] = m.into;
    }
    await _rewriteSnapshot(DbPlaybackStateStore.key, redirect);
    await _rewriteSnapshot(DbPlaybackStateStore.progressKey, redirect);
    await ReleaseStore(_db, serverId).foldSongs(redirect);
    return MergeOutcome(folded: folded, moves: moves, deletes: deletes);
  }

  /// After the page's refs were written: the moved downloads say which audio they were made from, and that is the survivor's (the two refs
  /// share ONE file on the server, but each describes it with its own length, and the audio key hashes that). Without this the next sync marks
  /// the moved copy stale and the person downloads again what he already has.
  Future<void> settle(MergeOutcome outcome) async {
    if (outcome.moves.isEmpty) return;
    final ids = {for (final m in outcome.moves) m.survivorId}.toList();
    final marks = List.filled(ids.length, '?').join(',');
    await _db.customUpdate(
      'UPDATE downloads SET source_audio_key = COALESCE('
      "(SELECT t.audio_key FROM tracks t WHERE t.server_id = downloads.server_id AND t.id = downloads.track_id AND t.audio_key != ''), "
      'source_audio_key) '
      'WHERE server_id = ? AND state = ${DownloadState.done} AND track_id IN ($marks)',
      variables: [
        Variable<int>(serverId),
        for (final id in ids) Variable<String>(id)
      ],
      updates: {_db.downloads},
      updateKind: UpdateKind.update,
    );
  }

  /// After the transaction committed: the file work. A file that cannot be moved or deleted is left where it is: the row names the file
  /// wherever it is, so the worst a failure here leaves is a file with the old name or an orphan file, never a song without its copy.
  Future<void> finish(MergeOutcome outcome, MergedFiles files) async {
    for (final path in outcome.deletes) {
      try {
        await files.delete(path);
      } on Object catch (error) {
        Log.warn('encore-merge', 'could not delete $path', error);
      }
    }
    for (final move in outcome.moves) {
      try {
        await _rename(move, files);
      } on Object catch (error) {
        Log.warn('encore-merge', 'could not rename ${move.path}', error);
      }
    }
  }

  /// `downloads/<server>/<loser>.opus` -> `downloads/<server>/<survivor>.opus`: the rule of a new download (`<track id>.<extension>`).
  static String? renamedPath(MovedDownload move) {
    final dir = p.dirname(move.path);
    final name = p.basename(move.path);
    if (!name.startsWith(move.nameId)) {
      return null; // not named by the rule: leave it
    }
    final target =
        p.join(dir, move.survivorId + name.substring(move.nameId.length));
    return target == move.path ? null : target;
  }

  Future<void> _rename(MovedDownload move, MergedFiles files) async {
    final target = renamedPath(move);
    if (target == null || !await files.exists(move.path)) return;
    await files.rename(move.path, target);
    var pointed = 0;
    try {
      pointed = await _db.customUpdate(
        'UPDATE downloads SET local_path = ?1 WHERE server_id = ?2 AND track_id = ?3 AND local_path = ?4',
        variables: [
          Variable<String>(target),
          Variable<int>(serverId),
          Variable<String>(move.survivorId),
          Variable<String>(move.path),
        ],
        updates: {_db.downloads},
        updateKind: UpdateKind.update,
      );
    } finally {
      if (pointed == 0) {
        // The row does not name this file any more (or the write failed): put the file back where the row can find it.
        try {
          await files.rename(target, move.path);
        } on Object catch (error) {
          Log.warn('encore-merge', 'could not put ${move.path} back', error);
        }
      }
    }
  }

  // ------------------------------------------------------------------ one merge

  /// Folds [loser] into [survivor]; true when the phone had anything of the loser's.
  Future<bool> _fold(String loser, String survivor, List<MovedDownload> moves,
      List<String> deletes) async {
    final loserRow = await _track(loser);
    final survivorRow = await _track(survivor);
    var touched = loserRow != null;

    // A like of the loser's belongs to the survivor (a rename carries it by itself).
    if (loserRow?.starredAtMs != null && survivorRow != null) {
      await _exec(
        'UPDATE tracks SET starred_at_ms = ?1 WHERE server_id = ?2 AND id = ?3 AND starred_at_ms IS NULL',
        [loserRow!.starredAtMs, serverId, survivor],
        {_db.tracks},
      );
    }

    // Places in playlists and plays: plain re-points (a playlist's own key is its position, never the song).
    final entries = await _exec(
      'UPDATE playlist_entries SET track_id = ?1 WHERE server_id = ?2 AND track_id = ?3',
      [survivor, serverId, loser],
      {_db.playlistEntries},
    );
    final plays = await _exec(
      'UPDATE play_history SET track_id = ?1 WHERE server_id = ?2 AND track_id = ?3',
      [survivor, serverId, loser],
      {_db.playHistory},
    );
    if (entries > 0 || plays > 0) touched = true;

    if (await _foldPins(loser, survivor)) touched = true;

    // Lyrics: the survivor keeps its own when it has some, otherwise it takes the loser's.
    final lyrics = await _exec(
      'UPDATE OR IGNORE lyrics SET track_id = ?1 WHERE server_id = ?2 AND track_id = ?3',
      [survivor, serverId, loser],
      {_db.lyrics},
    );
    if (lyrics > 0) touched = true;
    final dropped = await _exec(
      'DELETE FROM lyrics WHERE server_id = ?1 AND track_id = ?2',
      [serverId, loser],
      {_db.lyrics},
      kind: UpdateKind.delete,
    );
    if (dropped > 0) touched = true;

    if (await _foldDownload(loser, survivor, moves, deletes)) touched = true;

    // The row itself. A survivor that was retired (no file, nothing of the person's) comes back when the loser was live: it holds the
    // person's things now, and a retired row is left out of the pins' members and of the lists.
    if (survivorRow != null) {
      if (loserRow != null &&
          loserRow.deletedAtMs == null &&
          survivorRow.deletedAtMs != null) {
        await _exec(
          'UPDATE tracks SET deleted_at_ms = NULL WHERE server_id = ?1 AND id = ?2',
          [serverId, survivor],
          {_db.tracks},
        );
      }
      if (loserRow != null) {
        await _exec(
          'DELETE FROM tracks WHERE server_id = ?1 AND id = ?2',
          [serverId, loser],
          {_db.tracks},
          kind: UpdateKind.delete,
        );
      }
    } else if (loserRow != null) {
      // The phone never had the survivor: the loser's row becomes it (the page's refs, written next, bring the survivor's own fields).
      await _exec(
        'UPDATE tracks SET id = ?1 WHERE server_id = ?2 AND id = ?3',
        [survivor, serverId, loser],
        {_db.tracks},
      );
    }
    return touched;
  }

  /// A pin on one song: moved to the survivor; when both are pinned the survivor's stays at the better of the two qualities.
  Future<bool> _foldPins(String loser, String survivor) async {
    final rows = await _db.customSelect(
      "SELECT target_id, quality FROM pins WHERE server_id = ?1 AND target_type = 'track' AND target_id IN (?2, ?3)",
      variables: [
        Variable<int>(serverId),
        Variable<String>(loser),
        Variable<String>(survivor)
      ],
      readsFrom: {_db.pins},
    ).get();
    String? loserQuality;
    String? survivorQuality;
    for (final r in rows) {
      final id = r.read<String>('target_id');
      if (id == loser) loserQuality = r.read<String>('quality');
      if (id == survivor) survivorQuality = r.read<String>('quality');
    }
    if (loserQuality == null) return false;
    if (survivorQuality == null) {
      await _exec(
        "UPDATE pins SET target_id = ?1 WHERE server_id = ?2 AND target_type = 'track' AND target_id = ?3",
        [survivor, serverId, loser],
        {_db.pins},
      );
      return true;
    }
    final best = AudioQuality.best(
        AudioQuality.byId(survivorQuality), AudioQuality.byId(loserQuality));
    if (best.id != survivorQuality) {
      await _exec(
        "UPDATE pins SET quality = ?1 WHERE server_id = ?2 AND target_type = 'track' AND target_id = ?3",
        [best.id, serverId, survivor],
        {_db.pins},
      );
    }
    await _exec(
      "DELETE FROM pins WHERE server_id = ?1 AND target_type = 'track' AND target_id = ?2",
      [serverId, loser],
      {_db.pins},
      kind: UpdateKind.delete,
    );
    return true;
  }

  /// The download of the loser. Decided by whether a COPY exists (a path), not by whether a row exists:
  ///  * the loser has a copy and the survivor does not: the copy becomes the survivor's (the audio is the same file), as `done`;
  ///  * both have a copy: the BETTER one stays (the higher quality it was made at, `downloads.quality`: with the Data saver one of them may be a
  ///    48 kbps copy), as the survivor's; the other row goes and its file is deleted after the commit. Equal: the survivor's;
  ///  * the survivor is downloading right now: it is left to finish, and the loser's copy goes (the same song is arriving);
  ///  * the loser has no copy (queued, failed, or a first download in flight): its row goes (or becomes the survivor's, queued, when the
  ///    survivor has none). A transfer still running for the loser finds no row when it ends and throws its file away
  ///    (`DownloadManager._onComplete`), and the survivor is queued by the pins, which now name it.
  Future<bool> _foldDownload(String loser, String survivor,
      List<MovedDownload> moves, List<String> deletes) async {
    final mine = await _download(loser);
    if (mine == null) return false;
    final theirs = await _download(survivor);
    final loserHasCopy = (mine.localPath ?? '').isNotEmpty;
    final survivorHasCopy =
        theirs != null && (theirs.localPath ?? '').isNotEmpty;

    Future<void> dropLoser() => _exec(
          'DELETE FROM downloads WHERE server_id = ?1 AND track_id = ?2',
          [serverId, loser],
          {_db.downloads},
          kind: UpdateKind.delete,
        );

    if (!loserHasCopy) {
      if (theirs != null) {
        await dropLoser();
      } else {
        await _exec(
          'UPDATE downloads SET track_id = ?1, state = ${DownloadState.queued}, local_path = NULL, bytes = 0, expected_bytes = NULL, '
          'stale = 0, last_error = NULL, attempts = 0 WHERE server_id = ?2 AND track_id = ?3',
          [survivor, serverId, loser],
          {_db.downloads},
        );
      }
      return true;
    }

    final path = mine.localPath!;
    final loserIsBetter = survivorHasCopy &&
        AudioQuality.byId(mine.quality).rank >
            AudioQuality.byId(theirs.quality).rank;
    if (theirs?.state == DownloadState.downloading && !survivorHasCopy ||
        survivorHasCopy && !loserIsBetter) {
      // The survivor's own copy stays (or is arriving right now): the loser's goes.
      await dropLoser();
      _forget(path, moves);
      deletes.add(path);
      return true;
    }

    // The loser's copy moves: it is the only one, or the better one. The survivor's row gives way (a queued or failed one has no file; a worse
    // copy's file is deleted after the commit, before the better one is renamed onto its name). The loser's row is re-keyed IN PLACE, never copied
    // and deleted, so every column it has (and any column added later) comes along.
    if (theirs != null) {
      await _exec(
        'DELETE FROM downloads WHERE server_id = ?1 AND track_id = ?2',
        [serverId, survivor],
        {_db.downloads},
        kind: UpdateKind.delete,
      );
      if (survivorHasCopy) {
        final worse = theirs.localPath!;
        _forget(worse, moves);
        deletes.add(worse);
      }
    }
    await _exec(
      'UPDATE downloads SET track_id = ?1, state = ${DownloadState.done} WHERE server_id = ?2 AND track_id = ?3',
      [survivor, serverId, loser],
      {_db.downloads},
    );
    // A chain: the copy that was moved to the loser a moment ago moves on with it, keeping the name it was first given.
    final index = moves.indexWhere((m) => m.survivorId == loser);
    if (index >= 0) {
      moves[index] = moves[index].toSurvivor(survivor);
    } else {
      moves.add(MovedDownload(nameId: loser, survivorId: survivor, path: path));
    }
    return true;
  }

  /// A file that is going to be deleted is not renamed.
  void _forget(String path, List<MovedDownload> moves) =>
      moves.removeWhere((m) => m.path == path);

  // ------------------------------------------------------------------ rows and snapshots

  Future<TrackRow?> _track(String id) => (_db.select(_db.tracks)
        ..where((t) => t.serverId.equals(serverId) & t.id.equals(id)))
      .getSingleOrNull();

  Future<DownloadRow?> _download(String id) => (_db.select(_db.downloads)
        ..where((d) => d.serverId.equals(serverId) & d.trackId.equals(id)))
      .getSingleOrNull();

  Future<int> _exec(
    String sql,
    List<Object?> variables,
    Set<TableInfo<Table, Object?>> tables, {
    UpdateKind kind = UpdateKind.update,
  }) =>
      _db.customUpdate(
        sql,
        variables: [
          for (final v in variables)
            if (v is int) Variable<int>(v) else Variable<String>(v as String)
        ],
        updates: tables,
        updateKind: kind,
      );

  /// The saved queue and the saved position name songs by id: after a restart they must find the survivor.
  /// The ids are replaced where they stand (no entry is removed, so the order and the cursor indexes stay right: the same song twice in a
  /// queue is allowed). The GENERIC walk of `EncoreUpgrade._rekeyQueue`, not its `_rekey`.
  Future<void> _rewriteSnapshot(
      String key, Map<String, String> redirect) async {
    if (redirect.isEmpty) return;
    final raw = await _state.get(key);
    if (raw == null) return;
    var changed = false;
    Object? walk(Object? node) {
      if (node is String) {
        final to = redirect[node];
        if (to == null) return node;
        changed = true;
        return to;
      }
      if (node is List) return [for (final v in node) walk(v)];
      if (node is Map) {
        return {for (final e in node.entries) e.key: walk(e.value)};
      }
      return node;
    }

    try {
      final out = walk(jsonDecode(raw));
      if (changed) await _state.set(key, jsonEncode(out));
    } on FormatException {
      // A damaged snapshot is not ours to repair: the player ignores it the way it always did.
    }
  }
}
