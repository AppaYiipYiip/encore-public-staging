import '../../core/clock.dart';
import '../../core/logger.dart';
import '../../core/result.dart';
import '../db/app_database.dart';
import '../sync/sync_state_store.dart';
import 'encore_api.dart';
import 'encore_merge.dart' show DiskFiles, MergeOutcome, MergedFiles;
import 'encore_writer.dart';

/// What one pull brought.
class EncoreSyncStats {
  const EncoreSyncStats(
      {this.files = 0,
      this.refs = 0,
      this.likes = 0,
      this.playlists = 0,
      this.entries = 0,
      this.merges = 0});

  final int files;
  final int refs;
  final int likes;
  final int playlists;
  final int entries;

  /// Songs of this phone that were folded into another one (N-11).
  final int merges;

  int get changed => files + refs + likes + playlists + entries + merges;

  EncoreSyncStats operator +(EncoreSyncStats o) => EncoreSyncStats(
        files: files + o.files,
        refs: refs + o.refs,
        likes: likes + o.likes,
        playlists: playlists + o.playlists,
        entries: entries + o.entries,
        merges: merges + o.merges,
      );
}

/// Keeps the phone's copy of a person's library and of the server's files in step with an Encore server (docs/17 sections 3 and 5).
///
/// Two feeds, each a state-based change list after a cursor, so a missed event or a repeated question ends up right: the server's **files**
/// (the browse index of what it keeps) and the person's **library** (likes, saved albums, followed artists, playlists and their entries,
/// with the songs they name). A first pass reads everything; later passes read what changed. The cursors are the server's own and live in
/// `sync_state`.
class EncoreSync {
  EncoreSync({
    required AppDatabase db,
    required EncoreApi api,
    required this.serverId,
    required String ownerName,
    Clock clock = const SystemClock(),
    this.pageLimit = 500,
    MergedFiles files = const DiskFiles(),
  })  : _db = db,
        _api = api,
        _clock = clock,
        _writer =
            EncoreWriter(db, serverId, ownerName: ownerName, files: files),
        _state = SyncStateStore(db, serverId);

  final AppDatabase _db;
  final EncoreApi _api;
  final Clock _clock;
  final EncoreWriter _writer;
  final SyncStateStore _state;
  final int serverId;
  final int pageLimit;

  static const filesCursor = 'encoreFilesCursor';

  /// Where the server's list of merged songs was read to (its own cursor, not [filesCursor]).
  static const mergesCursor = 'encoreMergesCursor';
  static const changesCursor = 'encoreChangesCursor';

  /// Where the server's list of retired songs was read to (its own cursor, like [mergesCursor]; N-27 slice 2b).
  static const goneCursor = 'encoreGoneCursor';

  /// Both feeds: the person's library first, then the server's files and the list of retired songs (N-35).
  ///
  /// In this order every pointer at a song (a place in a playlist, a like) is in its final state when the phone hears that a song's file is gone or that
  /// the song itself is retired, so the one rule that drops a row nothing points at ([EncoreWriter.dropUnused]) decides with the whole picture. The cursors
  /// are independent (each feed keeps its own, written in the transaction of the page it read), so a feed that cannot be read leaves the other side's cursors
  /// where they were: the next pull reads both.
  Future<Result<EncoreSyncStats>> pull() => guard(() async {
        final library = (await pullChanges()).getOrThrow();
        final files = (await pullFiles()).getOrThrow();
        return files + library;
      });

