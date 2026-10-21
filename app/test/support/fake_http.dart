import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';

/// A recorded request (what the fake adapter saw).
class RecordedRequest {
  RecordedRequest({
    required this.method,
    required this.uri,
    required this.body,
    required this.contentType,
    this.headers = const {},
  });

  final String method;
  final Uri uri;
  final String body;
  final String? contentType;

  /// The request's own headers, names in lower case.
  final Map<String, String> headers;

  /// Subsonic method name (`ping`, `search3`...), from `/rest/<method>`.
  String get apiMethod => uri.pathSegments.isEmpty ? '' : uri.pathSegments.last;

  /// Query parameters merged with a form-encoded body (formPost).
  Map<String, List<String>> get params {
    final merged = <String, List<String>>{};
    void addAll(Map<String, List<String>> source) {
      source.forEach((k, v) => merged.putIfAbsent(k, () => []).addAll(v));
    }

    addAll(uri.queryParametersAll);
    if (body.isNotEmpty && (contentType ?? '').contains('urlencoded')) {
      addAll(Uri.splitQueryString(body).map((k, v) => MapEntry(k, [v])));
    }
    return merged;
  }

  String? param(String name) => params[name]?.first;
}

typedef FakeHandler = FutureOr<FakeResponse> Function(RecordedRequest request);

class FakeResponse {
  const FakeResponse.json(Object this.body,
      {this.status = 200, this.headers = const {}})
      : error = null;

  /// Simulates a socket-level failure (DioExceptionType.connectionError).
  const FakeResponse.connectionError()
      : body = null,
        status = 0,
        headers = const {},
        error = 'connection error';

  final Object? body;
  final int status;
  final String? error;

  /// Extra response headers (`X-Total-Count`...).
  final Map<String, String> headers;
}

/// In-memory Dio adapter: routes by Subsonic method name and records traffic.
///
/// No sockets, no real time - the foundation for contract and sync tests.
class FakeHttpAdapter implements HttpClientAdapter {
  FakeHttpAdapter({Map<String, FakeHandler>? routes}) : routes = routes ?? {};

  /// Handlers keyed by Subsonic method (`ping`) or full path (`/api/song`).
  final Map<String, FakeHandler> routes;
  final List<RecordedRequest> requests = [];

  int count(String apiMethod) =>
      requests.where((r) => r.apiMethod == apiMethod).length;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    var body = '';
    if (requestStream != null) {
      final bytes = <int>[];
      await for (final chunk in requestStream) {
        bytes.addAll(chunk);
      }
      body = utf8.decode(bytes);
    }
    final request = RecordedRequest(
      method: options.method,
      uri: options.uri,
      body: body,
      contentType: options.contentType,
      headers: {
        for (final e in options.headers.entries)
          e.key.toLowerCase(): '${e.value}',
      },
    );
    requests.add(request);

    final handler = routes[request.apiMethod] ?? routes[options.uri.path];
    if (handler == null) {
      return ResponseBody.fromString(
        jsonEncode({
          'subsonic-response': {
            'status': 'failed',
            'version': '1.16.1',
            'error': {
              'code': 0,
              'message': 'no fake route for ${request.apiMethod}'
            },
          },
        }),
        200,
        headers: {
          Headers.contentTypeHeader: ['application/json'],
        },
      );
    }
    final response = await handler(request);
    if (response.error != null) {
      throw DioException.connectionError(
        requestOptions: options,
        reason: response.error!,
      );
    }
    final payload = response.body is String
        ? response.body! as String
        : jsonEncode(response.body);
    return ResponseBody.fromString(
      payload,
      response.status,
      headers: {
        Headers.contentTypeHeader: ['application/json'],
        for (final e in response.headers.entries) e.key: [e.value],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

/// Wraps [payload] in the standard Subsonic envelope.
Map<String, Object?> subsonicOk(
  Map<String, Object?> payload, {
  String type = 'navidrome',
  bool openSubsonic = true,
}) =>
    {
      'subsonic-response': {
        'status': 'ok',
        'version': '1.16.1',
        'type': type,
        'serverVersion': '0.64.2 (test)',
        'openSubsonic': openSubsonic,
        ...payload,
      },
    };

Map<String, Object?> subsonicError(int code, String message) => {
      'subsonic-response': {
        'status': 'failed',
        'version': '1.16.1',
        'error': {'code': code, 'message': message},
      },
    };

/// Builds a Dio wired to [adapter].
Dio fakeDio(FakeHttpAdapter adapter) {
  final dio = Dio(BaseOptions(validateStatus: (s) => s != null && s < 400));
  dio.httpClientAdapter = adapter;
  return dio;
}
