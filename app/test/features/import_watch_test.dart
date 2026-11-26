import 'dart:async';

import 'package:dio/dio.dart';
import 'package:encore/app/app_in_front.dart';
import 'package:encore/app/providers.dart';
import 'package:encore/core/clock.dart';
import 'package:encore/data/encore/encore_api.dart';
import 'package:encore/data/encore/encore_live.dart';
import 'package:encore/features/downloads/keep_providers.dart';
import 'package:encore/features/import/import_watch.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';

import '../support/fake_encore_server.dart';

/// docs/design S-95 (P2-29): what the card of an import knows. The server pushes `import.progress` when a song has been matched and when an import is
/// stopped (flat: `importId, state, total, matched, unmatched, pending, kept`); an older server says nothing when it stores a song, so the watch reads
/// `GET imports` at the start, at every (re)connection and every return to the app, takes the pushes as they come, and asks again every few seconds
/// ONLY while an import is still saving. Idle, it does nothing. A server that lists `import-kept` (N-43) pushes when it stores a song too: it is never
/// asked in between.
void main() {
  late FakeEncoreServer server;
  late EncoreApi api;
  late StreamController<LiveEvent> events;
  late StreamController<bool> connection;
  late FakeClock clock;

  Map<String, Object?> row(
    String id, {
    String state = 'running',
    int total = 217,
    int matched = 0,
    int unmatched = 0,
    int pending = 217,
    int kept = 0,
    String? playlistId = 'pl_1',
  }) =>
      {
        'id': id,
        'source': 'youtube',
        'name': 'Prog snob',
        'state': state,
        'playlistId': playlistId,
        'total': total,
        'matched': matched,
        'unmatched': unmatched,
        'pending': pending,
        'kept': kept,
        'truncated': false,
        'createdAt': clock.now().millisecondsSinceEpoch,
      };

  setUp(() {
    server = FakeEncoreServer();
    api = EncoreApi(
      dio: Dio()..httpClientAdapter = server.adapter,
      baseUrl: () => Uri.parse('http://home.test:4540'),
      auth: () => {'u': 'tester', 't': 'tok', 's': 's'},
      deviceId: 'dv_phone',
    );
    events = StreamController<LiveEvent>.broadcast();
    connection = StreamController<bool>.broadcast();
    clock = FakeClock(DateTime(2026, 11, 24, 9, 0));
  });

  tearDown(() async {
    await events.close();
    await connection.close();
  });

  ProviderContainer start({
    bool onEncore = true,
    Duration poll = const Duration(milliseconds: 20),
    List<Override> more = const [],
  }) {
    final c = ProviderContainer(overrides: [
      keepApiProvider.overrideWithValue(onEncore ? api : null),
      keepEventsProvider.overrideWithValue(events.stream),
      keepConnectionProvider.overrideWithValue(connection.stream),
      clockProvider.overrideWithValue(clock),
      importPollProvider.overrideWithValue(poll),
      ...more,
    ]);
    addTearDown(c.dispose);
    c.listen(importWatchProvider, (_, __) {});
    return c;
  }

  Future<void> settle() =>
      Future<void>.delayed(const Duration(milliseconds: 80));

  int asked() => server.calls['GET imports'] ?? 0;

  test('it reads the imports once at the start and says what it found',
      () async {
    server.importRows.add(row('im_1'));
    final c = start();
    await settle();

    expect(c.read(importWatchProvider).imports.single.id, 'im_1');
    expect(asked(), greaterThan(0));
  });

  test('a push of import.progress changes the counts without asking again',
      () async {
    server.importRows.add(row('im_1'));
    final c = start(poll: const Duration(hours: 1));
    await settle();
    final before = asked();

    events.add(const LiveEvent('import.progress', {
      'importId': 'im_1',
      'state': 'running',
      'total': 217,
      'matched': 120,
      'unmatched': 3,
      'pending': 94,
      'kept': 10,
    }));
    await Future<void>.delayed(const Duration(milliseconds: 10));

    final i = c.read(importWatchProvider).imports.single;
    expect([i.matched, i.unmatched, i.pending, i.kept], [120, 3, 94, 10]);
    expect(asked(), before, reason: 'the push said it all: no request');
  });

  test('a push for an import the phone does not know reads the list', () async {
    final c = start(poll: const Duration(hours: 1));
    await settle();
    expect(c.read(importWatchProvider).imports, isEmpty);

    server.importRows.add(row('im_9'));
    events.add(const LiveEvent('import.progress', {
      'importId': 'im_9',
      'state': 'running',
      'total': 217,
      'matched': 1,
      'unmatched': 0,
      'pending': 216,
      'kept': 0,
    }));
    await settle();

    expect(c.read(importWatchProvider).imports.single.id, 'im_9',
        reason: 'an import started on another device of the person');
  });

  test('a connection that comes back reads the list again', () async {
    start(poll: const Duration(hours: 1));
    await settle();
    final before = asked();

    connection.add(true);
    await settle();

    expect(asked(), greaterThan(before));
  });

  test('coming back to the app reads the list again, leaving asks nothing',
      () async {
    final c = start(
      poll: const Duration(hours: 1),
      more: [appInFrontProvider.overrideWith(_Front.new)],
    );
    await settle();
    final before = asked();
    final front = c.read(appInFrontProvider.notifier) as _Front;

    front.set(false);
    await settle();
    expect(asked(), before);
    front.set(true);
    await settle();

    expect(asked(), greaterThan(before));
  });

  group('while something is saving it asks again, and only then', () {
    test('a running import is asked about until it is over', () async {
      server.importRows.add(row('im_1'));
      start();
      await settle();
      final first = asked();
      await settle();

      expect(asked(), greaterThan(first));
    });

    test('an import that is done and kept everything is not asked about',
        () async {
      server.importRows.add(row('im_1',
          state: 'done', matched: 214, unmatched: 3, pending: 0, kept: 214));
      start();
      await settle();
      final before = asked();
      await settle();
      await settle();

      expect(asked(), before, reason: 'idle: no poller');
    });

    test(
        'done but the server still has songs to keep: saving, and it goes on being asked',
        () async {
      server.importRows.add(row('im_1',
          state: 'done', matched: 214, unmatched: 3, pending: 0, kept: 150));
      final c = start();
      await settle();

      expect(c.read(importWatchProvider).saving, {'im_1'});
      final before = asked();
      await settle();
      expect(asked(), greaterThan(before));
    });

    test(
        'the server keeps a song: the next look sees it, and the last song ends the saving',
        () async {
      server.importRows.add(row('im_1',
          state: 'done',
          total: 4,
          matched: 4,
          unmatched: 0,
          pending: 0,
          kept: 3));
      final c = start();
      await settle();
      expect(c.read(importWatchProvider).saving, {'im_1'});

      server.importRows.single['kept'] = 4;
      await settle();

      expect(c.read(importWatchProvider).saving, isEmpty);
    });

    test(
        'songs that never come are not waited for for ever: no change in half an hour is settled',
        () async {
      server.importRows.add(row('im_1',
          state: 'done', matched: 214, unmatched: 3, pending: 0, kept: 150));
      final c = start();
      await settle();
      expect(c.read(importWatchProvider).saving, {'im_1'});

      clock.advance(const Duration(minutes: 31));
      await settle();

      expect(c.read(importWatchProvider).saving, isEmpty);
    });

    test('an import of yesterday is not shown again when the app starts',
        () async {
      server.importRows.add({
        ...row('im_1', state: 'done', matched: 214, pending: 0, kept: 150),
        'createdAt': clock
            .now()
            .subtract(const Duration(hours: 30))
            .millisecondsSinceEpoch,
      });
      final c = start();
      await settle();

      expect(c.read(importWatchProvider).saving, isEmpty);
    });
  });

  group('an import the server calls running that moves no more', () {
    // The same patience as for the saving: half an hour with no change of state, found, not found, waiting or kept.
    test(
        'after half an hour with no change it is stalled, and nothing is asked for it any more',
        () async {
      server.importRows.add(row('im_1', matched: 117, pending: 100));
      final c = start();
      await settle();
      expect(c.read(importWatchProvider).stalled, isEmpty,
          reason: 'it is only just seen');
      final first = asked();
      await settle();
      expect(asked(), greaterThan(first), reason: 'still asked while it moves');

      clock.advance(const Duration(minutes: 31));
      await settle();
      expect(c.read(importWatchProvider).stalled, {'im_1'});

      final before = asked();
      await settle();
      await settle();
      expect(asked(), before, reason: 'no poller for an import that is stuck');
    });

    test('half an hour is not yet stuck: it is still asked about', () async {
      server.importRows.add(row('im_1', matched: 117, pending: 100));
      final c = start();
      await settle();

      clock.advance(const Duration(minutes: 29));
      await settle();
      final before = asked();
      await settle();

      expect(c.read(importWatchProvider).stalled, isEmpty);
      expect(asked(), greaterThan(before));
    });

    test('a count that moves keeps it alive however long it takes', () async {
      server.importRows.add(row('im_1', matched: 117, pending: 100));
      final c = start();
      await settle();

      clock.advance(const Duration(minutes: 29));
      server.importRows.single['matched'] = 118;
      server.importRows.single['pending'] = 99;
      await settle();
      clock.advance(const Duration(minutes: 29));
      await settle();

      expect(c.read(importWatchProvider).stalled, isEmpty);
    });

    test(
        'a push that changes the counts brings it back, and it is asked about again',
        () async {
      server.importRows.add(row('im_1', matched: 117, pending: 100));
      final c = start();
      await settle();
      clock.advance(const Duration(minutes: 31));
      await settle();
      expect(c.read(importWatchProvider).stalled, {'im_1'});
      final stuck = asked();

      events.add(const LiveEvent('import.progress', {
        'importId': 'im_1',
        'state': 'running',
        'total': 217,
        'matched': 130,
        'unmatched': 0,
        'pending': 87,
        'kept': 0,
      }));
      await settle();

      expect(c.read(importWatchProvider).stalled, isEmpty);
      expect(asked(), greaterThan(stuck));
    });

    test(
        'coming back to the app still reads the list (once), and it stays stalled while nothing moved',
        () async {
      server.importRows.add(row('im_1', matched: 117, pending: 100));
      final c = start(more: [appInFrontProvider.overrideWith(_Front.new)]);
      await settle();
      clock.advance(const Duration(minutes: 31));
      await settle();
      final stuck = asked();
      final front = c.read(appInFrontProvider.notifier) as _Front;

      front.set(false);
      await settle();
      front.set(true);
      await settle();
      await settle();

      expect(asked(), stuck + 1, reason: 'one look at the return, no poller');
      expect(c.read(importWatchProvider).stalled, {'im_1'});
    });

    test(
        'a connection that comes back does not give a stuck import another half hour',
        () async {
      server.importRows.add(row('im_1', matched: 117, pending: 100));
      final c = start();
      await settle();
      clock.advance(const Duration(minutes: 31));
      await settle();
      expect(c.read(importWatchProvider).stalled, {'im_1'});
      final stuck = asked();

      connection.add(true);
      await settle();
      await settle();

      expect(c.read(importWatchProvider).stalled, {'im_1'},
          reason: 'a flaky line must not keep a stuck import asked about');
      expect(asked(), stuck + 1, reason: 'the one look of the reconnection');
    });

    test('an import that ended is never called stalled', () async {
      server.importRows.add(row('im_1',
          state: 'done', matched: 214, unmatched: 3, pending: 0, kept: 214));
      final c = start();
      await settle();
      clock.advance(const Duration(minutes: 31));
      // Nothing is asked for an import that is over, so the look is made by the connection coming back.
      connection.add(true);
      await settle();

      expect(c.read(importWatchProvider).stalled, isEmpty);
    });
  });

  group('on a server that pushes what it stores (import-kept, N-43)', () {
    setUp(() => server.hasImportKept = true);

    Map<String, Object?> pushed(int kept) => {
          'importId': 'im_1',
          'state': 'done',
          'total': 217,
          'matched': 214,
          'unmatched': 3,
          'pending': 0,
          'kept': kept,
        };

    test('a running import is read at the start and never asked about again',
        () async {
      server.importRows.add(row('im_1'));
      start();
      await settle();
      final first = asked();
      expect(first, greaterThan(0));
      await settle();
      await settle();

      expect(asked(), first, reason: 'the server says what it stores');
    });

    test('done, songs still to keep: saving, and still not asked about',
        () async {
      server.importRows.add(row('im_1',
          state: 'done', matched: 214, unmatched: 3, pending: 0, kept: 150));
      final c = start();
      await settle();

      expect(c.read(importWatchProvider).saving, {'im_1'});
      final first = asked();
      await settle();
      await settle();
      expect(asked(), first);
    });

    test('each stored song is a push and the card follows it with no request',
        () async {
      server.importRows.add(row('im_1',
          state: 'done', matched: 214, unmatched: 3, pending: 0, kept: 150));
      final c = start();
      await settle();
      final first = asked();

      for (final kept in [151, 152, 153]) {
        events.add(LiveEvent('import.progress', pushed(kept)));
        await Future<void>.delayed(const Duration(milliseconds: 10));
        expect(c.read(importWatchProvider).imports.single.kept, kept);
      }
      expect(asked(), first);
    });

    test(
        'a connection that comes back still reads the list: a push may be lost',
        () async {
      server.importRows.add(row('im_1'));
      start();
      await settle();
      final before = asked();

      connection.add(true);
      await settle();

      expect(asked(), greaterThan(before));
    });

    test('when what the server can do cannot be read, it asks as it always did',
        () async {
      server.failInfo = true;
      server.importRows.add(row('im_1'));
      start();
      await settle();
      final first = asked();
      await settle();

      expect(asked(), greaterThan(first));
    });
  });

  test('a stop pressed on this phone is remembered as ours', () async {
    server.importRows.add(row('im_1'));
    final c = start(poll: const Duration(hours: 1));
    await settle();

    await c.read(importWatchProvider.notifier).stop('im_1');

    expect(c.read(importWatchProvider).stoppedHere, {'im_1'});
  });

  test('on a server that is not an Encore server there is nothing to watch',
      () async {
    final c = start(onEncore: false);
    await settle();

    expect(c.read(importWatchProvider).imports, isEmpty);
    expect(asked(), 0);
  });
}

/// The app's place in front of the person, moved by the test.
class _Front extends AppInFront {
  @override
  bool build() => true;

  void set(bool value) => state = value;
}
