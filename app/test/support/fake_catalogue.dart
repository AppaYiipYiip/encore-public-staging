import 'package:encore/data/catalogue/catalogue_models.dart';

/// Scriptable catalogue for tests: canned search results plus per-id
/// artist / album / track lookups, and counters to assert on traffic.
class FakeCatalogue implements CatalogueClient {
  FakeCatalogue([this.results = CatalogueResults.empty]);

  /// Search hits made of albums only (cover-fallback tests).
  FakeCatalogue.withAlbums(List<CatalogueAlbum> albums)
      : results = CatalogueResults(albums: albums);

  CatalogueResults results;
  final List<String> queries = [];
  int get searches => queries.length;

  final Map<String, CatalogueArtist> artistsById = {};
  final Map<String, CatalogueAlbum> albumsById = {};
  final Map<String, List<CatalogueTrack>> topTracksByArtist = {};
  final Map<String, List<CatalogueAlbum>> albumsByArtist = {};
  final Map<String, List<CatalogueTrack>> tracksByAlbum = {};
  final Map<int, CatalogueGenreChart> genreCharts = {};

  /// `artist:ID`, `album:ID`, `top:ID`, `albums:ID`, `tracks:ID` per call.
  final List<String> lookups = [];

  set albums(List<CatalogueAlbum> value) =>
      results = CatalogueResults(albums: value);

  @override
  Future<CatalogueResults> search(String query, {int limit = 8}) async {
    queries.add(query);
    return results;
  }

  @override
  Future<CatalogueArtist?> artist(String artistId) async {
    lookups.add('artist:$artistId');
    return artistsById[artistId];
  }

  @override
  Future<CatalogueAlbum?> album(String albumId) async {
    lookups.add('album:$albumId');
    return albumsById[albumId];
  }

  @override
  Future<List<CatalogueTrack>> artistTopTracks(String artistId,
      {int limit = 10}) async {
    lookups.add('top:$artistId');
    return topTracksByArtist[artistId] ?? const [];
  }

  @override
  Future<List<CatalogueAlbum>> artistAlbums(
    String artistId, {
    String? artistName,
    int limit = 50,
  }) async {
    lookups.add('albums:$artistId');
    return albumsByArtist[artistId] ?? const [];
  }

  @override
  Future<CatalogueGenreChart> genreChart(int genreId) async {
    lookups.add('genre:$genreId');
    return genreCharts[genreId] ?? CatalogueGenreChart.empty;
  }

  @override
  Future<List<CatalogueTrack>> albumTracks(String albumId) async {
    lookups.add('tracks:$albumId');
    return tracksByAlbum[albumId] ?? const [];
  }
}
