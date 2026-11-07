import 'package:dio/dio.dart';

import '../../core/logger.dart';
import 'catalogue_models.dart';

/// Catalogue lookup on Deezer's public API (ADR-015/ADR-016).
///
/// No account or key is needed for search, responses are
/// small and fast (~300 ms), and covers are 1000 px. Failures never throw to
/// the UI: an unreachable catalogue just means "no extra results".
class DeezerClient implements CatalogueClient {
  DeezerClient({Dio? dio})
      : _dio = dio ??
            Dio(BaseOptions(
              baseUrl: 'https://api.deezer.com',
              connectTimeout: const Duration(seconds: 5),
              receiveTimeout: const Duration(seconds: 8),
              headers: const {'User-Agent': 'Encore/0.1'},
            ));

  final Dio _dio;

  Future<Map<String, dynamic>?> _get(
    String path, [
    Map<String, Object?> query = const {},
  ]) async {
    try {
      final response = await _dio.get<Object?>(
        path,
        queryParameters: {
          for (final e in query.entries)
            if (e.value != null) e.key: e.value,
        },
      );
      final data = response.data;
      if (data is! Map) return null;
      final map = data.cast<String, dynamic>();
      // Deezer reports errors with HTTP 200.
      if (map['error'] != null) {
        Log.warn('catalogue', 'Deezer error on $path: ${map['error']}');
        return null;
      }
      return map;
    } on DioException catch (error) {
      Log.debug('catalogue', 'Deezer $path failed: ${error.type.name}');
      return null;
    }
  }

  @override
  Future<CatalogueResults> search(String query, {int limit = 8}) async {
    final q = query.trim();
    if (q.length < 2) return CatalogueResults.empty;
    final results = await Future.wait([
      _get('/search/artist', {'q': q, 'limit': 8}),
      _get('/search/album', {'q': q, 'limit': limit}),
      _get('/search/track', {'q': q, 'limit': limit}),
    ]);
    return CatalogueResults(
      artists:
          _list(results[0]).map(_artist).whereType<CatalogueArtist>().toList(),
      albums:
          _list(results[1]).map(_album).whereType<CatalogueAlbum>().toList(),
      tracks:
          _list(results[2]).map(_track).whereType<CatalogueTrack>().toList(),
    );
  }

  @override
  Future<List<CatalogueArtist>> searchArtists(String query,
      {int limit = 5}) async {
    final q = query.trim();
    if (q.length < 2) return const [];
    final json = await _get('/search/artist', {'q': q, 'limit': limit});
    return _list(json).map(_artist).whereType<CatalogueArtist>().toList();
  }

  @override
  Future<CatalogueArtist?> artist(String artistId) async {
    final json = await _get('/artist/$artistId');
    return json == null ? null : _artist(json);
  }

  @override
  Future<CatalogueAlbum?> album(String albumId) async {
    final json = await _get('/album/$albumId');
    return json == null ? null : _album(json);
  }

  @override
  Future<List<CatalogueTrack>> artistTopTracks(String artistId,
      {int limit = 10}) async {
    final json = await _get('/artist/$artistId/top', {'limit': limit});
    return _list(json).map(_track).whereType<CatalogueTrack>().toList();
  }

  @override
  Future<List<CatalogueAlbum>> artistAlbums(
    String artistId, {
    String? artistName,
    int limit = 200,
  }) async {
    final json = await _get('/artist/$artistId/albums', {'limit': limit});
    return [
      for (final j in _list(json))
        _album(j, fallbackArtistName: artistName, fallbackArtistId: artistId),
    ].whereType<CatalogueAlbum>().toList();
  }

  @override
  Future<CatalogueGenreChart> genreChart(int genreId) async {
    final results = await Future.wait([
      _get('/chart/$genreId/tracks', {'limit': 25}),
      _get('/chart/$genreId/artists', {'limit': 15}),
      _get('/chart/$genreId/albums', {'limit': 15}),
    ]);
    return CatalogueGenreChart(
      tracks:
          _list(results[0]).map(_track).whereType<CatalogueTrack>().toList(),
      artists:
          _list(results[1]).map(_artist).whereType<CatalogueArtist>().toList(),
      albums:
          _list(results[2]).map(_album).whereType<CatalogueAlbum>().toList(),
    );
  }

