import 'package:dio/dio.dart';

import '../../core/result.dart';
import '../api/opensubsonic/json_read.dart';
import 'encore_models.dart';

/// The Encore server's own API (docs/17): song refs, the person's library, playlists, plays.
///
/// Like the music server's client it is stateless, returns a [Result] from every call and takes its address from a callback (so the
/// endpoint resolver can move it between a home address and a public one). Requests carry the music server's token login (`u`, `t`, `s`),
/// which the Encore server checks with the music server: nothing new is stored on the phone.
class EncoreApi {
  EncoreApi({
    required Dio dio,
    required Uri Function() baseUrl,
    required Map<String, String> Function() auth,
    this.deviceId,
  })  : _dio = dio,
        _baseUrl = baseUrl,
        _auth = auth;

  final Dio _dio;
  final Uri Function() _baseUrl;
  final Map<String, String> Function() _auth;

  /// This device's id on the server (`dv_...`), once signed in: lets the server tell a change made here from one made elsewhere.
  String? deviceId;

  static const String _prefix = '/encore/api/v1';

  Uri _uri(String path, [Map<String, Object?> query = const {}]) {
    final base = _baseUrl();
    final pairs = <String>[
      for (final e in {
        ..._auth(),
        for (final q in query.entries)
          if (q.value != null) q.key: '${q.value}'
      }.entries)
        '${Uri.encodeQueryComponent(e.key)}=${Uri.encodeQueryComponent(e.value)}',
    ];
    return base.replace(
        path: '${base.path.replaceAll(RegExp(r'/+$'), '')}$_prefix$path',
        query: pairs.join('&'));
  }

  Options get _options =>
      Options(headers: {if (deviceId != null) 'X-Encore-Device': deviceId});

  Future<Map<String, dynamic>> _send(String method, String path,
      {Map<String, Object?> query = const {}, Object? body}) async {
    try {
      final response = await _dio.requestUri<Object?>(
        _uri(path, query),
        data: body,
        options: _options.copyWith(
            method: method,
            contentType: body == null ? null : Headers.jsonContentType),
      );
      return readMap(response.data) ?? const {};
    } on DioException catch (e) {
      throw _failure(e);
    }
  }

