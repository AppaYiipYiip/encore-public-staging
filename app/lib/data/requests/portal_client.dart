import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

import '../../core/network_policy.dart';
import '../../core/result.dart';

/// What the portal answered to "request this".
@immutable
class RequestReceipt {
  const RequestReceipt({required this.kind, required this.name});

  /// `artist` | `album`.
  final String kind;
  final String name;
}

/// One artist the user asked for, as the portal tracks it.
@immutable
class PortalArtist {
  const PortalArtist({
    required this.id,
    required this.name,
    required this.state,
    this.albums,
    this.tracksHave,
    this.tracksAll,
    this.detail,
    this.candidates = const [],
  });

  final String id;
  final String name;

  /// `waiting` | `added` | `already` | `pick` | `not found` | `error`.
  final String state;
  final int? albums;
  final int? tracksHave;
  final int? tracksAll;
  final String? detail;

  /// Several artists share the name (`state == 'pick'`): the person chooses.
  final List<({String mbid, String label})> candidates;

  bool get isDone =>
      state == 'already' ||
      (tracksAll != null && tracksAll! > 0 && tracksHave == tracksAll);
}

@immutable
class PortalRequest {
  const PortalRequest({
    required this.artist,
    required this.album,
    required this.state,
  });

  final String artist;
  final String? album;
  final String state;
}

/// A Spotify / YouTube Music playlist imported through the portal; it becomes
/// a playlist in the user's account and fills up as the songs arrive.
@immutable
class PortalImport {
  const PortalImport({
    required this.name,
    required this.state,
    this.tracks,
    this.inLibrary,
    this.albums,
    this.albumsRequested,
  });

  final String name;

  /// The portal's own wording ("reading the playlist", "waiting for albums").
  final String state;

  /// Songs in the source playlist, and how many of them the server has now.
  final int? tracks;
  final int? inLibrary;

  /// Albums those songs belong to, and how many were asked for.
  final int? albums;
  final int? albumsRequested;

  bool get hasProgress => tracks != null && tracks! > 0;

  bool get isComplete =>
      hasProgress && inLibrary != null && inLibrary! >= tracks!;

  /// 0..1 share of the songs the server has, `null` while it is still being
  /// read.
  double? get fraction =>
      hasProgress ? ((inLibrary ?? 0) / tracks!).clamp(0.0, 1.0) : null;
}

/// What the portal answered to "import this link".
@immutable
class ImportReceipt {
  const ImportReceipt({required this.kind, required this.name});

  /// `artist` | `playlist`.
  final String kind;
  final String name;
}

@immutable
class PortalOverview {
  const PortalOverview({
    this.user,
    this.artists = const [],
    this.requests = const [],
    this.imports = const [],
  });

  final String? user;
  final List<PortalArtist> artists;
  final List<PortalRequest> requests;
  final List<PortalImport> imports;
}

/// The seam the app uses to ask for music (docs/07-request-pipeline.md).
abstract interface class RequestBackend {
  Future<Result<RequestReceipt>> request({
    required String artist,
    String? album,
  });

  Future<Result<PortalOverview>> overview();

  /// Verifies the address and credentials (Settings "Test connection").
  Future<Result<String>> check();
}

/// Bringing playlists and artists over from Spotify / YouTube Music by link
/// (ADR-050). Separate from [RequestBackend] so a backend that only takes
/// requests stays valid.
abstract interface class ImportBackend {
  Future<Result<ImportReceipt>> importLink({required String url, String? name});

  Future<Result<void>> removeImport(String name);

  /// Forgets an artist that was asked for (it stops being tracked).
  Future<Result<void>> removeArtist(String id);

  /// The portal found several artists with that name; this is the right one.
  Future<Result<void>> pickArtist({required String id, required String mbid});
}

/// The homelab's "playlist-portal" (cookie session, JSON API).
class HomelabPortalClient implements RequestBackend, ImportBackend {
  HomelabPortalClient({
    required Uri baseUrl,
    required String username,
    required String password,
    Dio? dio,
  })  : _base = baseUrl,
        _username = username,
        _password = password,
        _dio = dio ??
            Dio(BaseOptions(
              connectTimeout: const Duration(seconds: 5),
              receiveTimeout: const Duration(seconds: 15),
              validateStatus: (_) => true,
            ));

