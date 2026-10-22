import 'package:dio/dio.dart';
import 'package:meta/meta.dart';

import '../../core/network_policy.dart';
import '../../core/result.dart';
import 'import_models.dart';

/// Where a "play this now" job is (the service's own words, ADR-057).
enum FetchState {
  queued,
  searching,
  downloading,
  tagging,
  indexing,
  ready,
  failed;

  static FetchState byName(String? name) => values.firstWhere(
        (s) => s.name == name,
        orElse: () => FetchState.queued,
      );

  bool get isDone => this == ready || this == failed;
}

/// One song to get: what the catalogue knows about it.
@immutable
class FetchRequest {
  const FetchRequest({
    required this.artist,
    required this.title,
    this.album,
    this.trackNumber,
    this.discNumber,
    this.year,
    this.durationSec,
    this.coverUrl,
    this.bulk = false,
    this.videoId,
    this.official = false,
  });

  final String artist;
  final String title;
  final String? album;
  final int? trackNumber;
  final int? discNumber;
  final int? year;
  final int? durationSec;
  final String? coverUrl;

  /// One of many songs being added in the background, not the one a person
  /// is waiting to hear: the service serves waiting people first.
  final bool bulk;

  /// The YouTube video a playlist saved for this song; [official] when it is
  /// YouTube's own upload (the service then uses it without searching).
  final String? videoId;
  final bool official;

  Map<String, Object?> toJson() => {
        'artist': artist,
        'title': title,
        if (album != null) 'album': album,
        if (trackNumber != null && trackNumber! > 0) 'trackNumber': trackNumber,
        if (discNumber != null && discNumber! > 0) 'discNumber': discNumber,
        if (year != null && year! >= 1900 && year! <= 2100) 'year': year,
        if (durationSec != null && durationSec! >= 5)
          'durationSec': durationSec,
        if (coverUrl != null) 'coverUrl': coverUrl,
        if (bulk) 'priority': 'bulk',
        if (videoId != null) 'videoId': videoId,
        if (official && videoId != null) 'official': true,
      };
}

@immutable
class FetchJob {
  const FetchJob({
    required this.id,
    required this.state,
    this.detail,
    this.error,
    this.message,
    this.songId,
    this.path,
    this.codec,
    this.bitrateKbps,
    this.stream,
  });

  factory FetchJob.fromJson(Map<String, dynamic> json) => FetchJob(
        id: '${json['id'] ?? ''}',
        state: FetchState.byName(json['state'] as String?),
        detail: json['detail'] as String?,
        error: json['error'] as String?,
        message: json['message'] as String?,
        songId: json['songId'] == null ? null : '${json['songId']}',
        path: json['path'] as String?,
        codec: json['codec'] as String?,
        bitrateKbps: (json['bitrateKbps'] as num?)?.toInt(),
        stream: json['stream'] as String?,
      );

  final String id;
  final FetchState state;
  final String? detail;

  /// Short code (`not_found`, `blocked`, ...) when [state] is `failed`.
  final String? error;
  final String? message;

  /// The id the music server gave the song once it listed it.
  final String? songId;
  final String? path;
  final String? codec;
  final int? bitrateKbps;

  /// Path (on the service) the finished song can be streamed from.
  final String? stream;
}

/// The seam the app uses to get a song the library does not have.
abstract interface class InstantPlayBackend {
  Future<Result<FetchJob>> start(FetchRequest request);
  Future<Result<FetchJob>> status(String id);

  /// Asks the service to look a song up *before* anybody taps it (the search
  /// and YouTube's stream list are most of the wait). Never fails loudly: a
  /// lookup ahead of a tap is a nicety.
  Future<void> prepare(FetchRequest request);

  /// Where a finished job's audio can be played from (with the music
  /// server's login in the address), `null` when it has no stream.
  Uri? streamUri(FetchJob job);

  /// Where a song can be played from straight away, passed on from YouTube as it arrives (no job, no download, no length limit: a
  /// two-hour recitation plays and can be jumped around in), `null` when this service cannot stream.
  Uri? streamUrlFor(FetchRequest request);
}

/// What `GET /api/info` says about a service.
@immutable
class FetchServiceInfo {
  const FetchServiceInfo({required this.features, this.version = 1});

  final List<String> features;
  final int version;

  bool get canPlayNow => features.contains('play-now');
  bool get canPrepare => features.contains('prepare');

  /// Passes songs on as they arrive (`GET /api/stream`).
  bool get canStream => features.contains('stream');

  /// Reads a pasted Spotify / YouTube link into a list of songs.
  bool get canReadPlaylists => features.contains('playlist');

  /// Takes a whole list and fetches it in the background (ADR-100).
  bool get canImport => features.contains('import');
}

/// Bringing a playlist over: read a link, hand the list to the server, watch
/// it work. The server does the fetching, so the phone can be closed.
abstract interface class PlaylistImportBackend {
  /// The songs behind a Spotify / YouTube link. Nothing is added.
  Future<Result<ImportedPlaylist>> readPlaylist(String url);

