import 'dart:convert';
import 'dart:math';

import 'package:crypto/crypto.dart';
import 'package:dio/dio.dart';

import '../../../core/logger.dart';
import '../../../core/result.dart';
import 'json_read.dart';
import 'models.dart';

/// Credentials for token authentication. The password never leaves the device
/// in clear text: requests carry `t = md5(password + salt)` and `s = salt`.
class SubsonicCredentials {
  const SubsonicCredentials({required this.username, required this.password});

  final String username;
  final String password;
}

/// Typed OpenSubsonic API client (ADR-009).
///
/// * Stateless apart from a per-instance salt (so media URLs stay stable
///   within a session) and the list of supported extensions.
/// * Every public call returns a [Result]; nothing throws.
/// * The base URL comes from a callback so the endpoint resolver (LAN /
///   Tailscale / WAN) can change it between calls (ADR-028).
class OpenSubsonicClient {
  OpenSubsonicClient({
    required Dio dio,
    required Uri Function() baseUrl,
    required SubsonicCredentials credentials,
    String clientName = 'Encore',
    String apiVersion = '1.16.1',
    Random? random,
  })  : _dio = dio,
        _baseUrl = baseUrl,
        _credentials = credentials,
        _clientName = clientName,
        _apiVersion = apiVersion,
        _salt = _randomSalt(random ?? Random.secure());

  final Dio _dio;
  final Uri Function() _baseUrl;
  final SubsonicCredentials _credentials;
  final String _clientName;
  final String _apiVersion;
  final String _salt;

  Set<String> _extensions = const {};

  /// OpenSubsonic extension names advertised by the server.
  Set<String> get extensions => _extensions;

  bool get supportsFormPost => _extensions.contains('formPost');

  static String _randomSalt(Random random) {
    const alphabet = 'abcdefghijklmnopqrstuvwxyz0123456789';
    return String.fromCharCodes(
      List.generate(
        12,
        (_) => alphabet.codeUnitAt(random.nextInt(alphabet.length)),
      ),
    );
  }

  // ---------------------------------------------------------------- auth/URLs

  Map<String, String> _authParams() {
    final token =
        md5.convert(utf8.encode('${_credentials.password}$_salt')).toString();
    return {
      'u': _credentials.username,
      't': token,
      's': _salt,
      'v': _apiVersion,
      'c': _clientName,
      'f': 'json',
    };
  }

  /// `u`, `t`, `s`: the token authentication of this session, for companion
  /// services that accept the music server's own login (no password leaves
  /// the phone, and nothing new is stored).
  Map<String, String> authQuery() {
    final p = _authParams();
    return {'u': p['u']!, 't': p['t']!, 's': p['s']!};
  }

  Uri _endpoint(String method, Map<String, Object?> params) {
    final base = _baseUrl();
    final query = <String, List<String>>{};
    void add(String key, Object? value) {
      if (value == null) return;
      if (value is Iterable) {
        for (final v in value) {
          query.putIfAbsent(key, () => []).add(v.toString());
        }
      } else {
        query.putIfAbsent(key, () => []).add(value.toString());
      }
    }

    _authParams().forEach(add);
    params.forEach(add);

    final pairs = <String>[
      for (final e in query.entries)
        for (final v in e.value)
          '${Uri.encodeQueryComponent(e.key)}=${Uri.encodeQueryComponent(v)}',
    ];
    final path = '${base.path.replaceAll(RegExp(r'/+$'), '')}/rest/$method';
    return base.replace(path: path, query: pairs.join('&'));
  }

  /// Streaming URL for the player (token auth, stable within a session).
  Uri streamUrl(
    String id, {
    int? maxBitRate,
    String? format,
    bool estimateContentLength = false,
  }) =>
      _endpoint('stream', {
        'id': id,
        if (maxBitRate != null && maxBitRate > 0) 'maxBitRate': maxBitRate,
        if (format != null && format.isNotEmpty && format != 'raw')
          'format': format,
        if (estimateContentLength) 'estimateContentLength': true,
      });