  final Uri _base;
  final String _username;
  final String _password;
  final Dio _dio;

  String? _cookie;
  bool _loggedIn = false;

  Uri _url(String path, [Map<String, String>? query]) {
    final basePath = _base.path.replaceAll(RegExp(r'/+$'), '');
    return _base.replace(
      path: '$basePath$path',
      queryParameters: query,
      fragment: null,
    );
  }

  Future<void> _login() async {
    // The music login is the password here. Over plain http on a public address
    // it would cross the internet readable by anyone on the path; the address
    // was only checked when typed in a form (docs/23, B25), so the client
    // itself refuses.
    final problem = cleartextProblem(_base);
    if (problem != null) {
      throw UnexpectedFailure('Your password was not sent. $problem');
    }
    final response = await _dio.postUri<Object?>(
      _url('/api/login'),
      data: {'user': _username, 'password': _password},
    );
    if (response.statusCode == 401 || response.statusCode == 403) {
      throw const AuthFailure('The download service did not accept the login');
    }
    if ((response.statusCode ?? 500) >= 400) {
      throw ServerFailure('Login failed (${response.statusCode})',
          statusCode: response.statusCode);
    }
    final setCookie = response.headers.map['set-cookie'];
    _cookie = (setCookie == null || setCookie.isEmpty)
        ? null
        : setCookie.map((c) => c.split(';').first).join('; ');
    _loggedIn = true;
  }

  Future<Response<Object?>> _send(
    String method,
    String path, {
    Object? body,
    Map<String, String>? query,
  }) async {
    Future<Response<Object?>> once() => _dio.requestUri<Object?>(
          _url(path, query),
          data: body,
          options: Options(
            method: method,
            headers: {if (_cookie != null) 'Cookie': _cookie},
          ),
        );

    try {
      if (!_loggedIn) await _login();
      var response = await once();
      if (response.statusCode == 401 || response.statusCode == 403) {
        _loggedIn = false;
        _cookie = null;
        await _login();
        response = await once();
      }
      return response;
    } on DioException catch (error) {
      throw NetworkFailure(
        'Cannot reach the download service at ${_base.host}'
        '${_base.hasPort ? ':${_base.port}' : ''}',
        cause: error,
      );
    }
  }

  @override
  Future<Result<RequestReceipt>> request({
    required String artist,
    String? album,
  }) =>
      guard(() async {
        final response = await _send('POST', '/api/request', body: {
          'artist': artist,
          'album': album ?? '',
        });
        final status = response.statusCode ?? 500;
        if (status >= 400) {
          throw ServerFailure('The request was not accepted ($status)',
              statusCode: status);
        }
        final data = response.data;
        if (data is Map) {
          return RequestReceipt(
            kind: '${data['kind'] ?? (album == null ? 'artist' : 'album')}',
            name: '${data['name'] ?? (album ?? artist)}',
          );
        }
        return RequestReceipt(
          kind: album == null ? 'artist' : 'album',
          name: album ?? artist,
        );
      });

  @override
  Future<Result<PortalOverview>> overview() => guard(() async {
        final response = await _send('GET', '/api/me');
        final status = response.statusCode ?? 500;
        if (status >= 400) {
          throw ServerFailure('Could not read requests ($status)',
              statusCode: status);
        }
        final data = response.data;
        if (data is! Map) return const PortalOverview();
        return parseOverview(data.cast<String, dynamic>());
      });

  @override
  Future<Result<String>> check() => guard(() async {
        final result = await overview();
        final value = result.valueOrNull;
        if (value == null) throw result.failureOrNull!;
        return value.user ?? _username;
      });

  /// The portal's `{error: "..."}` text, or [fallback].
  static String _errorText(Object? data, String fallback) {
    if (data is Map && data['error'] is String) {
      final text = (data['error'] as String).trim();
      if (text.isNotEmpty) return text;
    }
    return fallback;
  }

