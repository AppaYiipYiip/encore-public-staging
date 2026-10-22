import '../../core/clock.dart';
import '../../core/logger.dart';
import '../../core/result.dart';
import '../db/app_database.dart';
import '../sync/sync_state_store.dart';
import 'encore_api.dart';
import 'encore_writer.dart';

/// What one pull brought.
class EncoreSyncStats {
  const EncoreSyncStats(
      {this.files = 0,
      this.refs = 0,
      this.likes = 0,
      this.playlists = 0,
      this.entries = 0});

  final int files;
  final int refs;
  final int likes;
  final int playlists;
  final int entries;

  int get changed => files + refs + likes + playlists + entries;

  EncoreSyncStats operator +(EncoreSyncStats o) => EncoreSyncStats(
        files: files + o.files,
        refs: refs + o.refs,
        likes: likes + o.likes,
        playlists: playlists + o.playlists,
        entries: entries + o.entries,
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
  })  : _db = db,
        _api = api,
        _clock = clock,
        _writer = EncoreWriter(db, serverId, ownerName: ownerName),
        _state = SyncStateStore(db, serverId);

  final AppDatabase _db;
  final EncoreApi _api;
  final Clock _clock;
  final EncoreWriter _writer;
  final SyncStateStore _state;
  final int serverId;
  final int pageLimit;

  static const filesCursor = 'encoreFilesCursor';
  static const changesCursor = 'encoreChangesCursor';

  /// Both feeds: the server's files, then the person's library.
  Future<Result<EncoreSyncStats>> pull() => guard(() async {
        final files = (await pullFiles()).getOrThrow();
        final library = (await pullChanges()).getOrThrow();
        return files + library;
      });

  Future<Result<EncoreSyncStats>> pullFiles() => guard(() async {
        var total = const EncoreSyncStats();
        var cursor = await _state.get(filesCursor) ?? '0';
        while (true) {
          final page =
              (await _api.files(since: cursor, limit: pageLimit)).getOrThrow();
          final nowMs = _clock.now().millisecondsSinceEpoch;
          await _db.transaction(() async {
            await _writer.upsertRefs(page.refs);
            await _writer.dropUnused([
              for (final r in page.refs)
                if (r.file?.navidromeSongId == null) r.id
            ], nowMs: nowMs);
            await _state.set(filesCursor, page.cursor);
          });
          total += EncoreSyncStats(files: page.refs.length);
          final moved = page.cursor != cursor;
          cursor = page.cursor;
          if (!page.more || !moved) break;
        }
        if (total.files > 0) {
          Log.info('encore-sync', 'files: ${total.files} songs changed');
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
            await _writer.applyPlaylists(page.playlists, page.entries,
                nowMs: nowMs);
            await _writer.dropUnused([
              for (final r in page.refs) r.id,
              for (final l in page.likes) l.ref,
              for (final e in page.entries) e.ref,
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
    await _state.set(changesCursor, null);
  }
}
