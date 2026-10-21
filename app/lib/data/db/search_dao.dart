import 'package:drift/drift.dart';

import 'app_database.dart';

/// Builds a safe FTS5 `MATCH` expression from free user input.
///
/// * Splits on anything that is not a letter/number (Unicode aware), so
///   punctuation and FTS operators typed by the user can never cause a syntax
///   error or inject query syntax.
/// * Quotes every token and makes it a prefix match (`"alc"*`), giving
///   search-as-you-type behaviour.
/// * A token that may be spelled with a ligature is searched in both
///   spellings (`aenima` also finds `Ænima`): the index folds accents but
///   not ligatures.
/// * Returns `null` when there is nothing searchable.
String? toFtsQuery(String input) {
  final tokens = RegExp(r'[\p{L}\p{N}]+', unicode: true)
      .allMatches(input)
      .map((m) => m.group(0)!)
      .toList();
  if (tokens.isEmpty) return null;
  var grouped = false;
  final parts = tokens.map((t) {
    final variants = _ligatureVariants(t);
    if (variants.isEmpty) return '"$t"*';
    grouped = true;
    return '("$t"* OR ${variants.map((v) => '"$v"*').join(' OR ')})';
  }).toList();
  // FTS5 takes a bare space between phrases, but a parenthesised group needs
  // the explicit operator.
  return parts.join(grouped ? ' AND ' : ' ');
}

const Map<String, String> _ligatures = {'ae': 'æ', 'oe': 'œ', 'ss': 'ß'};

/// The other spellings of [token]: a ligature typed as two letters, or the
/// two letters written as the ligature.
Set<String> _ligatureVariants(String token) {
  final lower = token.toLowerCase();
  final out = <String>{};
  _ligatures.forEach((two, one) {
    if (lower.contains(two)) out.add(lower.replaceAll(two, one));
    if (lower.contains(one)) out.add(lower.replaceAll(one, two));
  });
  out.remove(lower);
  return out;
}

/// Offline full-text search over the local library (< 30 ms on 50k tracks is a
/// budget in docs/00-requirements.md).
class SearchDao {
  SearchDao(this._db);

  final AppDatabase _db;

  /// Tracks matching [query], best match first. Empty list if not searchable.
  Selectable<TrackRow> tracks(int serverId, String query, {int limit = 50}) {
    final match = toFtsQuery(query);
    if (match == null) return _empty(_db.tracks);
    return _db.customSelect(
      'SELECT t.* FROM track_fts '
      'JOIN tracks t ON t.rowid = track_fts.rowid '
      'WHERE track_fts MATCH ?1 AND t.server_id = ?2 '
      'AND t.deleted_at_ms IS NULL '
      'ORDER BY bm25(track_fts, 10.0, 4.0, 2.0) LIMIT ?3',
      variables: [
        Variable<String>(match),
        Variable<int>(serverId),
        Variable<int>(limit),
      ],
      readsFrom: {_db.tracks},
    ).map((row) => _db.tracks.map(row.data));
  }

  Selectable<AlbumRow> albums(int serverId, String query, {int limit = 30}) {
    final match = toFtsQuery(query);
    if (match == null) return _empty(_db.albums);
    return _db.customSelect(
      'SELECT a.* FROM album_fts '
      'JOIN albums a ON a.rowid = album_fts.rowid '
      'WHERE album_fts MATCH ?1 AND a.server_id = ?2 '
      'AND a.deleted_at_ms IS NULL '
      'ORDER BY bm25(album_fts, 10.0, 3.0) LIMIT ?3',
      variables: [
        Variable<String>(match),
        Variable<int>(serverId),
        Variable<int>(limit),
      ],
      readsFrom: {_db.albums},
    ).map((row) => _db.albums.map(row.data));
  }

  Selectable<ArtistRow> artists(int serverId, String query, {int limit = 20}) {
    final match = toFtsQuery(query);
    if (match == null) return _empty(_db.artists);
    return _db.customSelect(
      'SELECT r.* FROM artist_fts '
      'JOIN artists r ON r.rowid = artist_fts.rowid '
      'WHERE artist_fts MATCH ?1 AND r.server_id = ?2 '
      'AND r.deleted_at_ms IS NULL '
      'ORDER BY bm25(artist_fts) LIMIT ?3',
      variables: [
        Variable<String>(match),
        Variable<int>(serverId),
        Variable<int>(limit),
      ],
      readsFrom: {_db.artists},
    ).map((row) => _db.artists.map(row.data));
  }

  Selectable<D> _empty<Tbl extends Table, D>(TableInfo<Tbl, D> table) =>
      _db.select(table)..where((_) => const Constant(false));
}
