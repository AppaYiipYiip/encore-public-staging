import 'dart:async';
import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:encore_session/encore_session.dart';
import 'package:flutter/foundation.dart';

import '../../core/logger.dart';
import '../../core/network_policy.dart';
import '../../core/result.dart';

/// A Jam the person is now in: its code (what others type), who they are in
/// it, and what it looks like now.
@immutable
class JamJoined {
  const JamJoined({required this.code, required this.you, required this.state});

  final String code;
  final String you;
  final SessionState state;
}

/// Something the hub says about the Jam, in order.
sealed class JamEvent {
  const JamEvent();
}

/// The Jam is now like this (sent first, and after every change).
class JamStateEvent extends JamEvent {
  const JamStateEvent(this.state);
  final SessionState state;
}

/// The host sent this person away.
class JamKickedEvent extends JamEvent {
  const JamKickedEvent();
}

/// The stream ended without the Jam ending: the network dropped
/// ([dropped]: try again) or the hub refused ([reason]: do not).
class JamClosedEvent extends JamEvent {
  const JamClosedEvent({this.reason, this.dropped = false});
  final String? reason;
  final bool dropped;
}

/// What the app asks of the Jam hub; [JamClient] is the real one and tests use
/// a fake.
abstract interface class JamApi {
  Future<Result<JamJoined>> create();
  Future<Result<JamJoined>> join(String code);
  Future<Result<void>> leave(String code);
  Future<Result<SessionState>> command(String code, Command command);

  /// One question to the hub's clock (see `ClockEstimator`).
  Future<Result<ClockSample>> sampleClock();

  /// The Jam's states as they happen, starting with the current one. Ends when
  /// the connection does.
  Stream<JamEvent> events(String code);
}

/// Client of the Jam hub (`server/hub`, ADR-095). Every request carries the
/// music server's own token (`u`, `t`, `s`), never the password; the hub asks
/// the music server whether it is good.
class JamClient implements JamApi {
  JamClient({
    required Uri baseUrl,
    required Map<String, String> Function() auth,
    Dio? dio,
    int Function()? nowMs,
  })  : _base = baseUrl,
        _auth = auth,
        _now = nowMs ?? (() => DateTime.now().millisecondsSinceEpoch),
        _dio = dio ??
            Dio(BaseOptions(
              connectTimeout: const Duration(seconds: 6),
              receiveTimeout: const Duration(seconds: 10),
              validateStatus: (_) => true,
            ));

  final Uri _base;
  final Map<String, String> Function() _auth;
  final int Function() _now;
  final Dio _dio;

  static String _basePath(Uri base) => base.path.replaceAll(RegExp(r'/+$'), '');

  /// Asks whether [base] is a Jam hub. No login is sent: the token goes only to
  /// an address that has just proved what it is.
  static Future<bool> probe(Uri base, {Dio? dio}) async {
    final http = dio ??
        Dio(BaseOptions(
          connectTimeout: const Duration(milliseconds: 1500),
          receiveTimeout: const Duration(milliseconds: 2500),
          validateStatus: (_) => true,
        ));
    try {
      final response = await http.getUri<String>(
        base.replace(
            path: '${_basePath(base)}/api/info', query: '', fragment: ''),
        options: Options(responseType: ResponseType.plain),
      );
      if (response.statusCode != 200) return false;
      final data = jsonDecode(response.data ?? '');
      return data is Map && data['service'] == 'encore-hub';
    } on DioException catch (error) {
      Log.debug('jam', 'no hub there: ${error.type.name}');
      return false;
    } on FormatException {
      return false; // something answered, and it is not the hub
    }
  }

  // --------------------------------------------------------------- sessions

  @override
  Future<Result<JamJoined>> create() => guard(() async {
        final data = _map(await _send('POST', '/sessions'));
        return _joined(data, code: data['code']);
      });

  @override
  Future<Result<JamJoined>> join(String code) => guard(() async {
        final clean = _clean(code);
        final data = _map(await _send('POST', '/sessions/$clean/join'));
        return _joined(data, code: clean);
      });

  @override
  Future<Result<void>> leave(String code) =>
      guard<void>(() async => _send('POST', '/sessions/${_clean(code)}/leave'));

  @override
  Future<Result<SessionState>> command(String code, Command command) =>
      guard(() async {
        final data = _map(await _send(
            'POST', '/sessions/${_clean(code)}/command',
            body: command.toJson()));
        final state = SessionState.fromJson(data['state']);
        if (state == null) throw _unreadable();
        return state;
      });

  @override
  Future<Result<ClockSample>> sampleClock() => guard(() async {
        final sent = _now();
        final data = _map(await _send('GET', '/time', withAuth: false));
        final received = _now();
        final hubMs = data['hubMs'];
        if (hubMs is! int) throw _unreadable();
        return ClockSample(sentMs: sent, receivedMs: received, hubMs: hubMs);
      });

  /// What people type may be lower case or have spaces around it.
  static String _clean(String code) => code.trim().toUpperCase();

  JamJoined _joined(Map<String, dynamic> data, {Object? code}) {
    final you = data['you'];
    final state = SessionState.fromJson(data['state']);
    if (code is! String || you is! String || state == null) {
      throw _unreadable();
    }
    return JamJoined(code: code, you: you, state: state);
  }

  // ----------------------------------------------------------- the stream

