import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:encore/core/result.dart';
import 'package:encore/data/jam/jam_client.dart';
import 'package:encore_session/encore_session.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_http.dart';

/// The app's side of the Jam hub (docs/30, ADR-095): every request carries the
/// music server's own token, answers become typed results with the hub's own
/// sentence, and the event stream is read the way a phone on a bad network
/// delivers it (in pieces, with comments and noise between the events).
void main() {
  late FakeHttpAdapter adapter;

  Dio dio() => Dio(BaseOptions(validateStatus: (_) => true))
    ..httpClientAdapter = adapter;

  JamClient at(String base, {int Function()? clock}) => JamClient(
        baseUrl: Uri.parse(base),
        auth: () => {'u': 'mia', 't': 'tok', 's': 'salt'},
        dio: dio(),
        nowMs: clock,
      );

  FakeResponse ok(Object body, {int status = 200}) =>
      FakeResponse.json(body, status: status);

  const owner = Member(id: 'owner', name: 'owner', role: Role.host);
  const mia = Member(id: 'mia', name: 'mia');
  final started = const SessionState(members: [owner], rev: 1);
  final joined = started.copyWith(members: [owner, mia], rev: 2);

  late JamClient client;

  setUp(() {
    adapter = FakeHttpAdapter();
    client = at('https://music.example.ts.net/hub');
  });

  RecordedRequest last() => adapter.requests.last;

  group('is the hub there?', () {
    test('asks without any login', () async {
      adapter.routes['/hub/api/info'] =
          (_) => ok({'service': 'encore-hub', 'version': 1});

      expect(
          await JamClient.probe(Uri.parse('https://music.example.ts.net/hub'),
              dio: dio()),
          isTrue);

      expect(last().uri.queryParameters, isEmpty,
          reason: 'the token goes only to an address that proved what it is');
    });

    test('something else answering is not the hub', () async {
      adapter.routes['/hub/api/info'] =
          (_) => ok({'service': 'encore-people', 'version': 1});
      expect(
          await JamClient.probe(Uri.parse('https://x.example/hub'), dio: dio()),
          isFalse);

      adapter.routes['/hub/api/info'] = (_) => ok('<html>', status: 404);
      expect(
          await JamClient.probe(Uri.parse('https://x.example/hub'), dio: dio()),
          isFalse);
    });

    test('an address that does not answer is not the hub, quietly', () async {
      adapter.routes['/hub/api/info'] =
          (_) => const FakeResponse.connectionError();
      expect(
          await JamClient.probe(Uri.parse('https://x.example/hub'), dio: dio()),
          isFalse);
    });
  });

  group('starting and joining', () {
    test('starting a Jam returns the code and the state, with the login',
        () async {
      adapter.routes['/hub/api/sessions'] = (_) => ok(
          {'code': 'AB23CD', 'you': 'mia', 'state': started.toJson()},
          status: 201);

      final result = await client.create();

      expect(result.isOk, isTrue, reason: '${result.failureOrNull}');
      expect(result.valueOrNull!.code, 'AB23CD');
      expect(result.valueOrNull!.state.members.single.isHost, isTrue);
      expect(last().method, 'POST');
      expect(last().uri.queryParameters['u'], 'mia');
      expect(last().uri.queryParameters['t'], 'tok');
      expect(last().uri.queryParameters.containsKey('p'), isFalse,
          reason: 'never the password');
    });

    test('joining uses the code as typed: any case, spaces around', () async {
      adapter.routes['/hub/api/sessions/AB23CD/join'] =
          (_) => ok({'you': 'mia', 'state': joined.toJson()});

      final result = await client.join('  ab23cd ');

      expect(result.isOk, isTrue, reason: '${result.failureOrNull}');
      expect(result.valueOrNull!.code, 'AB23CD');
      expect(
          result.valueOrNull!.state.members.map((m) => m.id), ['owner', 'mia']);
    });

    test('a code that is not there says so in the hub\'s own words', () async {
      adapter.routes['/hub/api/sessions/ZZZZZZ/join'] = (_) =>
          ok({'error': 'there is no session with that code'}, status: 404);

      final result = await client.join('ZZZZZZ');

      expect(result.failureOrNull, isA<NotFoundFailure>());
      expect(
          result.failureOrNull!.message, 'there is no session with that code');
    });

    test('a refused login is an AuthFailure, not "the hub is down"', () async {
      adapter.routes['/hub/api/sessions'] =
          (_) => ok({'error': 'Sign in again.'}, status: 401);

      final result = await client.create();

      expect(result.failureOrNull, isA<AuthFailure>());
    });

    test('a hub that cannot be reached is a network failure with a sentence',
        () async {
      adapter.routes['/hub/api/sessions'] =
          (_) => const FakeResponse.connectionError();

      final result = await client.create();

      expect(result.failureOrNull, isA<NetworkFailure>());
      expect(result.failureOrNull!.message, contains('music.example.ts.net'));
    });

    test('a hub the app cannot read is said plainly, never a crash', () async {
      adapter.routes['/hub/api/sessions'] = (_) => ok('not json at all');

      final result = await client.create();

      expect(result.isErr, isTrue);
      expect(result.failureOrNull!.message, contains('cannot read'));
    });
  });

  group('commands', () {
    test('sends the command as the engine writes it and returns the new state',
        () async {
      final after = joined.copyWith(rev: 3);
      adapter.routes['/hub/api/sessions/AB23CD/command'] =
          (_) => ok({'state': after.toJson()});

      final result = await client.command(
          'AB23CD', const Add('lib-1', title: 'Sommaire', artist: 'Raid'));

      expect(result.valueOrNull!.rev, 3);
      expect(jsonDecode(last().body), {
        'op': 'add',
        'trackId': 'lib-1',
        'at': 'end',
        'title': 'Sommaire',
        'artist': 'Raid',
      });
    });

    test('a refusal arrives as the rule\'s own sentence', () async {
      adapter.routes['/hub/api/sessions/AB23CD/command'] =
          (_) => ok({'error': 'only the host can do that'}, status: 409);

      final result = await client.command('AB23CD', const Kick('ben'));

      expect(result.failureOrNull!.message, 'only the host can do that');
    });

    test('leaving is a POST to leave', () async {
      adapter.routes['/hub/api/sessions/AB23CD/leave'] =
          (_) => ok({'ok': true});

      final result = await client.leave('AB23CD');

      expect(result.isOk, isTrue);
      expect(last().method, 'POST');
    });
  });

  group('the clock', () {
    test(
        'a sample is when it was sent, when it came back, and what the hub said',
        () async {
      var now = 1000;
      client = at('https://music.example.ts.net/hub', clock: () => now);
      adapter.routes['/hub/api/time'] = (_) {
        now += 80; // the round trip
        return ok({'hubMs': 5000});
      };

      final sample = (await client.sampleClock()).valueOrNull!;

      expect(sample.sentMs, 1000);
      expect(sample.receivedMs, 1080);
      expect(sample.hubMs, 5000);
      expect(sample.roundTripMs, 80);
    });
  });

  group('the event stream', () {
    String event(String name, Object data) =>
        'event: $name\ndata: ${jsonEncode(data)}\n\n';

    test('reads states in order, ignoring comments and noise', () async {
      final text = 'retry: 3000\n\n'
          '${event('state', started.toJson())}'
          ': ping\n\n'
          'garbage that is not a field\n'
          '${event('state', joined.toJson())}';
      adapter.routes['/hub/api/sessions/AB23CD/events'] = (_) => ok(text);

      final events = await client.events('AB23CD').toList();

      expect(events.whereType<JamStateEvent>().map((e) => e.state.rev), [1, 2]);
    });

    test(
        'a stream that just stops is the network: the controller listens again',
        () async {
      adapter.routes['/hub/api/sessions/AB23CD/events'] =
          (_) => ok(event('state', joined.toJson()));

      final events = await client.events('AB23CD').toList();

      expect(events.last, isA<JamClosedEvent>());
      expect((events.last as JamClosedEvent).dropped, isTrue);
    });

    test('a Jam that ended is not a drop: nothing to listen to again',
        () async {
      final over = joined.copyWith(rev: 9, ended: true);
      adapter.routes['/hub/api/sessions/AB23CD/events'] =
          (_) => ok(event('state', over.toJson()));

      final events = await client.events('AB23CD').toList();

      expect(events.single, isA<JamStateEvent>());
    });

    test('a person who was sent away is told', () async {
      adapter.routes['/hub/api/sessions/AB23CD/events'] =
          (_) => ok('${event('state', joined.toJson())}${event('kicked', {})}');

      final events = await client.events('AB23CD').toList();

      expect(events.last, isA<JamKickedEvent>());
    });

    test('an event cut in two by the network is still one event', () async {
      final whole = event('state', joined.toJson());
      final cut = whole.length ~/ 2;
      final chunks = [whole.substring(0, cut), whole.substring(cut)];
      client = JamClient(
        baseUrl: Uri.parse('https://music.example.ts.net/hub'),
        auth: () => {'u': 'mia', 't': 'tok', 's': 'salt'},
        dio: Dio(BaseOptions(validateStatus: (_) => true))
          ..httpClientAdapter = _ChunkedAdapter(chunks),
      );

      final events = await client.events('AB23CD').toList();

      expect(events.whereType<JamStateEvent>(), hasLength(1));
    });

    test('a state the app cannot read is skipped, the stream goes on',
        () async {
      adapter.routes['/hub/api/sessions/AB23CD/events'] = (_) => ok(
              '${event('state', {
                'rev': 'nonsense'
              })}${event('state', joined.toJson())}');

      final events = await client.events('AB23CD').toList();

      expect(events.whereType<JamStateEvent>().map((e) => e.state.rev), [2]);
    });

    test('a refusal ends the stream with the reason, not silence', () async {
      adapter.routes['/hub/api/sessions/AB23CD/events'] =
          (_) => ok({'error': 'you are not in this session'}, status: 403);

      final events = await client.events('AB23CD').toList();

      expect(events.single, isA<JamClosedEvent>());
      expect((events.single as JamClosedEvent).reason,
          'you are not in this session');
    });

    test('a connection that drops ends the stream, marked as dropped',
        () async {
      adapter.routes['/hub/api/sessions/AB23CD/events'] =
          (_) => const FakeResponse.connectionError();

      final events = await client.events('AB23CD').toList();

      expect(events.single, isA<JamClosedEvent>());
      expect((events.single as JamClosedEvent).dropped, isTrue,
          reason:
              'the controller reconnects after a drop, not after a refusal');
    });
  });

  test('a login is never sent over plain http to the internet', () async {
    final insecure = at('http://music.example.org/hub');

    final result = await insecure.create();

    expect(result.isErr, isTrue);
    expect(adapter.requests, isEmpty, reason: 'nothing left the phone');
  });
}

/// Delivers a body in the pieces given, as a slow network would.
class _ChunkedAdapter implements HttpClientAdapter {
  _ChunkedAdapter(this.chunks);

  final List<String> chunks;

  @override
  Future<ResponseBody> fetch(RequestOptions options,
      Stream<Uint8List>? requestStream, Future<void>? cancelFuture) async {
    return ResponseBody(
      Stream.fromIterable(
          [for (final c in chunks) Uint8List.fromList(utf8.encode(c))]),
      200,
      headers: {
        Headers.contentTypeHeader: ['text/event-stream'],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}
