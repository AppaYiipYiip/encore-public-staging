import 'dart:async';

import 'package:dio/dio.dart';
import 'package:encore/core/logger.dart';
import 'package:encore/data/encore/encore_api.dart';
import 'package:encore/data/encore/encore_live.dart';
import 'package:encore/data/encore/encore_models.dart';
import 'package:encore/features/downloads/keep_providers.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';

import '../support/fake_encore_server.dart';

/// What a phone does about the server's side of its downloads (P2-22 parts 2 and 4): it says which downloads it watches, asks the server for the
/// songs it does not have yet, listens for the push, and says it all again after a reconnect.
class _Groups extends Notifier<List<KeepGroupKey>> {
  @override
  List<KeepGroupKey> build() => const [];

  void set(List<KeepGroupKey> groups) => state = groups;
}

final _groupsProvider =
    NotifierProvider<_Groups, List<KeepGroupKey>>(_Groups.new);

void main() {
  late FakeEncoreServer server;
  late EncoreApi api;
  late StreamController<LiveEvent> events;
  late StreamController<bool> connection;

  const playlist = KeepGroupKey('playlist', 'pl_1');
  const liked = KeepGroupKey('liked', 'liked');

  Map<String, Object?> groupJson(String kind, String id,
          {int total = 10,
          int ready = 0,
          int keeping = 0,
          int queued = 0,
          int failed = 0,
          int retryable = 0}) =>
      {
        'kind': kind,
        'id': id,
        'total': total,
        'ready': ready,
        'keeping': keeping,
        'queued': queued,
        'failed': failed,
        'retryable': retryable,
        'failures': <Object?>[],
      };

  setUp(() {
    server = FakeEncoreServer();
    api = EncoreApi(
      dio: Dio()..httpClientAdapter = server.adapter,
      baseUrl: () => Uri.parse('http://home.test:4540'),
      auth: () => {'u': 'tester', 't': 'tok', 's': 'salt'},
      deviceId: 'dv_phone',
    );
    events = StreamController<LiveEvent>.broadcast();
    connection = StreamController<bool>.broadcast();
    Log.clear();
  });

  tearDown(() async {
    await events.close();
    await connection.close();
  });

  List<Override> overrides({EncoreApi? withApi, bool noApi = false}) => [
        keepApiProvider.overrideWithValue(noApi ? null : (withApi ?? api)),
        keepEventsProvider.overrideWithValue(events.stream),
        keepConnectionProvider.overrideWithValue(connection.stream),
        keepGroupsProvider.overrideWith((ref) => ref.watch(_groupsProvider)),
        keepDebounceProvider.overrideWithValue(Duration.zero),
      ];

  ProviderContainer start(List<KeepGroupKey> groups, {bool noApi = false}) {
    final c = ProviderContainer(overrides: overrides(noApi: noApi));
    addTearDown(c.dispose);
    c.read(_groupsProvider.notifier).set(groups);
    c.listen(keepProvider, (_, __) {}); // the screens keep it alive
    return c;
  }

  Future<void> until(bool Function() done) async {
    for (var i = 0; i < 300 && !done(); i++) {
      await Future<void>.delayed(const Duration(milliseconds: 5));
    }
  }

  group('watching', () {
    test('it says which downloads it watches and keeps the answer', () async {
      server.keepGroups['playlist:pl_1'] =
          groupJson('playlist', 'pl_1', ready: 4, queued: 6);
      server.keepGroups['liked:liked'] = groupJson('liked', 'liked', ready: 10);

      final c = start([playlist, liked]);
      await until(() => c.read(keepProvider).answered);

      final state = c.read(keepProvider);
      expect(server.keepWatches, [
        ['playlist:pl_1', 'liked:liked']
      ]);
      expect(state.supported, isTrue);
      expect(state.of(playlist)?.queued, 6);
      expect(state.of(liked)?.serverHasAll, isTrue);
      expect(server.keepWatchDevices.single, 'dv_phone');
    });

    test('a server that keeps no songs is not asked about them', () async {
      server.hasKeep = false;

      final c = start([playlist]);
      await until(() => c.read(keepProvider).supported == false);
      await Future<void>.delayed(const Duration(milliseconds: 40));

      expect(c.read(keepProvider).supported, isFalse);
      expect(server.keepWatches, isEmpty);
      expect(server.keepAsks, isEmpty);
    });

    test('a phone that is not on an Encore server has nothing to watch',
        () async {
      final c = start([playlist], noApi: true);
      await Future<void>.delayed(const Duration(milliseconds: 40));

      expect(c.read(keepProvider).supported, isFalse);
      expect(server.keepWatches, isEmpty);
    });

    test('with nothing pinned it asks nothing', () async {
      final c = start(const []);
      await Future<void>.delayed(const Duration(milliseconds: 40));

      expect(server.keepWatches, isEmpty);
      expect(c.read(keepProvider).supported, isTrue);
    });

    test('what the server pushes is shown at once, without a request',
        () async {
      server.keepGroups['playlist:pl_1'] =
          groupJson('playlist', 'pl_1', queued: 10);
      final c = start([playlist]);
      await until(() => c.read(keepProvider).answered);
      final before = server.calls.values.fold<int>(0, (a, b) => a + b);

      events.add(LiveEvent('keep.progress', {
        'groups': [groupJson('playlist', 'pl_1', ready: 7, queued: 3)],
        'youtube': {'state': 'resting', 'resumesInSec': 600},
        'serverTime': 1,
      }));
      await until(() => c.read(keepProvider).of(playlist)?.ready == 7);

      expect(c.read(keepProvider).of(playlist)?.ready, 7);
      expect(c.read(keepProvider).youtube.resting, isTrue);
      expect(server.calls.values.fold<int>(0, (a, b) => a + b), before);
    });

    test('a new pin is watched, and a removed one is dropped', () async {
      server.keepGroups['playlist:pl_1'] =
          groupJson('playlist', 'pl_1', ready: 10);
      server.keepGroups['liked:liked'] =
          groupJson('liked', 'liked', ready: 3, queued: 2);
      final c = start([playlist]);
      await until(() => c.read(keepProvider).answered);

      c.read(_groupsProvider.notifier).set([playlist, liked]);
      await until(() => c.read(keepProvider).of(liked) != null);
      expect(server.keepWatches.last, ['playlist:pl_1', 'liked:liked']);

      c.read(_groupsProvider.notifier).set([liked]);
      await until(() => c.read(keepProvider).of(playlist) == null);
      expect(c.read(keepProvider).of(liked), isNotNull);
    });

    test(
        'a download the server does not answer for is noted once, never silent',
        () async {
      server.keepGroups['liked:liked'] = groupJson('liked', 'liked', ready: 3);

      final c = start([playlist, liked]);
      await until(() => c.read(keepProvider).answered);

      expect(c.read(keepProvider).missing, {playlist});
      final warnings =
          Log.recent.where((r) => r.message.contains('pl_1')).length;
      expect(warnings, 1);

      c.read(_groupsProvider.notifier).set([liked, playlist]);
      await until(() => server.keepWatches.length >= 2);
      await Future<void>.delayed(const Duration(milliseconds: 20));
      expect(Log.recent.where((r) => r.message.contains('pl_1')).length, 1,
          reason: 'the same download is not reported again and again');
    });

    test('a watch that fails keeps what the phone knew and says it is old',
        () async {
      server.keepGroups['playlist:pl_1'] =
          groupJson('playlist', 'pl_1', ready: 4, queued: 6);
      final c = start([playlist]);
      await until(() => c.read(keepProvider).answered);

      server.online = false;
      connection.add(true);
      await until(() => c.read(keepProvider).stale);

      expect(c.read(keepProvider).stale, isTrue);
      expect(c.read(keepProvider).of(playlist)?.ready, 4,
          reason:
              'the numbers stay for the screens to decide (the phone\'s reason wins when it is away)');
    });
  });

  group('asking', () {
    test('what has songs still to come is asked for, once per connection',
        () async {
      server.keepGroups['playlist:pl_1'] =
          groupJson('playlist', 'pl_1', ready: 4, queued: 6);
      server.keepGroups['liked:liked'] = groupJson('liked', 'liked', ready: 10);

      final c = start([playlist, liked]);
      await until(() => server.keepAsks.isNotEmpty);

      expect(
          server.keepAsks,
          [
            ['playlist:pl_1']
          ],
          reason: 'a download the server has all of is not asked for');

      // the same connection: nothing more, however often it is looked at
      c.read(keepProvider.notifier).refresh();
      await until(() => server.keepWatches.length >= 2);
      await Future<void>.delayed(const Duration(milliseconds: 30));
      expect(server.keepWatches, hasLength(2));
      expect(server.keepAsks, hasLength(1));

      // a new connection says it all again, and asks again
      connection.add(false);
      connection.add(true);
      await until(() => server.keepAsks.length >= 2);
      expect(server.keepAsks.last, ['playlist:pl_1']);
      expect(server.keepWatches.length, greaterThanOrEqualTo(3),
          reason: 'and the watch is said again on every reconnect');
    });

    test(
        'a newly pinned download is asked at once, the rest are not asked again',
        () async {
      server.keepGroups['playlist:pl_1'] =
          groupJson('playlist', 'pl_1', ready: 4, queued: 6);
      server.keepGroups['liked:liked'] =
          groupJson('liked', 'liked', ready: 1, queued: 9);
      final c = start([playlist]);
      await until(() => server.keepAsks.isNotEmpty);

      c.read(_groupsProvider.notifier).set([playlist, liked]);
      await until(() => server.keepAsks.length >= 2);

      expect(server.keepAsks.last, ['liked:liked']);
    });

    test('a server that cannot be asked is still watched', () async {
      server.hasKeepAsk = false;
      server.keepGroups['playlist:pl_1'] =
          groupJson('playlist', 'pl_1', ready: 4, queued: 6);

      final c = start([playlist]);
      await until(() => c.read(keepProvider).answered);
      await Future<void>.delayed(const Duration(milliseconds: 30));

      expect(server.keepAsks, isEmpty);
      expect(c.read(keepProvider).of(playlist)?.queued, 6);
    });

    test('a download whose rest can never come is not asked for', () async {
      server.keepGroups['playlist:pl_1'] =
          groupJson('playlist', 'pl_1', ready: 7, failed: 3, retryable: 0);

      final c = start([playlist]);
      await until(() => c.read(keepProvider).answered);
      await Future<void>.delayed(const Duration(milliseconds: 30));

      expect(server.keepAsks, isEmpty,
          reason:
              'YouTube does not have those songs: there is nothing to ask for');
    });

    test(
        'songs that failed but could be helped are left to the server to judge, once per connection',
        () async {
      server.keepGroups['playlist:pl_1'] =
          groupJson('playlist', 'pl_1', ready: 7, failed: 3, retryable: 3);

      start([playlist]);
      await until(() => server.keepAsks.isNotEmpty);
      await Future<void>.delayed(const Duration(milliseconds: 30));

      expect(server.keepAsks, hasLength(1),
          reason:
              'a song nobody fetched is asked for; one whose keep failed is not tried by the server, only by Retry');
    });
  });

  group('Retry', () {
    test('asks the server again for ONE download and shows its answer',
        () async {
      server.keepGroups['liked:liked'] = groupJson('liked', 'liked',
          total: 3, ready: 1, failed: 2, retryable: 2);
      final c = start([liked]);
      await until(() => c.read(keepProvider).answered);

      final retried = await c.read(keepProvider.notifier).retry(liked);

      expect(retried, 2);
      expect(server.keepRetries, ['liked:liked']);
    });

    test('a download that is gone says so and changes nothing', () async {
      final c = start([liked]);
      await until(() => c.read(keepProvider).answered);

      final retried = await c.read(keepProvider.notifier).retry(playlist);

      expect(retried, isNull);
    });
  });
}