  Future<Result<EncoreSyncStats>> pullFiles() => guard(() async {
        var total = const EncoreSyncStats();
        var cursor = await _state.get(filesCursor) ?? '0';
        var mergesAt = await _state.get(mergesCursor) ?? '0';
        var goneAt = await _state.get(goneCursor) ?? '0';
        while (true) {
          final page = (await _api.files(
                  since: cursor,
                  limit: pageLimit,
                  mergesSince: mergesAt,
                  goneSince: goneAt))
              .getOrThrow();
          final nowMs = _clock.now().millisecondsSinceEpoch;
          late MergeOutcome merged;
          await _db.transaction(() async {
            // The songs the server folded into another first: what the phone has under the old id moves to the survivor, then the page's songs
            // are written (they carry the survivor's own fields). One transaction, so a pull that stops halfway leaves nothing half folded.
            merged = await _writer.applyMerges(page.merges);
            await _writer.upsertRefs(page.refs);
            await _writer.settleMerges(merged);
            await _writer.dropUnused([
              for (final r in page.refs)
                if (r.file?.navidromeSongId == null) r.id
            ], nowMs: nowMs);
            // The songs the server RETIRED (N-27): in the same transaction as the page, so the cursor and what it stands for are never apart.
            await _writer
                .applyGone([for (final g in page.gone) g.id], nowMs: nowMs);
            await _state.set(filesCursor, page.cursor);
            // A server that predates merges does not say: the cursor stays where it was.
            if (page.mergesCursor != null) {
              await _state.set(mergesCursor, page.mergesCursor);
            }
            // The same for tombstones: a server from before them does not say, and the cursor stays where it was.
            if (page.goneCursor != null) {
              await _state.set(goneCursor, page.goneCursor);
            }
          });
          // Files cannot be rolled back, so they are touched only once the rows are safe.
          await _writer.finishMerges(merged);
          total +=
              EncoreSyncStats(files: page.refs.length, merges: merged.folded);
          final filesMoved = page.cursor != cursor;
          final mergesMoved =
              page.mergesCursor != null && page.mergesCursor != mergesAt;
          final goneMoved =
              page.goneCursor != null && page.goneCursor != goneAt;
          cursor = page.cursor;
          mergesAt = page.mergesCursor ?? mergesAt;
          goneAt = page.goneCursor ?? goneAt;
          // Three feeds, three cursors: keep reading while any has more AND is getting somewhere.
          if (!((page.more && filesMoved) ||
              (page.mergesMore && mergesMoved) ||
              (page.goneMore && goneMoved))) {
            break;
          }
        }
        if (total.files > 0 || total.merges > 0) {
          Log.info('encore-sync',
              'files: ${total.files} songs changed, ${total.merges} merged songs folded');
        }
        return total;
      });

  Future<Result<EncoreSyncStats>> pullChanges() => guard(() async {
        var total = const EncoreSyncStats();
        var cursor = await _state.get(changesCursor) ?? '0';
        while (true) {
          final page = (await _api.changes(since: cursor)).getOrThrow();
          final nowMs = _clock.now().millisecondsSinceEpoch;
          await _db.transaction(() async {
            await _writer.upsertRefs(page.refs);
            await _writer.applyLikes(page.likes, nowMs: nowMs);
            await _writer.applySets(
                albums: page.savedAlbums, follows: page.follows, nowMs: nowMs);
            final freed = await _writer
                .applyPlaylists(page.playlists, page.entries, nowMs: nowMs);
            // The songs a page carries, and the songs whose place in a playlist the page took away: a purged tombstone names no song, so the phone's own
            // entry rows are what says which (N-35).
            await _writer.dropUnused([
              for (final r in page.refs) r.id,
              for (final l in page.likes) l.ref,
              for (final e in page.entries) e.ref,
              ...freed,
            ], nowMs: nowMs);
            await _state.set(changesCursor, page.cursor);
          });
          total += EncoreSyncStats(
            refs: page.refs.length,
            likes: page.likes.length,
            playlists: page.playlists.length,
            entries: page.entries.length,
          );
          final moved = page.cursor != cursor;
          cursor = page.cursor;
          if (!page.more || !moved) break;
        }
        if (total.changed > 0) {
          Log.info('encore-sync',
              'library: ${total.likes} likes, ${total.playlists} playlists, ${total.entries} entries');
        }
        return total;
      });

  /// Forgets where the feeds were (a new account on this phone, or a server that was set up again): the next pull reads everything.
  Future<void> reset() async {
    await _state.set(filesCursor, null);
    // Applying a merge twice changes nothing, so reading all of them again is safe.
    await _state.set(mergesCursor, null);
    // Retiring a row twice changes nothing, so reading all of the tombstones again is safe.
    await _state.set(goneCursor, null);
    await _state.set(changesCursor, null);
  }
}
