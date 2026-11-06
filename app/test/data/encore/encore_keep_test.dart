import 'package:dio/dio.dart';
import 'package:encore/core/result.dart';
import 'package:encore/data/encore/encore_api.dart';
import 'package:encore/data/encore/encore_models.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_encore_server.dart';

/// The calls that tell a phone how the server is getting the songs of its downloads (P2-22, docs/17 "Keep progress"): `PUT keep/watch`,
/// `POST keep/ask`, `POST keep/retry`, and how their answers are read.
void main() {
  late FakeEncoreServer server;
  late EncoreApi api;

  Map<String, Object?> groupJson(String kind, String id,
          {int total = 10,
          int ready = 0,
          int keeping = 0,
          int queued = 0,
          int failed = 0,
          int retryable = 0,
          List<Map<String, Object?>> failures = const []}) =>
      {
        'kind': kind,
        'id': id,
        'total': total,
        'ready': ready,
        'keeping': keeping,
        'queued': queued,
        'failed': failed,
        'retryable': retryable,
        'failures': failures,
      };

  setUp(() {
    server = FakeEncoreServer();
    api = EncoreApi(
      dio: Dio()..httpClientAdapter = server.adapter,
      baseUrl: () => Uri.parse('http://home.test:4540'),
      auth: () => {'u': 'tester', 't': 'tok', 's': 'salt'},
      deviceId: 'dv_phone',
    );
  });

  group('how an answer is read', () {
    test('the numbers of a download, its failures, and YouTube', () {
      final progress = KeepProgress.fromJson({
        'groups': [
          groupJson('playlist', 'pl_1',
              total: 217,
              ready: 40,
              keeping: 1,
              queued: 173,
              failed: 3,
              retryable: 2,
              failures: [
                {
                  'ref': 'sr_a',
                  'title': 'Nude',
                  'artist': 'Radiohead',
                  'reason': 'YouTube is resting.',
                  'retry': true,
                },
                {
                  'ref': 'sr_b',
                  'title': 'Weird Fishes',
                  'artist': 'Radiohead',
                  'reason': 'Not found.',
                  'retry': false,
                },
              ]),
        ],
        'youtube': {'state': 'resting', 'resumesInSec': 5400},
        'serverTime': 1790000000000,
      });

      final one = progress.groups.single;
      expect((one.kind, one.id), ('playlist', 'pl_1'));
      expect((one.total, one.ready, one.keeping, one.queued, one.failed),
          (217, 40, 1, 173, 3));
      expect(one.retryable, 2);
      expect(one.failures.map((f) => f.title), ['Nude', 'Weird Fishes']);
      expect(one.failures.map((f) => f.retry), [true, false]);
      expect(one.failures.first.reason, 'YouTube is resting.');
      expect(progress.youtube.state, 'resting');
      expect(progress.youtube.resumesInSec, 5400);
      expect(progress.youtube.resting, isTrue);
    });

    test('a strange value is a zero, never an exception', () {
      final progress = KeepProgress.fromJson({
        'groups': [
          {'kind': 'liked', 'id': 'liked', 'total': 'many', 'ready': null},
          'not a group',
          {'id': 'no kind'},
        ],
        'youtube': 'resting',
      });

      expect(progress.groups, hasLength(1),
          reason: 'only a group with a kind and an id is one');
      expect(progress.groups.single.total, 0);
      expect(progress.groups.single.ready, 0);
      expect(progress.youtube.state, 'off');
      expect(progress.youtube.resting, isFalse);
    });

    test('a group is found by its kind and id', () {
      final progress = KeepProgress.fromJson({
        'groups': [groupJson('playlist', 'pl_1'), groupJson('liked', 'liked')],
      });

      expect(progress.of(const KeepGroupKey('liked', 'liked'))?.kind, 'liked');
      expect(progress.of(const KeepGroupKey('playlist', 'pl_2')), isNull);
    });

    test(
        'what is outstanding: not on the server yet, and nothing is coming for the failed',
        () {
      final g = KeepGroup.fromJson(groupJson('playlist', 'pl_1',
          total: 10, ready: 4, keeping: 1, queued: 3, failed: 2, retryable: 1));

      expect(g.waiting, 4,
          reason: 'being kept and queued: the server is on its way');
      expect(g.serverHasAll, isFalse);
      expect(
          KeepGroup.fromJson(groupJson('liked', 'liked', total: 3, ready: 3))
              .serverHasAll,
          isTrue);
      expect(
          KeepGroup.fromJson(groupJson('liked', 'liked', total: 0))
              .serverHasAll,
          isFalse,
          reason: 'an empty download has nothing the server has');
    });
  });

  group('the calls', () {
    test('watch names the downloads and this device, and reads the answer',
        () async {
      server.keepGroups['playlist:pl_1'] =
          groupJson('playlist', 'pl_1', ready: 4, queued: 6);
      server.keepGroups['liked:liked'] = groupJson('liked', 'liked', ready: 10);

      final result = await api.watchKeep(const [
        KeepGroupKey('playlist', 'pl_1'),
        KeepGroupKey('liked', 'liked'),
        KeepGroupKey('playlist', 'pl_gone'),
      ]);

      final progress = result.valueOrNull!;
      expect(progress.groups.map((g) => g.id), ['pl_1', 'liked'],
          reason:
              'a download the person does not have is left out by the server');
      expect(server.keepWatches.single,
          ['playlist:pl_1', 'liked:liked', 'playlist:pl_gone']);
      expect(server.keepWatchDevices.single, 'dv_phone',
          reason:
              'the push goes to the device the server finds in this header');
    });

    test('a release carries the songs the phone knows, a playlist carries none',
        () {
      expect(const KeepGroupKey('playlist', 'pl_1').toJson(),
          {'kind': 'playlist', 'id': 'pl_1'});
      expect(
          const KeepGroupKey('release', 'cat:9', refs: ['sr_a', 'sr_b'])
              .toJson(),
          {
            'kind': 'release',
            'id': 'cat:9',
            'refs': ['sr_a', 'sr_b']
          });
    });

    test('ask says how many songs were asked for and how the downloads go now',
        () async {
      server.keepGroups['playlist:pl_1'] =
          groupJson('playlist', 'pl_1', ready: 4, queued: 6);

      final result =
          await api.askKeep(const [KeepGroupKey('playlist', 'pl_1')]);

      final asked = result.valueOrNull!;
      expect(asked.asked, 6);
      expect(asked.progress.groups.single.queued, 6);
      expect(server.keepAsks.single, ['playlist:pl_1']);
    });

    test('retry names ONE download and reads how many songs were asked for',
        () async {
      server.keepGroups['liked:liked'] = groupJson('liked', 'liked',
          total: 3, ready: 1, failed: 2, retryable: 2);

      final result = await api.retryKeep(const KeepGroupKey('liked', 'liked'));

      expect(result.valueOrNull!.retried, 2);
      expect(result.valueOrNull!.group?.failed, 2);
      expect(server.keepRetries, ['liked:liked']);
    });

    test('a download that does not exist (any more) is not found, not a crash',
        () async {
      final result =
          await api.retryKeep(const KeepGroupKey('playlist', 'pl_gone'));

      expect(result, isA<Err<Object?>>());
      expect(result.failureOrNull, isA<NotFoundFailure>());
    });

    test(
        'a server without the calls answers not found and the app gets a failure it can read',
        () async {
      server.hasKeep = false;

      final watch = await api.watchKeep(const [KeepGroupKey('liked', 'liked')]);

      expect(watch.failureOrNull, isA<NotFoundFailure>());
    });
  });

  group('what the server says it can do', () {
    test('keep and keep-ask are read from info', () async {
      final info = (await api.info()).valueOrNull!;

      expect(info.hasKeep, isTrue);
      expect(info.hasKeepAsk, isTrue);
    });

    test('an older server that keeps songs but cannot be asked says so',
        () async {
      server.hasKeepAsk = false;

      final info = (await api.info()).valueOrNull!;

      expect(info.hasKeep, isTrue);
      expect(info.hasKeepAsk, isFalse);
    });

    test('a server that keeps no songs lists neither', () async {
      server.hasKeep = false;

      final info = (await api.info()).valueOrNull!;

      expect((info.hasKeep, info.hasKeepAsk), (false, false));
    });
  });
}