  /// Original-file download URL.
  Uri downloadUrl(String id) => _endpoint('download', {'id': id});

  /// Cover art URL. Callers must key their image cache on `(server, id, size)`
  /// rather than this URL (ADR-017).
  ///
  /// An Encore server gives a song without a file of its own the catalogue's picture as an address: such an id is its own URL.
  Uri coverArtUrl(String id, {int? size}) => id.startsWith('https://')
      ? Uri.parse(id)
      : _endpoint('getCoverArt', {
          'id': id,
          if (size != null) 'size': size,
        });

  // ------------------------------------------------------------------ calls

  Future<Map<String, dynamic>> _call(
    String method, [
    Map<String, Object?> params = const {},
  ]) async {
    final url = _endpoint(method, params);
    try {
      final Response<Object?> response;
      if (supportsFormPost) {
        // Credentials in the body, not in the URL / server access logs.
        response = await _dio.postUri<Object?>(
          _withoutQuery(url),
          data: url.query,
          options: Options(contentType: Headers.formUrlEncodedContentType),
        );
      } else {
        response = await _dio.getUri<Object?>(url);
      }
      return _unwrap(response);
    } on DioException catch (e) {
      throw _mapDioError(e);
    }
  }

  static Uri _withoutQuery(Uri url) => Uri(
        scheme: url.scheme,
        userInfo: url.userInfo.isEmpty ? null : url.userInfo,
        host: url.host,
        port: url.hasPort ? url.port : null,
        path: url.path,
      );

  Map<String, dynamic> _unwrap(Response<Object?> response) {
    var data = response.data;
    if (data is String) {
      try {
        data = jsonDecode(data);
      } on FormatException catch (e) {
        throw ServerFailure('Server returned a non-JSON response',
            statusCode: response.statusCode, cause: e);
      }
    }
    final root = readMap(readMap(data)?['subsonic-response']);
    if (root == null) {
      throw ServerFailure('Unexpected response (no subsonic-response)',
          statusCode: response.statusCode);
    }
    if (root['status'] != 'ok') {
      final error = readMap(root['error']);
      final code = readInt(error?['code']);
      final message = readString(error?['message']) ?? 'Server error';
      if (code == 40 || code == 41 || code == 42 || code == 44) {
        throw AuthFailure(message);
      }
      if (code == 70) throw NotFoundFailure(message);
      throw ServerFailure(message, serverCode: code);
    }
    return root;
  }

  AppFailure _mapDioError(DioException e) {
    final status = e.response?.statusCode;
    // `DioExceptionType` gained members across 5.x releases, so match by name
    // for the timeout family instead of an exhaustive switch.
    if (e.type.name.toLowerCase().contains('timeout')) {
      return NetworkFailure('Connection timed out', cause: e);
    }
    switch (e.type) {
      case DioExceptionType.connectionError:
        return NetworkFailure('Cannot reach the server', cause: e);
      case DioExceptionType.badCertificate:
        return NetworkFailure('Certificate not trusted', cause: e);
      case DioExceptionType.cancel:
        return const CancelledFailure();
      case DioExceptionType.badResponse:
        if (status == 401 || status == 403) {
          return AuthFailure('Not authorised', cause: e);
        }
        if (status == 404) {
          return NotFoundFailure('Not found', cause: e);
        }
        return ServerFailure('Server error ($status)',
            statusCode: status, cause: e);
      default:
        return NetworkFailure('Network error', cause: e);
    }
  }

  // ---------------------------------------------------------- API methods

  Future<Result<SsPing>> ping() => guard(() async {
        final root = await _call('ping');
        return SsPing.fromJson(root);
      });

  /// Detects OpenSubsonic extensions and remembers them (e.g. `formPost`).
  Future<Result<Set<String>>> loadExtensions() => guard(() async {
        try {
          final root = await _call('getOpenSubsonicExtensions');
          _extensions = {
            for (final e in readObjectList(root['openSubsonicExtensions']))
              if (readString(e['name']) != null) readString(e['name'])!,
          };
        } on NotFoundFailure {
          _extensions = const {};
        } on ServerFailure catch (e) {
          // Plain Subsonic servers answer "unknown method".
          Log.debug('opensubsonic', 'extensions unavailable: ${e.message}');
          _extensions = const {};
        }
        return _extensions;
      });

