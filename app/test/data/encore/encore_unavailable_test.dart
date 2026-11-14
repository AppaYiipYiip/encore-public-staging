import 'package:dio/dio.dart';
import 'package:encore/data/encore/encore_api.dart';
import 'package:encore/data/encore/encore_instant.dart';
import 'package:encore/data/encore/encore_models.dart';
import 'package:encore/data/fetch/fetch_client.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_encore_server.dart';

/// N-13: the songs the server already knows it cannot get (docs/17 "Songs the server cannot get").
///
/// What these tests hold: the phone reads the memory from a ref and from ONE batched question per list; **the field and the route are optional**, so an
/// older server (no field; the route answers 404 or 405) means "no verdicts here" and never an error state; and a tapped song whose ref says the
/// server cannot get it is not saved, not played and not tried, and says why in the server's own sentence.
void main() {
  late FakeEncoreServer server;
  late List<EncoreRef> ingested;
  late EncoreApi api;
  late EncoreInstantBackend backend;
  var now = DateTime(2026, 11, 14, 12);

  setUp(() {
    server = FakeEncoreServer();
    ingested = [];
    now = DateTime(2026, 11, 14, 12);
    api = EncoreApi(
      dio: Dio()..httpClientAdapter = server.adapter,
      baseUrl: () => Uri.parse('http://home.test:4540'),
      auth: () => {'u': 'tester', 't': 'tok', 's': 'salt'},
    );
    backend = EncoreInstantBackend(
      api: api,
      ingest: (refs) async => ingested.addAll(refs),
      now: () => now,
    );
  });

  const lofi = FetchRequest(
      artist: 'Lofi & Sleep', title: 'Lofi For Focus', durationSec: 180);
  const rainy = FetchRequest(
      artist: 'Lofi & Sleep', title: 'Rainy Window', durationSec: 161);

  group('what the server says', () {
    test('a ref without the field has no memory (every older server)', () {
      final ref = EncoreRef.fromJson({
        'id': 'sr_1',
        'title': 'Nude',
        'artists': ['Radiohead']
      });

      expect(ref.unavailable, isNull);
    });

    test(
        'a ref with it carries the reason, the server\'s sentence and when the server stops believing it',
        () {
      final ref = EncoreRef.fromJson({
        'id': 'sr_1',
        'title': 'Lofi For Focus',
        'artists': ['Lofi & Sleep'],
        'unavailable': {
          'reason': 'not_found',
          'message': 'Nothing matching that song was found.',
          'since': 1000,
          'retryAfter': DateTime(2026, 11, 20).millisecondsSinceEpoch,
        },
      });

      final mark = ref.unavailable!;
      expect(mark.reason, 'not_found');
      expect(mark.liveAt(DateTime(2026, 11, 19)), isTrue);
      expect(mark.liveAt(DateTime(2026, 11, 20)), isFalse,
          reason: 'from the moment the server stops believing it, a tap tries');
      expect(mark.sentence,
          'Nothing matching that song was found. Try again in a few days.');
    });

    test(
        'only "not found" says when to try again; a removed song and an age check say only what the server says',
        () {
      EncoreUnavailable make(String reason, String message) =>
          EncoreUnavailable.fromJson({
            'reason': reason,
            'message': message,
            'retryAfter': 1,
          })!;

      expect(make('removed', 'YouTube has no copy of that song.').sentence,
          'YouTube has no copy of that song.');
      expect(make('age_restricted', 'Needs an age check.').sentence,
          'Needs an age check.');
    });

    test('a strange value is no memory, never an exception', () {
      for (final odd in <Object?>[
        null,
        'yes',
        7,
        <String, Object?>{},
        {'reason': 'not_found'},
        {'retryAfter': 5},
        {'reason': 3, 'retryAfter': 'x'},
      ]) {
        expect(EncoreUnavailable.fromJson(odd), isNull, reason: '$odd');
      }
    });

    test('a newer server\'s reason is still a memory, with a sentence', () {
      final mark = EncoreUnavailable.fromJson(
          {'reason': 'something_new', 'retryAfter': 5})!;

      expect(mark.reason, 'something_new');
      expect(mark.sentence, isNotEmpty);
    });
  });

  group('the batched question', () {
    test(
        'one request answers every song in the order asked: null where the server knows no problem',
        () async {
      server.cannotGet['lofi for focus'] =
          (reason: 'not_found', retryIn: const Duration(days: 7));

      final answer = await backend.unavailableAmong([rainy, lofi]);

      expect(answer!.supported, isTrue);
      expect(answer.verdicts[0], isNull);
      expect(answer.verdicts[1]!.reason, 'not_found');
      expect(
          server.unavailableAsked,
          [
            ['Rainy Window', 'Lofi For Focus']
          ],
          reason: 'one request for the whole list');
      expect(server.refs, isEmpty, reason: 'a read: asking makes no ref');
    });

    test(
        'the songs are described as a tap describes them (so the server finds the same ref)',
        () async {
      await backend.unavailableAmong([lofi]);

      final body = server.adapter.requests
          .singleWhere((r) => r.uri.path.endsWith('refs/unavailable'))
          .body;
      expect(body, contains('"title":"Lofi For Focus"'));
      expect(body, contains('"artists":["Lofi & Sleep"]'));
      expect(body, contains('"durationMs":180000'));
    });

    for (final status in [405, 404]) {
      test(
          'a server with no such question ($status) means "no verdicts here": not an error, not asked again by the marks service',
          () async {
        server.unavailableStatus = status;

        final answer = await backend.unavailableAmong([lofi]);

        expect(answer, isNotNull);
        expect(answer!.supported, isFalse);
        expect(answer.verdicts, isEmpty);
      });
    }

    test(
        'a server that cannot be reached is "ask again later", which is not "no verdicts"',
        () async {
      server.online = false;

      expect(await backend.unavailableAmong([lofi]), isNull);
    });

    test('a server that errs (500) is also "ask again later"', () async {
      server.unavailableStatus = 500;

      expect(await backend.unavailableAmong([lofi]), isNull);
    });
  });

  group('the question by ref id (B-128)', () {
    test(
        'a library row is asked about by its ref id, one request for the list, in the order asked; asking makes no ref',
        () async {
      final gone = server.addRef('Lofi For Focus', 'Lofi & Sleep');
      final fine = server.addRef('Rainy Window', 'Lofi & Sleep');
      server.cannotGet['lofi for focus'] =
          (reason: 'not_found', retryIn: const Duration(days: 7));

      final answer = await backend.unavailableAmongRefs([fine, gone, 'sr_x']);

      expect(answer!.supported, isTrue);
      expect(answer.verdicts[0], isNull);
      expect(answer.verdicts[1]!.reason, 'not_found');
      expect(answer.verdicts[2], isNull, reason: 'an id the server never saw');
      expect(server.unavailableIdsAsked, [
        [fine, gone, 'sr_x']
      ]);
      expect(server.refs, hasLength(2), reason: 'a read: asking makes no ref');
    });

    test(
        'a server that does not list unavailable-ids is never sent the question (docs/17: an app never tries a route to find out)',
        () async {
      server.hasUnavailableIds = false;
      final ref = server.addRef('Lofi For Focus', 'Lofi & Sleep');

      final answer = await backend.unavailableAmongRefs([ref]);

      expect(answer!.supported, isFalse);
      expect(server.idsSentToAServerWithoutThem, 0);
      expect(server.unavailableIdsAsked, isEmpty);
    });

    for (final status in [400, 404, 405]) {
      test(
          'a $status on the question is "no verdicts here" too, a second layer behind the feature list',
          () async {
        final ref = server.addRef('Lofi For Focus', 'Lofi & Sleep');
        server.unavailableStatus = status;

        final answer = await backend.unavailableAmongRefs([ref]);

        expect(answer, isNotNull);
        expect(answer!.supported, isFalse);
      });
    }

    test('a server that cannot be reached or errs is "ask again later"',
        () async {
      final ref = server.addRef('Lofi For Focus', 'Lofi & Sleep');
      server.unavailableStatus = 500;
      expect(await backend.unavailableAmongRefs([ref]), isNull);

      server.unavailableStatus = null;
      server.online = false;
      expect(await backend.unavailableAmongRefs([ref]), isNull);
    });
  });

  group('a tap on a song the server cannot get', () {
    test(
        'is not saved, not played and not tried: the job fails with the server\'s own sentence',
        () async {
      final first = (await backend.start(lofi)).getOrThrow();
      ingested.clear();
      server.cannotGet['lofi for focus'] =
          (reason: 'not_found', retryIn: const Duration(days: 7));

      final job = (await backend.start(lofi)).getOrThrow();

      expect(job.id, first.id);
      expect(job.state, FetchState.failed);
      expect(job.error, 'unavailable');
      expect(job.message,
          'Nothing matching that song was found. Try again in a few days.');
      expect(ingested, isEmpty, reason: 'nothing was saved for it');
    });

    test('once the server stops believing it, the tap goes ahead as before',
        () async {
      await backend.start(lofi);
      ingested.clear();
      server.cannotGet['lofi for focus'] =
          (reason: 'not_found', retryIn: const Duration(days: 7));
      now = DateTime.now().add(const Duration(days: 8));

      final job = (await backend.start(lofi)).getOrThrow();

      expect(job.state, FetchState.ready);
      expect(ingested, hasLength(1));
    });

    test('an older server never says it, and the tap is what it always was',
        () async {
      await backend.start(lofi);
      ingested.clear();
      server.unavailableOnRefs = false;
      server.cannotGet['lofi for focus'] =
          (reason: 'not_found', retryIn: const Duration(days: 7));

      final job = (await backend.start(lofi)).getOrThrow();

      expect(job.state, FetchState.ready);
    });

    test('a song the server keeps is never refused, whatever a ref says',
        () async {
      final kept = server.addRef('Nude', 'Radiohead',
          album: 'In Rainbows', fileId: 'nd-1', meta: {'albumId': 'al0'});
      server.cannotGet['nude'] =
          (reason: 'removed', retryIn: const Duration(days: 7));

      final job = (await backend.start(const FetchRequest(
              artist: 'Radiohead', title: 'Nude', durationSec: 200)))
          .getOrThrow();

      expect(job.id, kept);
      expect(job.state, FetchState.ready);
    });
  });
}
