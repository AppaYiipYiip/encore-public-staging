import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import '../../core/logger.dart';

/// One thing the server pushed down the live channel (docs/17 section 4): `hello`, `library.changed`, `playback.changed`, `resync` ...
class LiveEvent {
  const LiveEvent(this.type, [this.data = const {}]);

  final String type;
  final Map<String, dynamic> data;

  @override
  String toString() => 'LiveEvent($type)';
}

/// The socket, as far as the live channel needs it. Tests replace it; the app uses [IoLiveSocket].
abstract interface class LiveSocket {
  /// Text frames, in order. Done when the socket closes.
  Stream<String> get messages;

  void send(String text);

  /// Why the server closed it (`4401`: the device token was refused), once it has.
  int? get closeCode;

  Future<void> close();
}

typedef LiveSocketOpener = Future<LiveSocket> Function(Uri uri);

/// [LiveSocket] over `dart:io`.
class IoLiveSocket implements LiveSocket {
  IoLiveSocket(this._socket);

  final WebSocket _socket;

  static Future<LiveSocket> open(Uri uri) async =>
      IoLiveSocket(await WebSocket.connect(uri.toString())
          .timeout(const Duration(seconds: 10)));

  @override
  Stream<String> get messages =>
      _socket.where((m) => m is String).cast<String>();

  @override
  void send(String text) => _socket.add(text);

  @override
  int? get closeCode => _socket.closeCode;

  @override
  Future<void> close() => _socket.close();
}

/// The phone's connection to an Encore server's live channel (`/encore/live`): the server tells this phone when something changed (a
/// like or a playlist edit made on another phone, a change to the library) so it shows within a second or two instead of at the next
/// check.
///
/// Events only make things faster, never correct (docs/17): the phone also asks on its own, slowly, and after every reconnect it asks
/// at once. So this class never has to be perfect, only quick to come back: it reconnects with a jittered back-off (1, 2, 4 ... 30 s)
/// for as long as it runs, and drops a connection that has been silent for longer than the server's 25-second ping allows.
class EncoreLive {
  EncoreLive({
    required Uri Function() baseUrl,
    required Future<String?> Function() deviceToken,
    required Future<void> Function() tokenRefused,
    LiveSocketOpener open = IoLiveSocket.open,
    Random? random,
    Future<void> Function(Duration)? sleep,
    Timer Function(Duration, void Function())? timerFactory,
    this.silenceLimit = const Duration(seconds: 70),
    this.helloWithin = const Duration(seconds: 10),
    this.firstRetry = const Duration(seconds: 1),
    this.longestRetry = const Duration(seconds: 30),
  })  : _baseUrl = baseUrl,
        _deviceToken = deviceToken,
        _tokenRefused = tokenRefused,
        _open = open,
        _random = random ?? Random(),
        _sleep = sleep ?? Future<void>.delayed,
        _timer = timerFactory ?? ((d, cb) => Timer(d, cb));

  final Uri Function() _baseUrl;
  final Future<String?> Function() _deviceToken;
  final Future<void> Function() _tokenRefused;
  final LiveSocketOpener _open;
  final Random _random;
  final Future<void> Function(Duration) _sleep;
  final Timer Function(Duration, void Function()) _timer;

  final Duration silenceLimit;
  final Duration helloWithin;
  final Duration firstRetry;
  final Duration longestRetry;

  final StreamController<LiveEvent> _events = StreamController.broadcast();
  final StreamController<bool> _connection = StreamController.broadcast();
  bool _connected = false;
  bool _running = false;
  int _generation = 0;
  LiveSocket? _socket;

  /// Everything the server pushes, in order (pings are not passed on).
  Stream<LiveEvent> get events => _events.stream;

  /// `true` once the server has said hello, `false` when the connection ends.
  Stream<bool> get connection => _connection.stream;

  bool get isConnected => _connected;

  /// `ws://host/encore/live` for an `http://host` address (`wss` for `https`), keeping any path in front of it.
  static Uri socketUri(Uri base) {
    final front = base.path.replaceAll(RegExp(r'/+$'), '');
    return Uri(
      scheme: base.scheme == 'https' ? 'wss' : 'ws',
      host: base.host,
      port: base.hasPort ? base.port : null,
      path: '$front/encore/live',
    );
  }