  Future<Result<SsScanStatus>> getScanStatus() => guard(() async {
        final root = await _call('getScanStatus');
        return SsScanStatus.fromJson(readMap(root['scanStatus']) ?? const {});
      });

  /// Whether [username] administers the server (`getUser`): an administrator
  /// sees every library and may manage accounts, so the app only offers the
  /// old "make an account for them" invitation to one.
  Future<Result<bool>> isAdministrator(String username) => guard(() async {
        final root = await _call('getUser', {'username': username});
        return readMap(root['user'])?['adminRole'] == true;
      });

  /// Triggers a library scan (admin permission on most servers).
  Future<Result<void>> startScan() => guard(() async {
        await _call('startScan');
      });

  Future<Result<List<SsArtist>>> getArtists() => guard(() async {
        final root = await _call('getArtists');
        final indexes = readObjectList(readMap(root['artists'])?['index']);
        return [
          for (final index in indexes)
            for (final a in readObjectList(index['artist']))
              SsArtist.fromJson(a),
        ];
      });

  Future<Result<List<SsAlbum>>> getAlbumList2({
    String type = 'alphabeticalByName',
    int size = 500,
    int offset = 0,
  }) =>
      guard(() async {
        final root = await _call('getAlbumList2', {
          'type': type,
          'size': size,
          'offset': offset,
        });
        return [
          for (final a in readObjectList(readMap(root['albumList2'])?['album']))
            SsAlbum.fromJson(a),
        ];
      });

  Future<Result<SsSong>> getSong(String id) => guard(() async {
        final root = await _call('getSong', {'id': id});
        final song = readMap(root['song']);
        if (song == null) throw const NotFoundFailure('Song not found');
        return SsSong.fromJson(song);
      });

  Future<Result<SsAlbum>> getAlbum(String id) => guard(() async {
        final root = await _call('getAlbum', {'id': id});
        final album = readMap(root['album']);
        if (album == null) throw const NotFoundFailure('Album not found');
        return SsAlbum.fromJson(album);
      });

  /// `search3`; an empty [query] dumps the library page by page on
  /// Navidrome (verified on 0.64.2) and other servers that follow the
  /// "empty query lists everything" convention.
  Future<Result<SsSearchPage>> search3({
    String query = '',
    int artistCount = 0,
    int artistOffset = 0,
    int albumCount = 0,
    int albumOffset = 0,
    int songCount = 0,
    int songOffset = 0,
  }) =>
      guard(() async {
        final root = await _call('search3', {
          'query': query,
          'artistCount': artistCount,
          'artistOffset': artistOffset,
          'albumCount': albumCount,
          'albumOffset': albumOffset,
          'songCount': songCount,
          'songOffset': songOffset,
        });
        return SsSearchPage.fromJson(
            readMap(root['searchResult3']) ?? const {});
      });

  Future<Result<List<SsPlaylist>>> getPlaylists() => guard(() async {
        final root = await _call('getPlaylists');
        return [
          for (final p
              in readObjectList(readMap(root['playlists'])?['playlist']))
            SsPlaylist.fromJson(p),
        ];
      });

  Future<Result<SsPlaylist>> getPlaylist(String id) => guard(() async {
        final root = await _call('getPlaylist', {'id': id});
        final playlist = readMap(root['playlist']);
        if (playlist == null) throw const NotFoundFailure('Playlist not found');
        return SsPlaylist.fromJson(playlist);
      });

  Future<Result<SsStarred>> getStarred2() => guard(() async {
        final root = await _call('getStarred2');
        final s = readMap(root['starred2']) ?? const {};
        return SsStarred(
          artists: [
            for (final a in readObjectList(s['artist'])) SsArtist.fromJson(a),
          ],
          albums: [
            for (final a in readObjectList(s['album'])) SsAlbum.fromJson(a),
          ],
          songs: [
            for (final a in readObjectList(s['song'])) SsSong.fromJson(a),
          ],
        );
      });

