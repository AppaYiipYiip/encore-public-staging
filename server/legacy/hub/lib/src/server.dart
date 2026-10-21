import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:encore_session/encore_session.dart';

import 'hub.dart';
import 'verifier.dart';

/// The hub over HTTP: Server-Sent Events down, plain POSTs up (docs/29). It
/// passes through any proxy (the Tailscale Funnel included) and needs nothing
/// but `dart:io`.
///
///     GET  /api/info                      what this is (no login)
///     GET  /api/time                      the hub's clock (no login)
///     POST /api/sessions                  start a session, you host it
///     POST /api/sessions/CODE/join        join
///     GET  /api/sessions/CODE             the state now
///     GET  /api/sessions/CODE/events      the state now and after every change
///     POST /api/sessions/CODE/command     one command (see `encore_session`)
///     POST /api/sessions/CODE/leave       leave (the host leaving ends it)
///
/// Everything but the first two needs the music server's login in the query
/// (`u`, `t`, `s`). The Tailscale sidecar strips the `/hub` it publishes the
/// hub under, so the hub sees `/api/...`.
class HubServer {
  HubServer({
    required this.hub,
    required this.verifier,
    this.keepAlive = const Duration(seconds: 15),
    this.maxBody = 4096,
    this.failuresPerMinute = 20,
    Duration sweepEvery = const Duration(minutes: 1),
  }) : _sweepEvery = sweepEvery;

  final Hub hub;
  final Verifier verifier;
  final Duration keepAlive;
  final int maxBody;

  /// Wrong logins one address may send in a minute before it is refused: the
  /// music server counts failed logins by address, and the hub is one address.
  final int failuresPerMinute;
  final Duration _sweepEvery;

  HttpServer? _server;
  Timer? _sweeper;
  final Map<String, List<int>> _failures = {};
  final Set<Timer> _pings = {};

  /// Starts listening; the server is returned so a test can read the port.
  Future<HttpServer> bind(String host, int port) async {
    final server = await HttpServer.bind(host, port);
    _server = server;
    _sweeper = Timer.periodic(_sweepEvery, (_) => hub.sweep());
    unawaited(server.forEach((request) => unawaited(_handle(request))));
    return server;
  }

  Future<void> close() async {
    _sweeper?.cancel();
    for (final t in _pings.toList()) {
      t.cancel();
    }
    await _server?.close(force: true);
  }

  // --------------------------------------------------------------- helpers

  static void _json(HttpResponse response, int status, Object body) {
    response
      ..statusCode = status
      ..headers.contentType = ContentType.json
      ..headers.set('Cache-Control', 'no-store')
      ..write(jsonEncode(body));
  }

  static void _error(HttpResponse response, int status, String message) =>
      _json(response, status, {'error': message});

  String _from(HttpRequest request) {
    final forwarded = request.headers.value('x-forwarded-for');
    if (forwarded != null && forwarded.isNotEmpty) {
      return forwarded.split(',').first.trim();
    }
    return request.connectionInfo?.remoteAddress.address ?? 'unknown';
  }

  bool _blocked(String from) {
    final now = DateTime.now().millisecondsSinceEpoch;
    final list = _failures[from];
    if (list == null) return false;
    list.removeWhere((t) => t < now - 60000);
    return list.length >= failuresPerMinute;
  }

  void _failed(String from) {
    _failures
        .putIfAbsent(from, () => [])
        .add(DateTime.now().millisecondsSinceEpoch);
  }

  /// The body as text, or `null` when it is bigger than [maxBody].
  Future<String?> _text(HttpRequest request) async {
    final bytes = <int>[];
    var seen = 0;
    var tooBig = false;
    await for (final chunk in request) {
      seen += chunk.length;
      if (seen > 262144) {
        break; // far too much: stop reading, answer, close
      }
      if (tooBig) {
        continue; // read and dropped, so the sender can hear the answer
      }
      bytes.addAll(chunk);
      if (bytes.length > maxBody) {
        tooBig = true;
      }
    }
    return tooBig || seen > 262144
        ? null
        : utf8.decode(bytes, allowMalformed: true);
  }

  // ---------------------------------------------------------------- routes

  Future<void> _handle(HttpRequest request) async {
    final response = request.response;
    try {
      await _route(request);
    } on Object catch (error) {
      stderr.writeln(
          'hub: ${request.method} ${request.uri.path} failed: ${error.runtimeType}');
      try {
        _error(response, 500, 'Something went wrong on the server.');
      } on Object {
        // The connection is already gone.
      }
    } finally {
      try {
        await response.close();
      } on Object {
        // Closed already (an event stream that ended).
      }
    }
  }