  /// Hands [tracks] to the server's queue. [liked]: like every song instead of
  /// making a playlist.
  Future<Result<ImportJob>> startImport({
    required String name,
    required String source,
    required List<ImportedTrack> tracks,
    bool liked = false,
  });

  Future<Result<ImportJob>> importStatus(String id, {bool songs = false});

  /// Every import of this person the server still remembers, newest first
  /// (without the lists of missing songs).
  Future<Result<List<ImportJob>>> imports();

  Future<Result<ImportJob>> cancelImport(String id);

  /// The person does not want these songs (their numbers in the list): the ones
  /// not fetched yet never will be.
  Future<Result<ImportJob>> skipSongs(String id, List<int> indexes);
}

/// Client of the `encore-fetch` companion service. Stateless: every request
/// carries the music server's own Subsonic token (`u`, `t`, `s`), so there is
/// no second login and no password stored on the service.
class EncoreFetchClient implements InstantPlayBackend, PlaylistImportBackend {
  EncoreFetchClient({
    required Uri baseUrl,
    required Map<String, String> Function() auth,
    Dio? dio,
    this.canStream = false,
  })  : _base = baseUrl,
        _auth = auth,
        _dio = dio ??
            Dio(BaseOptions(
              connectTimeout: const Duration(seconds: 5),
              receiveTimeout: const Duration(seconds: 15),
              validateStatus: (_) => true,
            ));

  final Uri _base;
  final Map<String, String> Function() _auth;
  final Dio _dio;

  /// The service said it can stream (`/api/info` lists `stream`).
  final bool canStream;

  /// An older service answers 404 to `/api/prepare`: stop asking.
  bool _prepareSupported = true;

  /// Why the music login must not be sent to this address, or `null`. The
  /// token is replayable, so over plain http on a public address it stays home
  /// (docs/23, B25).
  String? get _unsafe => cleartextProblem(_base);

  void _requireSafe() {
    final problem = _unsafe;
    if (problem != null) {
      throw UnexpectedFailure('Your login was not sent. $problem');
    }
  }

  Uri _url(String path, {bool withAuth = true}) {
    final basePath = _base.path.replaceAll(RegExp(r'/+$'), '');
    return _base.replace(
      path: '$basePath$path',
      queryParameters: withAuth && _unsafe == null ? _auth() : null,
      fragment: null,
    );
  }

  /// Asks whether [base] is an `encore-fetch` and what it can do. No login.
  static Future<FetchServiceInfo?> probe(Uri base, {Dio? dio}) async {
    final http = dio ??
        Dio(BaseOptions(
          connectTimeout: const Duration(seconds: 3),
          receiveTimeout: const Duration(seconds: 7),
          validateStatus: (_) => true,
        ));
    try {
      final basePath = base.path.replaceAll(RegExp(r'/+$'), '');
      final response = await http.getUri<Object?>(
        base.replace(path: '$basePath/api/info', query: '', fragment: ''),
        options: Options(responseType: ResponseType.json),
      );
      final data = response.data;
      if (response.statusCode != 200 || data is! Map) return null;
      if (data['service'] != 'encore-fetch') return null;
      return FetchServiceInfo(
        features: [
          for (final f in (data['features'] as List? ?? const [])) '$f',
        ],
        version: (data['version'] as num?)?.toInt() ?? 1,
      );
    } on Object {
      return null;
    }
  }

  @override
  Future<Result<FetchJob>> start(FetchRequest request) => guard(() async {
        _requireSafe();
        final response = await _send(
          () =>
              _dio.postUri<Object?>(_url('/api/play'), data: request.toJson()),
        );
        return _job(response);
      });

  @override
  Future<void> prepare(FetchRequest request) async {
    if (!_prepareSupported || _unsafe != null) return;
    try {
      final response = await _dio.postUri<Object?>(
        _url('/api/prepare'),
        data: request.toJson(),
      );
      final status = response.statusCode ?? 0;
      if (status == 404 || status == 405) _prepareSupported = false;
    } on Object {
      // Nobody is waiting for this answer.
    }
  }

  @override
  Uri? streamUrlFor(FetchRequest request) {
    if (!canStream || _unsafe != null) return null;
    final basePath = _base.path.replaceAll(RegExp(r'/+$'), '');
    return _base.replace(
      path: '$basePath/api/stream',
      queryParameters: {
        ..._auth(),
        if (request.videoId != null) 'videoId': request.videoId!,
        if (request.official && request.videoId != null) 'official': '1',
        'artist': request.artist,
        'title': request.title,
        if (request.album != null) 'album': request.album!,
        if (request.durationSec != null && request.durationSec! >= 5)
          'durationSec': '${request.durationSec}',
      },
      fragment: null,
    );
  }