  @override
  Future<List<CatalogueTrack>> albumTracks(String albumId) async {
    final json = await _get('/album/$albumId/tracks', {'limit': 100});
    final tracks = _list(json);
    if (tracks.isEmpty) return const [];
    // /album/{id}/tracks omits the album object; fetch the cover once.
    final album = await _get('/album/$albumId');
    final cover = album?['cover_xl'] as String? ??
        album?['cover_big'] as String? ??
        album?['cover'] as String?;
    final title = album?['title'] as String?;
    return [
      for (final t in tracks)
        _track(t, fallbackCover: cover, fallbackAlbum: title, albumId: albumId),
    ].whereType<CatalogueTrack>().toList();
  }

  // ---------------------------------------------------------------- mapping

  static List<Map<String, dynamic>> _list(Map<String, dynamic>? json) {
    final data = json?['data'];
    if (data is! List) return const [];
    return [
      for (final e in data)
        if (e is Map) e.cast<String, dynamic>(),
    ];
  }

  static String? _str(Object? v) => v is String && v.isNotEmpty ? v : null;

  static CatalogueArtist? _artist(Map<String, dynamic> j) {
    final id = j['id'];
    final name = _str(j['name']);
    if (id == null || name == null) return null;
    return CatalogueArtist(
      id: '$id',
      name: name,
      imageUrl:
          _str(j['picture_xl']) ?? _str(j['picture_big']) ?? _str(j['picture']),
      fans: (j['nb_fan'] as num?)?.toInt(),
      albumCount: (j['nb_album'] as num?)?.toInt(),
    );
  }

  static CatalogueAlbum? _album(
    Map<String, dynamic> j, {
    String? fallbackArtistName,
    String? fallbackArtistId,
  }) {
    final id = j['id'];
    final title = _str(j['title']);
    final artist = j['artist'];
    final artistName = artist is Map ? _str(artist['name']) : null;
    if (id == null || title == null) return null;
    final date = _str(j['release_date']);
    return CatalogueAlbum(
      id: '$id',
      title: title,
      artistName: artistName ?? fallbackArtistName ?? 'Unknown artist',
      artistId: artist is Map && artist['id'] != null
          ? '${artist['id']}'
          : fallbackArtistId,
      coverUrl: _str(j['cover_xl']) ?? _str(j['cover_big']) ?? _str(j['cover']),
      trackCount: (j['nb_tracks'] as num?)?.toInt(),
      year: date != null && date.length >= 4
          ? int.tryParse(date.substring(0, 4))
          : null,
      recordType: _str(j['record_type']),
      releaseDate: date,
    );
  }

  static CatalogueTrack? _track(
    Map<String, dynamic> j, {
    String? fallbackCover,
    String? fallbackAlbum,
    String? albumId,
  }) {
    final id = j['id'];
    final title = _str(j['title']);
    final artist = j['artist'];
    final album = j['album'];
    if (id == null || title == null) return null;
    final seconds = (j['duration'] as num?)?.toInt();
    return CatalogueTrack(
      id: '$id',
      title: title,
      artistName:
          (artist is Map ? _str(artist['name']) : null) ?? 'Unknown artist',
      artistId:
          artist is Map && artist['id'] != null ? '${artist['id']}' : null,
      albumTitle: (album is Map ? _str(album['title']) : null) ?? fallbackAlbum,
      albumId: album is Map && album['id'] != null ? '${album['id']}' : albumId,
      coverUrl: (album is Map
              ? (_str(album['cover_xl']) ??
                  _str(album['cover_big']) ??
                  _str(album['cover']))
              : null) ??
          fallbackCover,
      duration: seconds == null ? null : Duration(seconds: seconds),
      isrc: _str(j['isrc']),
      trackNumber: (j['track_position'] as num?)?.toInt(),
      discNumber: (j['disk_number'] as num?)?.toInt(),
    );
  }
}