  /// Starts (or keeps) connecting. Safe to call again.
  void start() {
    if (_running) return;
    _running = true;
    unawaited(_loop(++_generation));
  }

  /// Closes the connection and stops trying (the app went to the background, or the session ended).
  Future<void> stop() async {
    _running = false;
    _generation++;
    final socket = _socket;
    _socket = null;
    _setConnected(false);
    try {
      await socket?.close();
    } on Object catch (error) {
      Log.debug('encore-live', 'closing the socket: ${error.runtimeType}');
    }
  }

  Future<void> dispose() async {
    await stop();
    await _events.close();
    await _connection.close();
  }

  Future<void> _loop(int generation) async {
    var pause = firstRetry;
    while (_running && generation == _generation) {
      final reached = await _oneConnection(generation);
      if (!_running || generation != _generation) return;
      if (reached) pause = firstRetry;
      // Jitter, so a server that restarts is not met by every phone in the same second.
      final wait = Duration(
          milliseconds:
              (pause.inMilliseconds * (0.6 + 0.4 * _random.nextDouble()))
                  .round());
      await _sleep(wait);
      pause = Duration(
          milliseconds:
              min(pause.inMilliseconds * 2, longestRetry.inMilliseconds));
    }
  }

  /// One connection from open to close. `true` when the server said hello on it.
  Future<bool> _oneConnection(int generation) async {
    final String? token;
    try {
      token = await _deviceToken();
    } on Object catch (error) {
      Log.debug('encore-live', 'no device sign-in yet: $error');
      return false;
    }
    if (token == null || token.isEmpty) return false;

    final LiveSocket socket;
    try {
      socket = await _open(socketUri(_baseUrl()));
    } on Object catch (error) {
      Log.debug('encore-live', 'could not connect: ${error.runtimeType}');
      return false;
    }
    if (!_running || generation != _generation) {
      await socket.close();
      return false;
    }
    _socket = socket;

    var hello = false;
    final done = Completer<void>();
    Timer? watchdog;
    void arm(Duration limit) {
      watchdog?.cancel();
      watchdog = _timer(limit, () {
        Log.debug(
            'encore-live', 'silent for ${limit.inSeconds} s: reconnecting');
        unawaited(socket.close());
      });
    }

    arm(helloWithin);
    socket.send(jsonEncode({'type': 'auth', 'token': token}));
    final sub = socket.messages.listen(
      (text) {
        final event = _parse(text);
        if (event == null) return;
        arm(silenceLimit);
        if (event.type == 'hello') {
          hello = true;
          _setConnected(true);
        }
        if (event.type != 'ping' && !_events.isClosed) _events.add(event);
      },
      onError: (Object error) =>
          Log.debug('encore-live', 'the socket failed: ${error.runtimeType}'),
      onDone: () {
        if (!done.isCompleted) done.complete();
      },
      cancelOnError: false,
    );
    try {
      await done.future;
    } finally {
      watchdog?.cancel();
      await sub.cancel();
      if (identical(_socket, socket)) _socket = null;
      _setConnected(false);
    }
    if (socket.closeCode == 4401) {
      // The server does not know this device any more (it was removed, or the server was set up again): sign in afresh next time.
      Log.info(
          'encore-live', 'the device sign-in was refused: signing in again');
      try {
        await _tokenRefused();
      } on Object catch (error) {
        // The next attempt will ask again.
        Log.debug(
            'encore-live', 'could not forget the token: ${error.runtimeType}');
      }
    }
    return hello;
  }

  static LiveEvent? _parse(String text) {
    try {
      final decoded = jsonDecode(text);
      if (decoded is Map && decoded['type'] is String) {
        return LiveEvent(
            decoded['type'] as String, decoded.cast<String, dynamic>());
      }
    } on FormatException catch (error) {
      Log.debug('encore-live', 'a frame that is not JSON: ${error.message}');
    }
    return null;
  }

  void _setConnected(bool value) {
    if (_connected == value) return;
    _connected = value;
    if (!_connection.isClosed) _connection.add(value);
  }
}
