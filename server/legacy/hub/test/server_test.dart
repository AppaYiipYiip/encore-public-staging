import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:encore_hub/encore_hub.dart';
import 'package:encore_session/encore_session.dart';
import 'package:test/test.dart';

/// The hub over real HTTP, two phones talking to it at once. The music
/// server's login is replaced by a list of names and tokens (the real check is
/// "does Navidrome accept this token", proved against the real server in the
/// journey); everything else here is the real thing: sockets, the event stream,
/// the order of messages.
class _Names implements Verifier {
  _Names(this.tokens);
  final Map<String, String> tokens;
  int asked = 0;

  @override
  Future<String?> verify(Map<String, String> query) async {
    asked++;
    final user = query['u'];
    return user != null && tokens[user] == query['t'] ? user : null;
  }
}

/// A phone: logs in as [user] and speaks to the hub.
class _Phone {
  _Phone(this.base, this.user, this.token);

  final Uri base;
  final String user;
  final String token;
  final HttpClient _http = HttpClient();

  Uri url(String path, [Map<String, String> extra = const {}]) => base.replace(
        path: path,
        queryParameters: {'u': user, 't': token, 's': 'x', ...extra},
      );

  Future<(int, Map<String, Object?>)> call(String method, String path,
      {Object? body, Map<String, String> extra = const {}}) async {
    final request = await _http.openUrl(method, url(path, extra));
    if (body != null) {
      request.headers.contentType = ContentType.json;
      request.write(body is String ? body : jsonEncode(body));
    }
    final response = await request.close();
    final text = await utf8.decodeStream(response);
    final json = text.isEmpty ? <String, Object?>{} : jsonDecode(text);
    return (response.statusCode, (json as Map).cast<String, Object?>());
  }

  /// The event stream of a session: states in order, and a flag for "kicked".
  Future<_Listening> listen(String code) async {
    final request = await _http.getUrl(url('/api/sessions/$code/events'));
    final response = await request.close();
    final listening = _Listening(response.statusCode);
    if (response.statusCode == 200) {
      listening._sub = response
          .transform(utf8.decoder)
          .transform(const LineSplitter())
          .listen(listening._line, onDone: listening._done);
    } else {
      await response.drain<void>();
    }
    return listening;
  }

  void close() => _http.close(force: true);
}

class _Listening {
  _Listening(this.status);

  final int status;
  final List<SessionState> states = [];
  bool kicked = false;
  bool closed = false;
  String? _event;
  StreamSubscription<String>? _sub;
  final _changes = StreamController<void>.broadcast();

  void _line(String line) {
    if (line.startsWith('event: ')) {
      _event = line.substring(7);
    } else if (line.startsWith('data: ')) {
      final data = jsonDecode(line.substring(6));
      if (_event == 'state') {
        states.add(SessionState.fromJson(data)!);
      } else if (_event == 'kicked') {
        kicked = true;
      }
      _changes.add(null);
    }
  }

  void _done() {
    closed = true;
    _changes.add(null);
  }

  Future<void> until(bool Function() ok) async {
    if (ok()) return;
    await _changes.stream.firstWhere((_) => ok()).timeout(
        const Duration(seconds: 5),
        onTimeout: () =>
            throw StateError('never happened: ${states.length} states'));
  }

  Future<void> stop() async {
    await _sub?.cancel();
    await _changes.close();
  }
}

