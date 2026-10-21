import 'dart:async';

import 'package:drift/drift.dart';

import '../../core/clock.dart';
import '../../domain/text_match.dart';
import '../catalogue/catalogue_models.dart';
import '../db/app_database.dart';

/// Finds artwork for albums the server has no cover for, using the public
/// catalogue, and remembers the answer.
///
/// * positive results are kept forever (covers do not change),
/// * "not found" is kept for a week,
/// * lookups are serialised and spaced so a scrolling grid of 50 coverless
///   albums never trips the catalogue's rate limit.
class CoverFallbackRepository {
  CoverFallbackRepository({
    required AppDatabase db,
    required this.serverId,
    required CatalogueClient catalogue,
    Clock clock = const SystemClock(),
    Duration spacing = const Duration(milliseconds: 150),
  })  : _db = db,
        _catalogue = catalogue,
        _clock = clock,
        _spacing = spacing;

  final AppDatabase _db;
  final int serverId;
  final CatalogueClient _catalogue;
  final Clock _clock;
  final Duration _spacing;

  static const Duration _negativeTtl = Duration(days: 7);

  Future<void> _gate = Future<void>.value();
  final Map<String, Future<String?>> _inFlight = {};

  static String keyFor(String artist, String title) =>
      '${normalizeForMatch(artist)}|${normalizeForMatch(title)}';

  /// URL of a cover for [artist] / [title], or `null`.
  Future<String?> urlFor(String artist, String title) {
    final key = keyFor(artist, title);
    if (key == '|') return Future.value();
    // NB: the callback must not return `_inFlight.remove(...)` - that is the
    // very future being built, and `whenComplete` would wait on itself.
    return _inFlight.putIfAbsent(
      key,
      () => _lookup(key, artist, title).whenComplete(() {
        _inFlight.remove(key);
      }),
    );
  }

  Future<String?> _lookup(String key, String artist, String title) async {
    final row = await (_db.select(_db.coverFallbacks)
          ..where((r) => r.serverId.equals(serverId) & r.key.equals(key)))
        .getSingleOrNull();
    final now = _clock.now().millisecondsSinceEpoch;
    if (row != null) {
      if (row.url != null) return row.url;
      if (now - row.fetchedAtMs < _negativeTtl.inMilliseconds) return null;
    }

    // Serialise network lookups.
    final turn = _gate;
    final done = Completer<void>();
    _gate = done.future;
    await turn;
    try {
      final found = await _search(artist, title);
      await _db.into(_db.coverFallbacks).insertOnConflictUpdate(
            CoverFallbacksCompanion.insert(
              serverId: serverId,
              key: key,
              url: Value(found),
              fetchedAtMs: _clock.now().millisecondsSinceEpoch,
            ),
          );
      return found;
    } finally {
      unawaited(Future<void>.delayed(_spacing).then((_) => done.complete()));
    }
  }

  Future<String?> _search(String artist, String title) async {
    final results = await _catalogue.search('$artist $title', limit: 5);
    final wantArtist = normalizeForMatch(artist);
    final wantTitle = normalizeForMatch(title);
    CatalogueAlbum? best;
    for (final album in results.albums) {
      if (album.coverUrl == null) continue;
      final sameArtist = normalizeForMatch(album.artistName) == wantArtist;
      final sameTitle = normalizeForMatch(album.title) == wantTitle;
      if (sameArtist && sameTitle) return album.coverUrl;
      if (sameArtist && best == null) best = album;
    }
    // Accept a same-artist album only when the titles clearly overlap
    // (edition names, "(Remastered)", etc.); never a random release.
    if (best != null) {
      final t = normalizeForMatch(best.title);
      if (t.contains(wantTitle) || wantTitle.contains(t)) return best.coverUrl;
    }
    return null;
  }
}
