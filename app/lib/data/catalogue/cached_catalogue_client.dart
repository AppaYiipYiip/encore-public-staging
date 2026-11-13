import 'dart:async';
import 'dart:collection';

import 'catalogue_models.dart';

/// A [CatalogueClient] that remembers what the catalogue answered, so a page that is opened again (an artist, an album: the person goes
/// back and forth between a few of them) is drawn from memory instead of asking the outside service again (owner, 7 Nov 2026: "it took
/// 3 seconds to open the artist, even if I do it for the same artist multiple times"; every open asked Deezer four times in a chain).
///
/// It stands in front of whichever client answers (Deezer today; the server's own catalogue module when P2-12 lands, ADR-R38), so it is
/// the same on either side of that move and can be dropped without touching a screen. It remembers in memory only: nothing is written
/// anywhere, and what is remembered is public catalogue data.
///
/// Answers are kept [keep] (a catalogue changes slowly). An answer of nothing is kept only [keepNothing]: the clients report an
/// unreachable service as an empty answer, so a failure must not be remembered as "this artist has no songs". Two asks for the same thing
/// at the same moment share one request. A request that throws is forgotten at once and the error goes on to the asker.
///
/// The text [search] and the genre charts are not remembered: the first is typed live (and has its own short memory in
/// `ArtistLookupCache`), the second is not asked twice in a row.
class CachedCatalogueClient implements CatalogueClient {
  CachedCatalogueClient(
    this._inner, {
    this.keep = const Duration(minutes: 30),
    this.keepNothing = const Duration(seconds: 30),
    this.most = 300,
    DateTime Function()? now,
  }) : _now = now ?? DateTime.now;

  final CatalogueClient _inner;
  final Duration keep;
  final Duration keepNothing;

  /// How many answers are held; the oldest goes first.
  final int most;
  final DateTime Function() _now;

  final LinkedHashMap<String, _Remembered> _memory =
      LinkedHashMap<String, _Remembered>();

  Future<T> _remember<T>(
      String key, Future<T> Function() ask, bool Function(T) isNothing) {
    final known = _memory[key];
    if (known != null && !known.expired(_now())) {
      return known.future as Future<T>;
    }
    _memory.remove(key);
    while (_memory.length >= most) {
      _memory.remove(_memory.keys.first);
    }
    final entry = _Remembered(ask());
    _memory[key] = entry;
    // The time is counted from when the answer arrived, so a slow answer is not already old.
    entry.future.then<void>((Object? value) {
      entry.until = _now().add(isNothing(value as T) ? keepNothing : keep);
    }, onError: (Object _) {
      if (identical(_memory[key], entry)) _memory.remove(key);
    });
    return entry.future as Future<T>;
  }

  static String _name(String text) => text.trim().toLowerCase();

  @override
  Future<CatalogueResults> search(String query, {int limit = 8}) =>
      _inner.search(query, limit: limit);

  @override
  Future<List<CatalogueArtist>> searchArtists(String query, {int limit = 5}) =>
      _remember('artists:${_name(query)}:$limit',
          () => _inner.searchArtists(query, limit: limit), (l) => l.isEmpty);

  @override
  Future<CatalogueArtist?> artist(String artistId) => _remember(
      'artist:$artistId', () => _inner.artist(artistId), (a) => a == null);

  @override
  Future<CatalogueAlbum?> album(String albumId) => _remember(
      'album:$albumId', () => _inner.album(albumId), (a) => a == null);

  @override
  Future<List<CatalogueTrack>> artistTopTracks(String artistId,
          {int limit = 10}) =>
      _remember(
          'top:$artistId:$limit',
          () => _inner.artistTopTracks(artistId, limit: limit),
          (l) => l.isEmpty);

  @override
  Future<List<CatalogueAlbum>> artistAlbums(
    String artistId, {
    String? artistName,
    int limit = 200,
  }) =>
      _remember(
          'albums:$artistId:$limit:${artistName ?? ''}',
          () => _inner.artistAlbums(artistId,
              artistName: artistName, limit: limit),
          (l) => l.isEmpty);

  @override
  Future<List<CatalogueTrack>> albumTracks(String albumId) => _remember(
      'tracks:$albumId', () => _inner.albumTracks(albumId), (l) => l.isEmpty);

  @override
  Future<CatalogueGenreChart> genreChart(int genreId) =>
      _inner.genreChart(genreId);
}

class _Remembered {
  _Remembered(this.future);

  final Future<Object?> future;

  /// `null` while the answer is awaited.
  DateTime? until;

  bool expired(DateTime now) => until != null && !now.isBefore(until!);
}