  /// The server's one error shape (`{"error": {code, message, retryable, retryAfterMs}}`) as the app's failure types, one to one.
  static AppFailure _failure(DioException e) {
    final status = e.response?.statusCode;
    final error = readMap(readMap(e.response?.data)?['error']);
    final code = readString(error?['code']);
    final message = readString(error?['message']);
    if (error != null && code != null) {
      switch (code) {
        case 'unauthorized':
        case 'forbidden':
          return AuthFailure(message ?? 'Sign in again.', cause: e);
        case 'not_found':
          return NotFoundFailure(message ?? 'Not found.', cause: e);
        default:
          return ServerFailure(message ?? 'The server could not do that.',
              statusCode: status, code: code, cause: e);
      }
    }
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
        if (status == 404) return NotFoundFailure('Not found', cause: e);
        return ServerFailure('Server error ($status)',
            statusCode: status, cause: e);
      default:
        return NetworkFailure('Network error', cause: e);
    }
  }

  // ------------------------------------------------------------------ the server and the person

  /// What this server is. Answered without a login, so it also tells whether the address is an Encore server at all.
  Future<Result<EncoreInfo>> info() =>
      guard(() async => EncoreInfo.fromJson(await _send('GET', '/info')));

  /// Signs in once for a device token (the live channel authenticates with it). The password is turned into a token by the server's
  /// check and not kept there.
  Future<Result<EncoreDeviceLogin>> login({
    required String username,
    required String password,
    String deviceName = 'Phone',
    String? appVersion,
  }) =>
      guard(() async {
        // The token login does not apply here: this call carries the password itself, over the same address.
        final response = await _dio.postUri<Object?>(
          _baseUrl().replace(
              path:
                  '${_baseUrl().path.replaceAll(RegExp(r'/+$'), '')}$_prefix/auth/login',
              query: ''),
          data: {
            'username': username,
            'password': password,
            'deviceName': deviceName,
            'deviceKind': 'phone',
            if (appVersion != null) 'appVersion': appVersion,
          },
          options: Options(contentType: Headers.jsonContentType),
        );
        return EncoreDeviceLogin.fromJson(readMap(response.data) ?? const {});
      });

  // ------------------------------------------------------------------ songs

  /// Gives songs a ref each (finds the one the server already has: same recording, same ref for everybody). In the order asked.
  Future<Result<List<EncoreRef>>> resolve(List<Map<String, Object?>> songs) =>
      guard(() async {
        final body =
            await _send('POST', '/refs/resolve', body: {'songs': songs});
        return [
          for (final r in readObjectList(body['items'])) EncoreRef.fromJson(r)
        ];
      });

  Future<Result<EncoreRef>> ref(String id) =>
      guard(() async => EncoreRef.fromJson(await _send('GET', '/refs/$id')));

  /// The address to play a song from the server's stream (signed, valid for hours): for songs it does not keep.
  Future<Result<Uri>> streamUrl(String refId) => guard(() async {
        final body = await _send('GET', '/refs/$refId/stream-url');
        final url = readString(body['url']);
        if (url == null) {
          throw const ServerFailure('The server gave no stream address.');
        }
        final base = _baseUrl();
        return Uri.parse(url).isAbsolute ? Uri.parse(url) : base.resolve(url);
      });

  // ------------------------------------------------------------------ the library

  Future<Result<EncoreChanges>> changes({required String since}) =>
      guard(() async => EncoreChanges.fromJson(
          await _send('GET', '/library/changes', query: {'since': since})));

  Future<Result<EncoreFiles>> files({required String since, int limit = 500}) =>
      guard(() async => EncoreFiles.fromJson(await _send(
          'GET', '/library/files',
          query: {'since': since, 'limit': limit})));

  Future<Result<void>> like(String refId, {int? atMs}) => guard(() async =>
      _send('PUT', '/likes/$refId', body: {if (atMs != null) 'at': atMs}));

  Future<Result<void>> unlike(String refId) =>
      guard(() async => _send('DELETE', '/likes/$refId'));

  Future<Result<void>> saveAlbum(String albumId) =>
      guard(() async => _send('PUT', '/saved-albums/$albumId', body: const {}));

  Future<Result<void>> unsaveAlbum(String albumId) =>
      guard(() async => _send('DELETE', '/saved-albums/$albumId'));

  Future<Result<void>> follow(String artistId) =>
      guard(() async => _send('PUT', '/follows/$artistId', body: const {}));

  Future<Result<void>> unfollow(String artistId) =>
      guard(() async => _send('DELETE', '/follows/$artistId'));

  // ------------------------------------------------------------------ playlists (every write carries ids the phone made: a retry is harmless)

  Future<Result<void>> createPlaylist(String id, String name) => guard(
      () async => _send('POST', '/playlists', body: {'id': id, 'name': name}));

  Future<Result<void>> renamePlaylist(String id, String name) =>
      guard(() async => _send('PATCH', '/playlists/$id', body: {'name': name}));

  Future<Result<void>> deletePlaylist(String id) =>
      guard(() async => _send('DELETE', '/playlists/$id'));

  /// Adds songs at the end, or after the entry [after]. Each is `(ref, entryId)`.
  Future<Result<void>> addEntries(
          String playlistId, List<({String ref, String entryId})> songs,
          {String? after}) =>
      guard(
        () async => _send('POST', '/playlists/$playlistId/entries', body: {
          'songs': [
            for (final s in songs) {'ref': s.ref, 'id': s.entryId},
          ],
          if (after != null) 'after': after,
        }),
      );

  Future<Result<void>> removeEntries(
          String playlistId, List<String> entryIds) =>
      guard(() async => _send('DELETE', '/playlists/$playlistId/entries',
          body: {'entryIds': entryIds}));

  Future<Result<void>> reorder(String playlistId, List<String> entryIds) =>
      guard(() async => _send('PUT', '/playlists/$playlistId/order',
          body: {'entryIds': entryIds}));

  // ------------------------------------------------------------------ moving over

  /// Asks the server to bring this person's stars and playlists over from the music server, as them (the sign-in rides in the body).
  /// Safe to repeat.
  Future<Result<EncoreMigrationReport>> migrateFromNavidrome() =>
      guard(() async {
        final body =
            await _send('POST', '/migrate/navidrome', body: {..._auth()});
        return EncoreMigrationReport.fromJson(
            readMap(body['report']) ?? const {});
      });

  // ------------------------------------------------------------------ plays

  /// One listening, for history, "recently played", Year in Music and recommendations. [id] is made by the phone: a retried report is one play.
  Future<Result<void>> play({
    required String id,
    required String refId,
    required int atMs,
    required int msPlayed,
    String? context,
  }) =>
      guard(() async => _send('POST', '/plays', body: {
            'id': id,
            'ref': refId,
            'at': atMs,
            'msPlayed': msPlayed,
            if (context != null) 'context': context,
          }));
}