  @override
  Future<Result<ImportReceipt>> importLink({
    required String url,
    String? name,
  }) =>
      guard(() async {
        final response = await _send('POST', '/api/imports', body: {
          'url': url,
          'name': name ?? '',
        });
        final status = response.statusCode ?? 500;
        if (status >= 400) {
          throw ServerFailure(
            _errorText(response.data, 'The link was not accepted ($status)'),
            statusCode: status,
          );
        }
        final data = response.data;
        final map = data is Map ? data : const <Object?, Object?>{};
        return ImportReceipt(
          kind: '${map['kind'] ?? 'playlist'}',
          name: '${map['name'] ?? name ?? url}',
        );
      });

  @override
  Future<Result<void>> removeImport(String name) => guard(() async {
        final response =
            await _send('DELETE', '/api/imports', query: {'name': name});
        final status = response.statusCode ?? 500;
        if (status >= 400) {
          throw ServerFailure(
            _errorText(response.data, 'Could not remove it ($status)'),
            statusCode: status,
          );
        }
      });

  @override
  Future<Result<void>> removeArtist(String id) => guard(() async {
        final response =
            await _send('DELETE', '/api/artist', query: {'id': id});
        final status = response.statusCode ?? 500;
        if (status >= 400) {
          throw ServerFailure(
            _errorText(response.data, 'Could not remove it ($status)'),
            statusCode: status,
          );
        }
      });

  @override
  Future<Result<void>> pickArtist({
    required String id,
    required String mbid,
  }) =>
      guard(() async {
        final response = await _send('POST', '/api/artist/pick',
            body: {'id': id, 'mbid': mbid});
        final status = response.statusCode ?? 500;
        if (status >= 400) {
          throw ServerFailure(
            _errorText(response.data, 'Could not choose that artist ($status)'),
            statusCode: status,
          );
        }
      });

  /// Public for tests: tolerant mapping of `/api/me`.
  static PortalOverview parseOverview(Map<String, dynamic> json) {
    int? asInt(Object? v) => v is num ? v.toInt() : int.tryParse('$v');

    final artists = <PortalArtist>[
      for (final e in (json['artists'] as List? ?? const []))
        if (e is Map)
          PortalArtist(
            id: '${e['id'] ?? e['mbid'] ?? e['name']}',
            name: '${e['name'] ?? ''}',
            state: '${e['state'] ?? 'waiting'}',
            albums: asInt(e['albums']),
            tracksHave: asInt(e['tracks_have']),
            tracksAll: asInt(e['tracks_all']),
            detail: e['detail'] as String?,
            candidates: [
              for (final c in (e['candidates'] as List? ?? const []))
                if (c is Map && c['mbid'] != null)
                  (mbid: '${c['mbid']}', label: '${c['label'] ?? c['mbid']}'),
            ],
          ),
    ];
    final requests = <PortalRequest>[
      for (final e in (json['requests'] as List? ?? const []))
        if (e is Map)
          PortalRequest(
            artist: '${e['artist'] ?? ''}',
            album: e['album'] as String?,
            state: '${e['state'] ?? 'requested'}',
          ),
    ];
    final imports = <PortalImport>[
      for (final e in (json['imports'] as List? ?? const []))
        if (e is Map)
          PortalImport(
            name: '${e['name'] ?? ''}',
            state: e['status'] is Map
                ? '${(e['status'] as Map)['state'] ?? ''}'
                : '${e['status'] ?? ''}',
            tracks: e['status'] is Map
                ? asInt((e['status'] as Map)['tracks'])
                : null,
            inLibrary: e['status'] is Map
                ? asInt((e['status'] as Map)['in_library'])
                : null,
            albums: e['status'] is Map
                ? asInt((e['status'] as Map)['albums'])
                : null,
            albumsRequested: e['status'] is Map
                ? asInt((e['status'] as Map)['albums_requested'])
                : null,
          ),
    ];
    return PortalOverview(
      user: json['user'] as String?,
      artists: artists,
      requests: requests,
      imports: imports,
    );
  }
}