void main() {
  late HubServer server;
  late HttpServer socket;
  late Uri base;
  late _Names names;
  late Hub hub;
  final phones = <_Phone>[];

  _Phone phone(String user) {
    final p = _Phone(base, user, 'token-$user');
    phones.add(p);
    return p;
  }

  setUp(() async {
    names = _Names({
      for (final u in ['owner', 'mia', 'ben']) u: 'token-$u',
    });
    final clock = Stopwatch()..start();
    hub = Hub(clock: () => clock.elapsedMilliseconds);
    server = HubServer(
        hub: hub,
        verifier: names,
        keepAlive: const Duration(milliseconds: 200));
    socket = await server.bind('127.0.0.1', 0);
    base = Uri.parse('http://127.0.0.1:${socket.port}');
  });

  tearDown(() async {
    for (final p in phones) {
      p.close();
    }
    phones.clear();
    await server.close();
  });

  test('who it is and what time it is are public (no login)', () async {
    final stranger = _Phone(base, 'nobody', 'nothing');
    phones.add(stranger);

    final (infoStatus, info) = await stranger.call('GET', '/api/info');
    final (timeStatus, time) = await stranger.call('GET', '/api/time');

    expect(infoStatus, 200);
    expect(info['service'], 'encore-hub');
    expect(timeStatus, 200);
    expect(time['hubMs'], isA<int>());
    expect(names.asked, 0, reason: 'nobody was asked for a login');
  });

  test('everything else needs the music server\'s login', () async {
    final stranger = _Phone(base, 'owner', 'a-wrong-token');
    phones.add(stranger);

    final (status, body) = await stranger.call('POST', '/api/sessions');

    expect(status, 401);
    expect(body['error'], 'Sign in again.');
  });

  test('a session from start to finish, between two phones', () async {
    final owner = phone('owner');
    final mia = phone('mia');

    // The owner starts it and shares the code.
    final (created, made) = await owner.call('POST', '/api/sessions');
    expect(created, 201);
    final code = made['code']! as String;
    expect(code, hasLength(6));

    // Mia joins and listens.
    final (joined, state) = await mia.call('POST', '/api/sessions/$code/join');
    expect(joined, 200);
    expect(SessionState.fromJson(state['state'])!.members.map((m) => m.id),
        ['owner', 'mia']);
    final listening = await mia.listen(code);
    expect(listening.status, 200);
    await listening.until(() => listening.states.isNotEmpty);

    // The owner adds a song; mia hears it. Mia presses play; the owner's view agrees.
    await owner.call('POST', '/api/sessions/$code/command',
        body: const Add('song-a').toJson());
    await listening.until(() => listening.states.last.queue.isNotEmpty);
    final (played, _) = await mia.call('POST', '/api/sessions/$code/command',
        body: const Play().toJson());
    expect(played, 200);
    await listening.until(() => listening.states.last.playing);

    final (_, seen) = await owner.call('GET', '/api/sessions/$code');
    final ownerView = SessionState.fromJson(seen['state'])!;
    expect(ownerView.playing, isTrue);
    expect(ownerView.queue.single.trackId, 'song-a');
    expect(ownerView.queue.single.addedBy, 'owner');

    final revs = listening.states.map((s) => s.rev).toList();
    expect(revs, [...revs]..sort(), reason: 'in order');

    await listening.stop();
  });

  test('somebody who is not in the session cannot listen or command', () async {
    final owner = phone('owner');
    final ben = phone('ben');
    final (_, made) = await owner.call('POST', '/api/sessions');
    final code = made['code']! as String;

    final heard = await ben.listen(code);
    final (status, body) = await ben.call('POST', '/api/sessions/$code/command',
        body: const Pause().toJson());

    expect(heard.status, 403);
    expect(status, 403);
    expect(body['error'], 'you are not in this session');
  });

  test('a code that does not exist is a 404 with a sentence', () async {
    final mia = phone('mia');

    final (status, body) = await mia.call('POST', '/api/sessions/NOPE22/join');

    expect(status, 404);
    expect(body['error'], 'there is no session with that code');
  });

  test('nonsense is refused politely, never crashes the hub', () async {
    final owner = phone('owner');
    final (_, made) = await owner.call('POST', '/api/sessions');
    final code = made['code']! as String;

    final (notJson, _) = await owner.call('POST', '/api/sessions/$code/command',
        body: 'this is not json');
    final (unknown, _) = await owner
        .call('POST', '/api/sessions/$code/command', body: {'op': 'explode'});
    final (huge, _) = await owner.call('POST', '/api/sessions/$code/command',
        body: {'op': 'add', 'trackId': 'x' * 10000});

    expect(notJson, 400);
    expect(unknown, 400);
    expect(huge, 413);
    final (alive, _) = await owner.call('GET', '/api/sessions/$code');
    expect(alive, 200, reason: 'still serving after all that');
  });

  test('the host sends somebody away: they are told and their stream closes',
      () async {
    final owner = phone('owner');
    final ben = phone('ben');
    final (_, made) = await owner.call('POST', '/api/sessions');
    final code = made['code']! as String;
    await ben.call('POST', '/api/sessions/$code/join');
    final listening = await ben.listen(code);
    await listening.until(() => listening.states.isNotEmpty);

    await owner.call('POST', '/api/sessions/$code/command',
        body: const Kick('ben').toJson());

    await listening.until(() => listening.closed);
    expect(listening.kicked, isTrue);
    await listening.stop();
  });

  test('when the host leaves everybody hears it is over and the stream closes',
      () async {
    final owner = phone('owner');
    final mia = phone('mia');
    final (_, made) = await owner.call('POST', '/api/sessions');
    final code = made['code']! as String;
    await mia.call('POST', '/api/sessions/$code/join');
    final listening = await mia.listen(code);
    await listening.until(() => listening.states.isNotEmpty);

    await owner.call('POST', '/api/sessions/$code/leave');

    await listening.until(() => listening.closed);
    expect(listening.states.last.ended, isTrue);
    final (gone, _) = await mia.call('GET', '/api/sessions/$code');
    expect(gone, 404);
    await listening.stop();
  });

  test('a quiet stream is kept alive, so a proxy does not cut it', () async {
    final owner = phone('owner');
    final (_, made) = await owner.call('POST', '/api/sessions');
    final code = made['code']! as String;

    final request =
        await HttpClient().getUrl(owner.url('/api/sessions/$code/events'));
    final response = await request.close();
    final text = StringBuffer();
    final done = Completer<void>();
    final sub = response.transform(utf8.decoder).listen((chunk) {
      text.write(chunk);
      if (text.toString().contains(': ping')) done.complete();
    });

    await done.future.timeout(const Duration(seconds: 3));
    expect(response.headers.contentType?.mimeType, 'text/event-stream');
    expect(response.headers.value('cache-control'), contains('no-store'));
    await sub.cancel();
  });

  test('somebody guessing logins is slowed down, not the hub', () async {
    final guesser = _Phone(base, 'owner', 'wrong');
    phones.add(guesser);

    var last = 0;
    for (var i = 0; i < 40; i++) {
      (last, _) = await guesser.call('POST', '/api/sessions');
    }

    expect(last, 429);
  });
}