  @override
  Stream<JamEvent> events(String code) async* {
    final problem = cleartextProblem(_base);
    if (problem != null) {
      yield JamClosedEvent(reason: 'Your login was not sent. $problem');
      return;
    }
    final Response<ResponseBody> response;
    try {
      response = await _dio.getUri<ResponseBody>(
        _url('/sessions/${_clean(code)}/events'),
        options: Options(
          responseType: ResponseType.stream,
          // The hub sends a comment every 15 s: 45 s of silence is a dead line.
          receiveTimeout: const Duration(seconds: 45),
          headers: {'Accept': 'text/event-stream'},
          validateStatus: (_) => true,
        ),
      );
    } on DioException catch (error) {
      yield JamClosedEvent(dropped: true, reason: error.type.name);
      return;
    }
    if (response.statusCode != 200) {
      final text = await _readAll(response.data);
      yield JamClosedEvent(
          reason: _sentence(text) ??
              'The Jam service answered '
                  '${response.statusCode}');
      return;
    }

    var endedByHub = false;
    final parser = _EventParser();
    try {
      await for (final chunk in response.data!.stream) {
        for (final event
            in parser.add(utf8.decode(chunk, allowMalformed: true))) {
          if (event is JamKickedEvent) endedByHub = true;
          if (event is JamStateEvent && event.state.ended) endedByHub = true;
          yield event;
        }
      }
    } on DioException catch (error) {
      yield JamClosedEvent(dropped: true, reason: error.type.name);
      return;
    }
    // The hub closes the stream by itself only when the Jam is over or the
    // person was sent away; anything else is the network.
    if (!endedByHub) yield const JamClosedEvent(dropped: true);
  }

  static Future<String> _readAll(ResponseBody? body) async {
    if (body == null) return '';
    final bytes = <int>[];
    await for (final chunk in body.stream) {
      bytes.addAll(chunk);
    }
    return utf8.decode(bytes, allowMalformed: true);
  }

  // -------------------------------------------------------------- plumbing

  AppFailure _unreadable() =>
      const ServerFailure('The Jam service sent an answer the app cannot read');

  Uri _url(String path, {bool withAuth = true}) => _base.replace(
        path: '${_basePath(_base)}/api$path',
        queryParameters: withAuth ? _auth() : null,
        fragment: null,
      );

  Future<String> _send(String method, String path,
      {Object? body, bool withAuth = true}) async {
    final problem = cleartextProblem(_base);
    if (problem != null) {
      throw UnexpectedFailure('Your login was not sent. $problem');
    }
    final Response<String> response;
    try {
      response = await _dio.requestUri<String>(
        _url(path, withAuth: withAuth),
        data: body == null ? null : jsonEncode(body),
        options: Options(
          method: method,
          responseType: ResponseType.plain,
          contentType: body == null ? null : Headers.jsonContentType,
          validateStatus: (_) => true,
        ),
      );
    } on DioException catch (error) {
      throw NetworkFailure(
        'Cannot reach the Jam service at ${_base.host}'
        '${_base.hasPort ? ':${_base.port}' : ''}',
        cause: error,
      );
    }
    final status = response.statusCode ?? 500;
    final text = response.data ?? '';
    if (status >= 200 && status < 300) return text;
    final said = _sentence(text);
    if (status == 401) throw AuthFailure(said ?? 'Sign in again.');
    if (status == 404) {
      throw NotFoundFailure(said ?? 'There is no Jam with that code.');
    }
    throw ServerFailure(
      said ?? 'The Jam service answered $status',
      statusCode: status,
    );
  }

  static String? _sentence(String text) {
    try {
      final data = jsonDecode(text);
      final error = data is Map ? data['error'] : null;
      return error is String && error.isNotEmpty ? error : null;
    } on FormatException {
      return null;
    }
  }

  Map<String, dynamic> _map(String text) {
    try {
      final data = jsonDecode(text);
      if (data is Map<String, dynamic>) return data;
    } on FormatException {
      // Falls through to the failure below.
    }
    throw _unreadable();
  }
}

/// Reads Server-Sent Events out of text that arrives in pieces.
class _EventParser {
  String _buffer = '';
  String? _name;
  final List<String> _data = [];

  List<JamEvent> add(String text) {
    _buffer += text;
    final out = <JamEvent>[];
    var newline = _buffer.indexOf('\n');
    while (newline >= 0) {
      var line = _buffer.substring(0, newline);
      _buffer = _buffer.substring(newline + 1);
      if (line.endsWith('\r')) line = line.substring(0, line.length - 1);
      final event = _line(line);
      if (event != null) out.add(event);
      newline = _buffer.indexOf('\n');
    }
    return out;
  }

  JamEvent? _line(String line) {
    if (line.isEmpty) return _dispatch();
    if (line.startsWith(':')) return null; // a keep-alive comment
    if (line.startsWith('event:')) {
      _name = line.substring(6).trim();
    } else if (line.startsWith('data:')) {
      _data.add(line.substring(5).trimLeft());
    }
    return null; // retry:, and anything else that is not ours
  }

  JamEvent? _dispatch() {
    final name = _name;
    final data = _data.join('\n');
    _name = null;
    _data.clear();
    if (name == 'kicked') return const JamKickedEvent();
    if (name != 'state' || data.isEmpty) return null;
    try {
      final state = SessionState.fromJson(jsonDecode(data));
      return state == null ? null : JamStateEvent(state);
    } on FormatException {
      return null;
    }
  }
}