  Future<Result<void>> star({
    List<String> songIds = const [],
    List<String> albumIds = const [],
    List<String> artistIds = const [],
  }) =>
      guard(() async {
        await _call('star', {
          'id': songIds,
          'albumId': albumIds,
          'artistId': artistIds,
        });
      });

  Future<Result<void>> unstar({
    List<String> songIds = const [],
    List<String> albumIds = const [],
    List<String> artistIds = const [],
  }) =>
      guard(() async {
        await _call('unstar', {
          'id': songIds,
          'albumId': albumIds,
          'artistId': artistIds,
        });
      });

  Future<Result<void>> setRating(String id, int rating) => guard(() async {
        await _call('setRating', {'id': id, 'rating': rating.clamp(0, 5)});
      });

  /// Registers a play. [timeMs] backdates the event (offline plays replayed
  /// from the outbox).
  Future<Result<void>> scrobble(
    String id, {
    bool submission = true,
    int? timeMs,
  }) =>
      guard(() async {
        await _call('scrobble', {
          'id': id,
          'submission': submission,
          if (timeMs != null) 'time': timeMs,
        });
      });

  /// Creates a playlist and returns the id the server gave it (`null` when
  /// the server's answer does not carry one).
  Future<Result<String?>> createPlaylist({
    required String name,
    List<String> songIds = const [],
  }) =>
      guard(() async {
        final root =
            await _call('createPlaylist', {'name': name, 'songId': songIds});
        final id = readMap(root['playlist'])?['id'];
        return id == null ? null : '$id';
      });

  Future<Result<void>> updatePlaylist({
    required String playlistId,
    String? name,
    String? comment,
    bool? isPublic,
    List<String> songIdsToAdd = const [],
    List<int> songIndexesToRemove = const [],
  }) =>
      guard(() async {
        await _call('updatePlaylist', {
          'playlistId': playlistId,
          if (name != null) 'name': name,
          if (comment != null) 'comment': comment,
          if (isPublic != null) 'public': isPublic,
          'songIdToAdd': songIdsToAdd,
          'songIndexToRemove': songIndexesToRemove,
        });
      });

  Future<Result<void>> deletePlaylist(String id) => guard(() async {
        await _call('deletePlaylist', {'id': id});
      });

  Future<Result<List<SsSong>>> getSimilarSongs2(String id, {int count = 30}) =>
      guard(() async {
        final root =
            await _call('getSimilarSongs2', {'id': id, 'count': count});
        return [
          for (final s
              in readObjectList(readMap(root['similarSongs2'])?['song']))
            SsSong.fromJson(s),
        ];
      });

  Future<Result<List<SsSong>>> getTopSongs(String artist, {int count = 20}) =>
      guard(() async {
        final root =
            await _call('getTopSongs', {'artist': artist, 'count': count});
        return [
          for (final s in readObjectList(readMap(root['topSongs'])?['song']))
            SsSong.fromJson(s),
        ];
      });

  /// Structured (possibly time-synced) lyrics for a song, or `null`.
  Future<Result<SsLyrics?>> getLyricsBySongId(String id) => guard(() async {
        final root = await _call('getLyricsBySongId', {'id': id});
        final list =
            readObjectList(readMap(root['lyricsList'])?['structuredLyrics']);
        if (list.isEmpty) return null;
        // Prefer a synced variant when the server offers several.
        final chosen = list.firstWhere(
          (l) => readBool(l['synced']),
          orElse: () => list.first,
        );
        final lines = [
          for (final l in readObjectList(chosen['line']))
            SsLyricLine(
              startMs: readInt(l['start']) ?? 0,
              text: readString(l['value']) ?? '',
            ),
        ];
        if (lines.isEmpty) return null;
        return SsLyrics(
          lines: lines,
          synced: readBool(chosen['synced']),
          lang: readString(chosen['lang']),
        );
      });
}
