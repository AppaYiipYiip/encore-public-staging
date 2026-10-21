import 'package:drift/drift.dart';

import '../../core/clock.dart';
import '../../domain/text_match.dart';
import '../db/app_database.dart';
import '../db/search_dao.dart';

/// Lifecycle of a request (docs/07-request-pipeline.md section 2).
abstract final class RequestState {
  /// Created locally, being sent.
  static const submitted = 'submitted';

  /// The portal accepted it; music arrives minutes to days later.
  static const requested = 'requested';

  /// The music showed up in the library (resolved by sync).
  static const inLibrary = 'in_library';

  /// Could not be sent / was rejected; can be retried.
  static const failed = 'failed';

  static const open = {submitted, requested};
}

/// Local record of what the user asked for, and whether it arrived.
class RequestRepository {
  RequestRepository(this._db, this.serverId,
      {Clock clock = const SystemClock()})
      : _clock = clock;

  final AppDatabase _db;
  final int serverId;
  final Clock _clock;

  int get _nowMs => _clock.now().millisecondsSinceEpoch;

  Stream<List<RequestRow>> watchAll() => (_db.select(_db.requests)
        ..where((r) => r.serverId.equals(serverId))
        ..orderBy([(r) => OrderingTerm.desc(r.createdAtMs)]))
      .watch();

  /// State of one artist/album request, `null` when never requested.
  Stream<RequestRow?> watchFor(String artist, String? album) => watchAll().map(
        (rows) {
          final key = matchKey(artist, album);
          for (final r in rows) {
            if (matchKey(r.artist, r.album) == key) return r;
          }
          return null;
        },
      );

  Future<RequestRow?> find(String artist, String? album) async {
    final key = matchKey(artist, album);
    final rows = await (_db.select(_db.requests)
          ..where((r) => r.serverId.equals(serverId)))
        .get();
    for (final r in rows) {
      if (matchKey(r.artist, r.album) == key) return r;
    }
    return null;
  }

  /// Records a new request, or returns the existing open/arrived one
  /// (duplicate suppression: tapping Request twice never asks twice).
  Future<RequestRow> create({required String artist, String? album}) async {
    final existing = await find(artist, album);
    if (existing != null && existing.state != RequestState.failed) {
      return existing;
    }
    final now = _nowMs;
    if (existing != null) {
      await (_db.update(_db.requests)..where((r) => r.id.equals(existing.id)))
          .write(RequestsCompanion(
        state: const Value(RequestState.submitted),
        detail: const Value(null),
        updatedAtMs: Value(now),
      ));
      return (await find(artist, album))!;
    }
    final id = await _db.into(_db.requests).insert(RequestsCompanion.insert(
          serverId: serverId,
          kind: album == null ? 'artist' : 'album',
          title: album ?? artist,
          artist: artist,
          album: Value(album),
          state: RequestState.submitted,
          createdAtMs: now,
          updatedAtMs: now,
        ));
    return (_db.select(_db.requests)..where((r) => r.id.equals(id)))
        .getSingle();
  }

  Future<void> setState(int id, String state, {String? detail}) =>
      (_db.update(_db.requests)..where((r) => r.id.equals(id))).write(
        RequestsCompanion(
          state: Value(state),
          detail: Value(detail),
          updatedAtMs: Value(_nowMs),
        ),
      );

  /// Marks open requests whose music is now in the library. Call after each
  /// library sync. Returns the rows that arrived (for notifications).
  Future<List<RequestRow>> resolveAgainstLibrary() async {
    final open = await (_db.select(_db.requests)
          ..where((r) =>
              r.serverId.equals(serverId) & r.state.isIn(RequestState.open)))
        .get();
    if (open.isEmpty) return const [];

    final dao = SearchDao(_db);
    final arrived = <RequestRow>[];
    for (final r in open) {
      final found = r.album == null
          ? await _artistArrived(dao, r.artist)
          : await _albumArrived(dao, r.artist, r.album!);
      if (found) {
        await setState(r.id, RequestState.inLibrary);
        arrived.add(r);
      }
    }
    return arrived;
  }

  Future<bool> _albumArrived(SearchDao dao, String artist, String album) async {
    final want = matchKey(artist, album);
    final candidates = await dao
        .albums(serverId, '$artist ${normalizeForMatch(album)}', limit: 20)
        .get();
    return candidates.any((a) => matchKey(a.artist, a.name) == want);
  }

  Future<bool> _artistArrived(SearchDao dao, String artist) async {
    final want = normalizeForMatch(artist);
    final candidates = await dao.artists(serverId, artist, limit: 10).get();
    return candidates
        .any((a) => normalizeForMatch(a.name) == want && a.albumCount > 0);
  }
}

/// "Do I already own this?" lookups for catalogue results.
class LibraryMatcher {
  LibraryMatcher(this._db, this.serverId);

  final AppDatabase _db;
  final int serverId;

  /// The library artist whose name matches [name] (accents, case, "The"
  /// ignored), or `null`.
  Future<ArtistRow?> findArtist(String name) async {
    final want = normalizeForMatch(name);
    final rows = await SearchDao(_db).artists(serverId, name, limit: 10).get();
    for (final a in rows) {
      if (normalizeForMatch(a.name) == want) return a;
    }
    return null;
  }

  Future<AlbumRow?> findAlbum(String artist, String title) async {
    final want = matchKey(artist, title);
    final rows = await SearchDao(_db)
        .albums(serverId, '$artist ${normalizeForMatch(title)}', limit: 20)
        .get();
    for (final a in rows) {
      if (matchKey(a.artist, a.name) == want) return a;
    }
    return null;
  }

  Future<bool> hasArtist(String name) async => await findArtist(name) != null;

  Future<bool> hasAlbum(String artist, String title) async =>
      await findAlbum(artist, title) != null;

  /// The library's copy of "[artist] - [title]", or `null`.
  Future<TrackRow?> findTrack(String artist, String title) async {
    final want = matchKey(artist, title);
    final rows = await SearchDao(_db)
        .tracks(serverId, '$artist ${normalizeForMatch(title)}', limit: 20)
        .get();
    for (final t in rows) {
      if (matchKey(t.artist, t.title) == want) return t;
    }
    return null;
  }

  Future<bool> hasTrack(String artist, String title) async {
    final want = matchKey(artist, title);
    final rows = await SearchDao(_db)
        .tracks(serverId, '$artist ${normalizeForMatch(title)}', limit: 20)
        .get();
    return rows.any((t) => matchKey(t.artist, t.title) == want);
  }
}