  Future<void> _route(HttpRequest request) async {
    final response = request.response;
    final parts = [...request.uri.pathSegments]..removeWhere((p) => p.isEmpty);
    if (parts.isEmpty || parts.first != 'api') {
      return _error(response, 404, 'Not found.');
    }
    final path = parts.sublist(1);
    final method = request.method;

    if (path.length == 1 && path[0] == 'info' && method == 'GET') {
      return _json(response, 200, {
        'service': 'encore-hub',
        'version': 1,
        'features': ['jam']
      });
    }
    if (path.length == 1 && path[0] == 'time' && method == 'GET') {
      return _json(response, 200, {'hubMs': hub.nowMs});
    }

    final from = _from(request);
    if (_blocked(from)) {
      return _error(response, 429, 'Slow down.');
    }
    final user = await verifier.verify(request.uri.queryParameters);
    if (user == null) {
      _failed(from);
      return _error(response, 401, 'Sign in again.');
    }

    if (path.isEmpty || path[0] != 'sessions') {
      return _error(response, 404, 'Not found.');
    }
    if (path.length == 1 && method == 'POST') {
      final session = hub.create(user);
      if (session == null) {
        return _error(response, 503, 'The hub is full. Try again later.');
      }
      return _json(response, 201, {
        'code': session.code,
        'you': user,
        'state': session.state.toJson(),
      });
    }
    if (path.length < 2) return _error(response, 404, 'Not found.');
    final code = path[1];
    final action = path.length > 2 ? path[2] : '';

    final session = hub.find(code);
    if (session == null) {
      return _error(response, 404, 'there is no session with that code');
    }

    if (action == 'join' && method == 'POST') {
      final outcome = hub.join(code, user);
      if (!outcome.ok) return _error(response, 409, outcome.rejected!);
      return _json(response, 200,
          {'you': user, 'state': hub.find(code)!.state.toJson()});
    }

    // Everything below is for people in the session.
    if (session.state.member(user) == null) {
      return _error(response, 403, 'you are not in this session');
    }
    if (action.isEmpty && method == 'GET') {
      return _json(
          response, 200, {'you': user, 'state': session.state.toJson()});
    }
    if (action == 'events' && method == 'GET') {
      return _events(request, code, user);
    }
    if (action == 'command' && method == 'POST') {
      final text = await _text(request);
      if (text == null) return _error(response, 413, 'That is too much data.');
      final Object? decoded;
      try {
        decoded = jsonDecode(text);
      } on FormatException {
        return _error(response, 400, 'That is not a command.');
      }
      final command = Command.fromJson(decoded);
      if (command == null) {
        return _error(response, 400, 'That is not a command.');
      }
      final outcome = hub.command(code, user, command);
      if (!outcome.ok) return _error(response, 409, outcome.rejected!);
      return _json(response, 200, {'state': outcome.state.toJson()});
    }
    if (action == 'leave' && method == 'POST') {
      hub.leaveSession(code, user);
      return _json(response, 200, {'ok': true});
    }
    return _error(response, 404, 'Not found.');
  }

  Future<void> _events(HttpRequest request, String code, String user) async {
    final response = request.response;
    response
      ..statusCode = 200
      ..headers.contentType =
          ContentType('text', 'event-stream', charset: 'utf-8')
      ..headers.set('Cache-Control', 'no-store, no-transform')
      ..headers.set('X-Accel-Buffering', 'no')
      ..bufferOutput = false;
    final finished = Completer<void>();
    Subscription? subscription;
    Timer? ping;

    void finish() {
      final timer = ping;
      if (timer != null) {
        timer.cancel();
        _pings.remove(timer);
      }
      subscription?.cancel();
      if (!finished.isCompleted) finished.complete();
    }

    void send(String text) {
      if (finished.isCompleted) return;
      try {
        response.write(text);
      } on Object {
        finish();
      }
    }

    send('retry: 3000\n\n');
    subscription = hub.subscribe(code, user, (event) {
      switch (event) {
        case StateEvent(:final state):
          send('event: state\ndata: ${jsonEncode(state.toJson())}\n\n');
          if (state.ended) finish();
        case KickedEvent():
          send('event: kicked\ndata: {}\n\n');
          finish();
      }
    });
    if (subscription == null) {
      return _error(response, 403, 'you are not in this session');
    }
    ping = Timer.periodic(keepAlive, (_) => send(': ping\n\n'));
    _pings.add(ping);
    unawaited(
        response.done.then<void>((_) => finish(), onError: (_) => finish()));
    await finished.future;
  }
}
