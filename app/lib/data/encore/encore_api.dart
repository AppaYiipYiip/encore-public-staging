import 'package:dio/dio.dart';

import '../../core/result.dart';
import '../api/opensubsonic/json_read.dart';
import 'encore_models.dart';
import 'signed_addresses.dart';

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
    DateTime Function() clock = DateTime.now,
  })  : _dio = dio,
        _baseUrl = baseUrl,
        _auth = auth,
        _clock = clock;

  final Dio _dio;
  final Uri Function() _baseUrl;
  final Map<String, String> Function() _auth;
  final DateTime Function() _clock;

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
      final parsed = readMap(response.data);
      // A page (the sign-in page of a cafe's Wi-Fi) is not an answer: reading "nothing" from it made an owner a guest with an empty library.
      if (parsed == null &&
          response.data is String &&
          (response.data as String).trim().isNotEmpty) {
        throw const NetworkFailure(
            'This address did not answer like your server');
      }
      return parsed ?? const {};
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
          return NotFoundFailure(message ?? 'Not found.',
              unknownRef: readString(readMap(error['details'])?['ref']),
              cause: e);
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
        // The server's own refusals carry its error shape (handled above). A bare 401 or 403 is somebody else's page, for instance a
        // Wi-Fi sign-in: not a reason to ask the person for the password again.
        if (status == 401 || status == 403) {
          return NetworkFailure('This address did not answer like your server',
              cause: e);
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

  /// The addresses this server says it has (signed in): the home one and the one over the internet.
  Future<Result<EncoreServerAddresses>> server() => guard(() async =>
      EncoreServerAddresses.fromJson(await _send('GET', '/server')));

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
        try {
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
        } on DioException catch (e) {
          // A refused password is an AuthFailure like everywhere else (not an unexpected error): callers must tell it from a busy server.
          throw _failure(e);
        }
      });

  /// Ends this phone's device on the server (`X-Encore-Device` names it; the music server's login proves who is asking). Only the person's own
  /// device can be ended this way.
  Future<Result<void>> logout() =>
      guard(() async => _send('POST', '/auth/logout'));

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

  /// The address to play a song from (signed, valid for hours), and when it stops working. The server picks where the audio comes from: its own
  /// kept file when it has one, YouTube otherwise.
  Future<Result<SignedAddress>> streamAddress(String refId) => guard(() async {
        final body = await _send('GET', '/refs/$refId/stream-url');
        final url = readString(body['url']);
        if (url == null) {
          throw const ServerFailure('The server gave no stream address.');
        }
        final base = _baseUrl();
        final address =
            Uri.parse(url).isAbsolute ? Uri.parse(url) : base.resolve(url);
        return SignedAddress(address, _expiry(body));
      });

  // ------------------------------------------------------------------ the bell

  /// The person's news, newest first (`GET /notifications`); with [since] only what is newer than the cursor the last answer gave.
  Future<Result<EncoreNewsList>> notifications(
          {String? since, int limit = 50}) =>
      guard(() async => EncoreNewsList.fromJson(await _send(
          'GET', '/notifications',
          query: {if (since != null) 'since': since, 'limit': limit})));

  /// Marks the news read, all of it or up to [upTo]; answers how many are still unread.
  Future<Result<int>> markNewsRead({int? upTo}) => guard(() async {
        final body = await _send('POST', '/notifications/read',
            body: {if (upTo != null) 'upTo': upTo});
        return readInt(body['unread']) ?? 0;
      });

  Future<Result<Uri>> streamUrl(String refId) =>
      streamAddress(refId).then((r) => r.map((a) => a.url));

  /// One ticket for every picture of the server, valid for days (`GET /covers/pass`).
  Future<Result<CoverPass>> coverPass() => guard(() async {
        final body = await _send('GET', '/covers/pass');
        final ticket = readMap(body['pass']);
        final person = readString(ticket?['p']);
        final signature = readString(ticket?['sig']);
        if (person == null || signature == null) {
          throw const ServerFailure('The server gave no ticket for pictures.');
        }
        return CoverPass(
            person: person, signature: signature, expiresAt: _expiry(body));
      });

  /// When an address stops working, counted by this phone's own clock: the server says when (`expiresAt`) and what time it is (`serverTime`),
  /// and what is left is the difference, so a phone whose clock is hours out does not keep an address that has run out (or drop one that
  /// has not). Without the server's time the date is taken as given; without any date the address is taken as run out, so it is asked again.
  DateTime _expiry(Map<String, dynamic> body) {
    final expires = readInt(body['expiresAt']);
    if (expires == null) {
      return DateTime.fromMillisecondsSinceEpoch(0, isUtc: true);
    }
    final serverNow = readInt(body['serverTime']);
    if (serverNow == null) {
      return DateTime.fromMillisecondsSinceEpoch(expires, isUtc: true);
    }
    return _clock().add(Duration(milliseconds: expires - serverNow));
  }

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

  /// Saves a release the server may not hold yet and names the songs the phone resolved for it: the server records the save and keeps those
  /// songs in the background, first in line, whether or not the phone stays (D-21, docs/17 "Saving a release"). All or nothing: a song the
  /// server does not know refuses the whole call. Safe to repeat.
  Future<Result<EncoreReleaseSave>> saveRelease(
          String releaseId, List<String> refIds) =>
      guard(() async => EncoreReleaseSave.fromJson(await _send(
          'PUT', '/saved-albums/${Uri.encodeComponent(releaseId)}',
          body: {'refs': refIds})));

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

  // ------------------------------------------------------------------ people and invitations

  /// Who the server says this person is.
  Future<Result<EncoreMe>> me() =>
      guard(() async => EncoreMe.fromJson(await _send('GET', '/me')));

  /// Makes a one-person invitation (an owner's call). The code is in the answer once and nowhere else.
  Future<Result<EncoreInvite>> createInvite(
          {String role = 'member', String? note}) =>
      guard(() async {
        final body = await _send('POST', '/invites',
            body: {'role': role, if (note != null) 'note': note});
        return EncoreInvite.fromJson(readMap(body['invite']) ?? const {});
      });

  Future<Result<List<EncoreInvite>>> invites() => guard(() async {
        final body = await _send('GET', '/invites');
        return [
          for (final i in readObjectList(body['items']))
            EncoreInvite.fromJson(i)
        ];
      });

  Future<Result<void>> revokeInvite(String id) =>
      guard(() async => _send('DELETE', '/invites/$id'));

  Future<Result<List<EncorePerson>>> people() => guard(() async {
        final body = await _send('GET', '/people');
        return [
          for (final p in readObjectList(body['items']))
            EncorePerson.fromJson(p)
        ];
      });

  Future<Result<void>> updatePerson(String id, {String? role, bool? locked}) =>
      guard(() async => _send('PATCH', '/people/$id', body: {
            if (role != null) 'role': role,
            if (locked != null) 'locked': locked,
          }));

  Future<Result<void>> removePerson(String id) =>
      guard(() async => _send('DELETE', '/people/$id'));

  // ------------------------------------------------------------------ imports

  /// Brings a playlist over: [url] is read by the server, or [songs] (a file the phone parsed) are given with a [name]. The playlist exists
  /// when this answers, every song with its ref; finding and keeping the songs carries on in the background. [id] is made by the phone, so
  /// a retried request is one import. With [liked] every song is liked and no playlist is made.
  Future<Result<EncoreImportMade>> createImport({
    required String id,
    String? url,
    String? name,
    String? source,
    List<Map<String, Object?>>? songs,
    bool liked = false,
  }) =>
      guard(() async => EncoreImportMade.fromJson(await _send(
            'POST',
            '/imports',
            body: {
              'id': id,
              if (url != null) 'url': url,
              if (name != null) 'name': name,
              if (source != null) 'source': source,
              if (songs != null) 'songs': songs,
              if (liked) 'liked': true,
            },
          )));

  Future<Result<List<EncoreImport>>> imports() => guard(() async {
        final body = await _send('GET', '/imports');
        return [
          for (final i in readObjectList(body['imports']))
            EncoreImport.fromJson(i)
        ];
      });

  Future<Result<EncoreImport>> stopImport(String id) =>
      guard(() async => EncoreImport.fromJson(
          readMap((await _send('POST', '/imports/$id/stop'))['import']) ??
              const {}));

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
