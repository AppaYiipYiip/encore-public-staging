import 'dart:async';

import 'package:dio/dio.dart';

import '../../core/network_policy.dart';
import '../../core/result.dart';
import '../../domain/year_in_music.dart';
import '../api/opensubsonic/opensubsonic_client.dart' show SubsonicCredentials;

/// Reads one person's own play history from Navidrome (ADR-064).
///
/// Navidrome records every completed play of every person, whichever app made
/// it (this one, the web player, a car), and the person's own login can read
/// their own list: `GET /api/scrobble`, rows `{id, mediaFileId,
/// submissionTime}` with the time in epoch seconds, paged with `_start` and
/// `_end`, the total in `X-Total-Count`. Another person's plays cannot be read
/// with this login. The page needs Navidrome's own token (`POST /auth/login`),
/// which takes the password, so it is never sent over plain http to an address
/// on the internet.
class PlayHistoryClient {
  PlayHistoryClient({
    required Dio dio,
    required Uri Function() baseUrl,
    required SubsonicCredentials credentials,
    this.pageSize = 500,
    this.parallel = 4,
  })  : _dio = dio,
        _baseUrl = baseUrl,
        _credentials = credentials;

  final Dio _dio;
  final Uri Function() _baseUrl;
  final SubsonicCredentials _credentials;

  /// Plays asked for in one request.
  final int pageSize;

  /// Pages asked for at the same time once the total is known.
  final int parallel;

  String? _token;

  /// Every play, newest first. [progress] is told how many have arrived of how
  /// many there are. Never throws.
  Future<Result<List<Listen>>> fetchAll({
    void Function(int done, int total)? progress,
  }) =>
      guard(() async {
        final first = await _page(0);
        final listens = [...first.listens];
        final total = first.total;
        progress?.call(listens.length, total);
        var next = pageSize;
        while (next < total) {
          final starts = [
            for (var i = 0; i < parallel && next + i * pageSize < total; i++)
              next + i * pageSize,
          ];
          next += starts.length * pageSize;
          final pages = await Future.wait([for (final s in starts) _page(s)]);
          for (final page in pages) {
            listens.addAll(page.listens);
          }
          progress?.call(listens.length, total);
        }
        return listens;
      });

  Future<({List<Listen> listens, int total})> _page(int start,
      {bool renewed = false}) async {
    final base = _baseUrl();
    final problem = cleartextProblem(base);
    if (problem != null) {
      throw UnexpectedFailure('Your login was not sent. $problem');
    }
    final token = _token ??= await _login(base);
    final Response<Object?> response;
    try {
      response = await _dio.getUri<Object?>(
        _url(base, '/api/scrobble', {
          '_start': '$start',
          '_end': '${start + pageSize}',
          '_sort': 'submissionTime',
          '_order': 'DESC',
        }),
        options: Options(
          headers: {'x-nd-authorization': 'Bearer $token'},
          responseType: ResponseType.json,
          validateStatus: (_) => true,
        ),
      );
    } on DioException catch (error) {
      throw NetworkFailure('Cannot reach your server', cause: error);
    }
    final status = response.statusCode ?? 0;
    if (status == 401 && !renewed) {
      _token = null; // expired: sign in again, once
      return _page(start, renewed: true);
    }
    if (status == 401) {
      throw const AuthFailure('The server did not accept your login');
    }
    if (status != 200) {
      throw ServerFailure('Your server has no play history to read',
          statusCode: status);
    }
    final data = response.data;
    if (data is! List) {
      throw const ServerFailure('Your server answered something unexpected');
    }
    final total = int.tryParse(response.headers.value('x-total-count') ?? '') ??
        data.length;
    return (
      listens: [
        for (final row in data)
          if (row is Map &&
              row['mediaFileId'] is String &&
              row['submissionTime'] is num)
            Listen(
              row['mediaFileId'] as String,
              DateTime.fromMillisecondsSinceEpoch(
                  (row['submissionTime'] as num).toInt() * 1000),
            ),
      ],
      total: total,
    );
  }

  Future<String> _login(Uri base) async {
    final Response<Object?> response;
    try {
      response = await _dio.postUri<Object?>(
        _url(base, '/auth/login', null),
        data: {
          'username': _credentials.username,
          'password': _credentials.password,
        },
        options: Options(
          contentType: Headers.jsonContentType,
          responseType: ResponseType.json,
          validateStatus: (_) => true,
        ),
      );
    } on DioException catch (error) {
      throw NetworkFailure('Cannot reach your server', cause: error);
    }
    final status = response.statusCode ?? 0;
    if (status == 401 || status == 403) {
      throw const AuthFailure('The server did not accept your login');
    }
    final data = response.data;
    final token = data is Map ? data['token'] : null;
    if (status != 200 || token is! String || token.isEmpty) {
      throw ServerFailure('Your server has no play history to read',
          statusCode: status);
    }
    return token;
  }

  static Uri _url(Uri base, String path, Map<String, String>? query) {
    final basePath = base.path.replaceAll(RegExp(r'/+$'), '');
    return base.replace(
      path: '$basePath$path',
      queryParameters: query,
      fragment: null,
    );
  }
}