  @override
  Uri? streamUri(FetchJob job) {
    final path = job.stream;
    if (path == null || !path.startsWith('/') || _unsafe != null) return null;
    final basePath = _base.path.replaceAll(RegExp(r'/+$'), '');
    return _base.replace(
      path: '$basePath$path',
      queryParameters: _auth(),
      fragment: null,
    );
  }

  @override
  Future<Result<FetchJob>> status(String id) => guard(() async {
        _requireSafe();
        final response = await _send(
          () => _dio.getUri<Object?>(_url('/api/play/$id')),
        );
        return _job(response);
      });

  @override
  Future<Result<ImportedPlaylist>> readPlaylist(String url) => guard(() async {
        _requireSafe();
        // Reading a long Spotify or YouTube list can take a while.
        final response = await _send(() => _dio.postUri<Object?>(
              _url('/api/playlist'),
              data: {'url': url},
              options: Options(receiveTimeout: const Duration(seconds: 120)),
            ));
        return ImportedPlaylist.fromJson(_ok(response));
      });

  @override
  Future<Result<ImportJob>> startImport({
    required String name,
    required String source,
    required List<ImportedTrack> tracks,
    bool liked = false,
  }) =>
      guard(() async {
        _requireSafe();
        final response = await _send(() => _dio.postUri<Object?>(
              _url('/api/import'),
              data: {
                'name': name,
                'source': source,
                'kind': liked ? 'liked' : 'playlist',
                'tracks': [for (final t in tracks) t.toJson()],
              },
              options: Options(sendTimeout: const Duration(seconds: 60)),
            ));
        return ImportJob.fromJson(_ok(response));
      });

  @override
  Future<Result<ImportJob>> importStatus(String id, {bool songs = false}) =>
      guard(() async {
        _requireSafe();
        final url = _url('/api/import/$id');
        final response = await _send(() => _dio.getUri<Object?>(songs
            ? url.replace(
                queryParameters: {...url.queryParameters, 'songs': '1'})
            : url));
        return ImportJob.fromJson(_ok(response));
      });

  @override
  Future<Result<List<ImportJob>>> imports() => guard(() async {
        _requireSafe();
        final response =
            await _send(() => _dio.getUri<Object?>(_url('/api/import')));
        final map = _ok(response);
        return [
          for (final j in (map['imports'] as List? ?? const []))
            if (j is Map) ImportJob.fromJson(j.cast<String, dynamic>()),
        ];
      });

  @override
  Future<Result<ImportJob>> cancelImport(String id) => guard(() async {
        _requireSafe();
        final response = await _send(
            () => _dio.postUri<Object?>(_url('/api/import/$id/cancel')));
        return ImportJob.fromJson(_ok(response));
      });

  @override
  Future<Result<ImportJob>> skipSongs(String id, List<int> indexes) =>
      guard(() async {
        _requireSafe();
        final response = await _send(() => _dio.postUri<Object?>(
              _url('/api/import/$id/skip'),
              data: {'indexes': indexes},
            ));
        return ImportJob.fromJson(_ok(response));
      });

  /// The JSON object of a successful answer; the service's own sentence as a
  /// failure otherwise (every refusal carries `message` and a short `error`).
  Map<String, dynamic> _ok(Response<Object?> response) {
    final status = response.statusCode ?? 500;
    final data = response.data;
    final map = data is Map ? data.cast<String, dynamic>() : null;
    if (status == 401 || status == 403) {
      throw const AuthFailure('The service did not accept the music server '
          'login');
    }
    if (status >= 400 || map == null) {
      throw ServerFailure(
        (map?['message'] as String?) ??
            (map?['error'] as String?) ??
            'The service answered $status',
        statusCode: status,
        code: map?['error'] as String?,
      );
    }
    return map;
  }

  Future<Response<Object?>> _send(
      Future<Response<Object?>> Function() call) async {
    try {
      return await call();
    } on DioException catch (error) {
      throw NetworkFailure(
        'Cannot reach the instant-play service at ${_base.host}'
        '${_base.hasPort ? ':${_base.port}' : ''}',
        cause: error,
      );
    }
  }

  FetchJob _job(Response<Object?> response) {
    final status = response.statusCode ?? 500;
    final data = response.data;
    final map = data is Map ? data.cast<String, dynamic>() : null;
    if (status == 401 || status == 403) {
      throw const AuthFailure('The instant-play service did not accept the '
          'music server login');
    }
    if (status == 429) {
      throw ServerFailure(
        (map?['message'] as String?) ??
            'Too many songs at once. Try again '
                'in a minute.',
        statusCode: status,
        code: (map?['error'] as String?) ?? 'rate_limited',
      );
    }
    if (status >= 400 || map == null) {
      throw ServerFailure(
        (map?['error'] as String?) ?? 'The service answered $status',
        statusCode: status,
      );
    }
    return FetchJob.fromJson(map);
  }
}
