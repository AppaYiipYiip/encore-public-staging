import 'package:drift/drift.dart' show Value;
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/encore/encore_models.dart';
import 'package:encore/features/downloads/download_status.dart';
import 'package:encore/features/downloads/keep_providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../support/test_app.dart';

/// A download on a server that keeps songs, in the Library (docs/design S-16 "the two stages", P2-22 parts 2 and 4): the line says both stages, the
/// bar has two tones, and what did not come is named with Retry. The server's answer is arranged here; the app around it is the real one.
class _Keep extends KeepController {
  _Keep(this.initial);

  final KeepState initial;
  final List<KeepGroupKey> retried = [];

  @override
  KeepState build() => initial;

  @override
  Future<int?> retry(KeepGroupKey key) async {
    retried.add(key);
    return 1;
  }
}

KeepGroup serverGroup(String id,
        {int total = 6,
        int ready = 0,
        int keeping = 0,
        int queued = 0,
        int failed = 0,
        int retryable = 0,
        List<KeepFailure> failures = const []}) =>
    KeepGroup(
      kind: 'playlist',
      id: id,
      total: total,
      ready: ready,
      keeping: keeping,
      queued: queued,
      failed: failed,
      retryable: retryable,
      failures: failures,
    );

void main() {
  playlistPage();
  setUpAll(loadAppFonts);
  setUp(() =>
      SharedPreferences.setMockInitialValues({'encore.libraryScope': 'mine'}));

  Future<void> open(WidgetTester tester, String location) async {
    final element = tester.element(find.byType(Scaffold).first);
    GoRouter.of(element).go(location);
    await settle(tester);
  }

  Future<void> pin(
          ({AppDatabase db, FakePlaybackFacade facade, int serverId}) app,
          String type,
          String id) =>
      app.db.into(app.db.pins).insert(PinsCompanion.insert(
            serverId: app.serverId,
            targetType: type,
            targetId: id,
            createdAtMs: 1,
          ));

  Future<void> onPhone(
      ({AppDatabase db, FakePlaybackFacade facade, int serverId}) app,
      Iterable<String> trackIds) async {
    for (final id in trackIds) {
      await app.db.into(app.db.downloads).insert(DownloadsCompanion.insert(
            serverId: app.serverId,
            trackId: id,
            state: const Value(2),
            localPath: Value('/x/$id.opus'),
            bytes: const Value(5 * 1024 * 1024),
            updatedAtMs: 0,
          ));
    }
  }

  Future<({_Keep keep, AppDatabase db})> arrange(
    WidgetTester tester,
    Map<KeepGroupKey, KeepGroup> groups, {
    KeepYoutube youtube = const KeepYoutube(),
    DateTime? restingUntil,
    String playlist = 'pl1',
    List<String> onThePhone = const ['al3-t1'],
  }) async {
    final keep = _Keep(KeepState(
        supported: true,
        answered: true,
        groups: groups,
        youtube: youtube,
        restingUntil: restingUntil));
    final app = await pumpApp(tester,
        size: const Size(390, 1400),
        overrides: [keepProvider.overrideWith(() => keep)]);
    await pin(app, 'playlist', playlist); // pl1 is Prog Snob: six songs
    await onPhone(app, onThePhone); // by default one of them is on the phone
    await open(tester, '/library');
    await tester.ensureVisible(find.text('Downloaded'));
    await tester.pump();
    await tester.tap(find.text('Downloaded'));
    await settle(tester);
    return (keep: keep, db: app.db);
  }

  testWidgets('both stages in one line, and a bar of two tones',
      (tester) async {
    final shown = await arrange(tester, {
      const KeepGroupKey('playlist', 'pl1'):
          serverGroup('pl1', ready: 3, queued: 3)
    });

    expect(find.text('1 of 6 on this phone · 3 ready on your server'),
        findsOneWidget);
    expect(
        find.text('Playlist • 1 of 6 on this phone · 3 ready on your server'),
        findsNothing,
        reason: 'a download in progress takes the whole line');
    final bar = tester.widget<DownloadBar>(find.byType(DownloadBar));
    expect(bar.phoneFraction, closeTo(1 / 6, 1e-9));
    expect(bar.serverFraction, closeTo(3 / 6, 1e-9));
    await closeApp(tester, shown.db);
  });

  testWidgets(
      'a long line of the two stages gets two lines, never cut off in the middle of a word',
      (tester) async {
    final shown = await arrange(tester, {
      const KeepGroupKey('playlist', 'pl1'):
          serverGroup('pl1', ready: 3, queued: 3)
    });

    final line = tester.widget<Text>(
        find.text('1 of 6 on this phone · 3 ready on your server'));

    expect(line.maxLines, 2);
    await closeApp(tester, shown.db);
  });

  testWidgets('the server resting says until when', (tester) async {
    final shown = await arrange(
      tester,
      {
        const KeepGroupKey('playlist', 'pl1'):
            serverGroup('pl1', ready: 1, queued: 5)
      },
      youtube: const KeepYoutube(state: 'resting', resumesInSec: 3600),
      restingUntil: DateTime(2026, 10, 15, 21, 40),
    );

    expect(
        find.text('1 of 6 on this phone · your server is resting until 21:40'),
        findsOneWidget);
    await closeApp(tester, shown.db);
  });

  testWidgets(
      'songs that did not come are named, with Retry that asks the server again',
      (tester) async {
    final shown = await arrange(tester, {
      const KeepGroupKey('playlist', 'pl1'): serverGroup('pl1',
          ready: 4,
          failed: 2,
          retryable: 1,
          failures: const [
            KeepFailure(
                ref: 'sr_a',
                title: 'Nude',
                artist: 'Radiohead',
                reason: 'YouTube is resting.',
                retry: true),
            KeepFailure(
                ref: 'sr_b',
                title: 'Weird Fishes',
                artist: 'Radiohead',
                reason: 'Not found.',
                retry: false),
          ]),
    }, onThePhone: const [
      'al3-t1',
      'al3-t2',
      'al4-t1',
      'al5-t3'
    ]);

    expect(find.text('4 of 6 on this phone · 2 songs did not come'),
        findsOneWidget);
    expect(find.text('Nude: YouTube is resting.'), findsOneWidget);
    expect(find.text('Weird Fishes: Not found.'), findsOneWidget);

    await tester.tap(find.text('Retry'));
    await tester.pump();

    expect(shown.keep.retried, [const KeepGroupKey('playlist', 'pl1')]);
    await closeApp(tester, shown.db);
  });

  testWidgets('a finished download keeps the words it always had',
      (tester) async {
    final shown = await arrange(
      tester,
      {
        const KeepGroupKey('playlist', 'pl2'):
            serverGroup('pl2', total: 3, ready: 3)
      },
      playlist: 'pl2', // Late night: three songs
      onThePhone: ['al1-t1', 'al2-t3', 'al2-t4'],
    );

    expect(find.text('Playlist • Downloaded • 3 songs'), findsOneWidget);
    expect(find.byType(DownloadBar), findsNothing);
    await closeApp(tester, shown.db);
  });

  testWidgets(
      'without an answer from the server the row says what the phone has',
      (tester) async {
    final shown = await arrange(tester, {});

    expect(find.text('1 of 6 on this phone'), findsOneWidget);
    await closeApp(tester, shown.db);
  });
}

/// The same two stages on the playlist's own page and on its download button (docs/design S-17).
void playlistPage() {
  group('the playlist page', () {
    setUpAll(loadAppFonts);
    setUp(() => SharedPreferences.setMockInitialValues(
        {'encore.libraryScope': 'mine'}));

    Future<AppDatabase> show(
      WidgetTester tester,
      Map<KeepGroupKey, KeepGroup> groups, {
      List<String> onThePhone = const ['al3-t1'],
    }) async {
      final keep =
          _Keep(KeepState(supported: true, answered: true, groups: groups));
      final app = await pumpApp(tester,
          size: const Size(390, 1400),
          overrides: [keepProvider.overrideWith(() => keep)]);
      await app.db.into(app.db.pins).insert(PinsCompanion.insert(
            serverId: app.serverId,
            targetType: 'playlist',
            targetId: 'pl1',
            createdAtMs: 1,
          ));
      for (final id in onThePhone) {
        await app.db.into(app.db.downloads).insert(DownloadsCompanion.insert(
              serverId: app.serverId,
              trackId: id,
              state: const Value(2),
              localPath: Value('/x/$id.opus'),
              bytes: const Value(1024),
              updatedAtMs: 0,
            ));
      }
      final element = tester.element(find.byType(Scaffold).first);
      GoRouter.of(element).go('/home/playlist/pl1');
      await settle(tester);
      return app.db;
    }

    testWidgets('the header says both stages under its own line',
        (tester) async {
      final db = await show(tester, {
        const KeepGroupKey('playlist', 'pl1'):
            serverGroup('pl1', ready: 3, queued: 3)
      });

      expect(find.text('1 of 6 on this phone · 3 ready on your server'),
          findsOneWidget);
      expect(find.byType(DownloadBar), findsOneWidget);
      await closeApp(tester, db);
    });

    testWidgets(
        'the button says it for a screen reader, and its sheet offers a new try for the songs that did not come',
        (tester) async {
      // The four songs the server holds are on the phone; the other two did not come.
      final db = await show(tester, {
        const KeepGroupKey('playlist', 'pl1'):
            serverGroup('pl1', ready: 4, failed: 2, retryable: 2)
      }, onThePhone: const [
        'al3-t1',
        'al3-t2',
        'al4-t1',
        'al5-t3'
      ]);

      expect(
          find.bySemanticsLabel(RegExp(
              r'^Some downloads failed\. 4 of 6 on this phone · 2 songs did not come')),
          findsOneWidget);

      await tester
          .tap(find.bySemanticsLabel(RegExp(r'^Some downloads failed')));
      await settle(tester);

      expect(find.text('Try again now'), findsOneWidget);
      await closeApp(tester, db);
    });
  });
}
