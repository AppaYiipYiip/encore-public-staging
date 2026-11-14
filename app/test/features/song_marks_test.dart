import 'dart:async';

import 'package:dio/dio.dart';
import 'package:drift/drift.dart' show Value;
import 'package:encore/app/connection.dart'
    show ServerReachability, serverReachabilityProvider;
import 'package:encore/app/navigation.dart';
import 'package:encore/core/result.dart';
import 'package:encore/data/catalogue/catalogue_models.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/encore/encore_api.dart';
import 'package:encore/data/encore/encore_instant.dart';
import 'package:encore/data/encore/encore_models.dart';
import 'package:encore/data/fetch/fetch_client.dart';
import 'package:encore/design/theme.dart';
import 'package:encore/design/tokens.dart';
import 'package:encore/features/catalogue/catalogue_widgets.dart';
import 'package:encore/features/common/playability.dart'
    show kNotAvailableWords;
import 'package:encore/features/instant/instant_controller.dart';
import 'package:encore/features/instant/instant_play.dart';
import 'package:encore/features/instant/song_marks.dart';
import 'package:encore/features/instant/song_refusals.dart';
import 'package:encore/features/player/playback_facade.dart';
import 'package:encore/features/providers.dart';
import 'package:encore/features/requests/request_providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/factories.dart';
import '../support/fake_catalogue.dart';
import '../support/fake_encore_server.dart';
import '../support/reachability.dart';
import '../support/test_app.dart';

/// N-13: songs the server already knows it cannot get are marked in the lists of catalogue songs, before anybody taps them (drawn 14 Nov 2026, docs/design
/// S-12, S-18, S-19, classes C and X).
///
/// The rules these tests hold:
///
/// * **One question for the whole list** (`POST refs/unavailable`), after the rows are drawn, and the answer is kept until the server stops believing it.
/// * **Safe across server versions:** a server with no such question (404 or 405), a plain music server, a phone whose server is away and a server that
///   could not be reached all mean "no marks" and never an error; only the last is asked again.
/// * **A marked row never tries:** a tap says why in the server's own sentence, nothing spins and the server is asked nothing; a whole-list Play or
///   Shuffle leaves marked songs out of the queue without a notice.
void main() {
  group('the marks service', () {
    late FakeEncoreServer server;
    late EncoreInstantBackend backend;
    var now = DateTime.now();

    CatalogueTrack track(int n) => CatalogueTrack(
          id: 'dz-$n',
          title: 'Song $n',
          artistName: 'Lofi & Sleep',
          duration: const Duration(minutes: 3),
        );

    ProviderContainer container({
      bool away = false,
      InstantPlayBackend? backendOverride,
    }) {
      final c = ProviderContainer(overrides: [
        serverReachabilityProvider.overrideWith(() => FixedReachability(
            away ? ServerReachability.serverAway : ServerReachability.ok)),
        instantBackendProvider
            .overrideWith((ref) async => backendOverride ?? backend),
        songMarksClockProvider.overrideWithValue(() => now),
      ]);
      addTearDown(c.dispose);
      return c;
    }

    Future<void> check(ProviderContainer c, List<CatalogueTrack> list) =>
        c.read(songMarksCheckProvider(TrackList(list)).future);

    setUp(() {
      server = FakeEncoreServer();
      now = DateTime.now();
      backend = EncoreInstantBackend(
        api: EncoreApi(
          dio: Dio()..httpClientAdapter = server.adapter,
          baseUrl: () => Uri.parse('http://home.test:4540'),
          auth: () => {'u': 'tester', 't': 'tok', 's': 'salt'},
        ),
        ingest: (_) async {},
      );
      server.cannotGet['song 2'] =
          (reason: 'not_found', retryIn: const Duration(days: 7));
    });

    test('marks the song the server cannot get, with one question for the list',
        () async {
      final c = container();

      await check(c, [track(1), track(2), track(3)]);

      expect(c.read(songMarkProvider('dz-2'))?.reason, 'not_found');
      expect(c.read(songMarkProvider('dz-1')), isNull);
      expect(c.read(songMarkProvider('dz-3')), isNull);
      expect(server.unavailableAsked, [
        ['Song 1', 'Song 2', 'Song 3']
      ]);
    });

    test(
        'the same songs in another list are not asked about again until the answer is stale',
        () async {
      final c = container();
      await check(c, [track(1), track(2)]);

      await check(c, [track(2), track(1)]);
      expect(server.unavailableAsked, hasLength(1));

      now = now.add(kSongMarksFreshFor + const Duration(seconds: 1));
      server.cannotGet['song 1'] =
          (reason: 'removed', retryIn: const Duration(days: 7));
      await check(c, [track(1), track(2)]);

      expect(server.unavailableAsked, hasLength(2));
      expect(c.read(songMarkProvider('dz-1'))?.reason, 'removed',
          reason: 'a song the server learned about meanwhile gets its mark');
    });

    test('a mark goes when the server stops believing it', () async {
      server.cannotGet['song 2'] =
          (reason: 'not_found', retryIn: const Duration(hours: 1));
      final c = container();
      await check(c, [track(2)]);
      expect(c.read(songMarkProvider('dz-2')), isNotNull);

      now = now.add(const Duration(hours: 2));
      await check(c, [track(3)]);

      expect(c.read(songMarksProvider), isEmpty,
          reason: 'from then on a tap tries for real; the list shown next '
              'drops it even if the question is about other songs');
    });

    test('a mark is dropped when a later answer says the problem is over',
        () async {
      final c = container();
      await check(c, [track(2)]);
      server.cannotGet.clear();
      now = now.add(kSongMarksFreshFor + const Duration(seconds: 1));

      await check(c, [track(2)]);

      expect(c.read(songMarkProvider('dz-2')), isNull);
    });

    for (final status in [405, 404]) {
      test(
          'a server with no such question ($status) is "no verdicts here": nothing is marked, nothing is an error, and it is not asked again',
          () async {
        server.unavailableStatus = status;
        final c = container();

        await check(c, [track(1), track(2)]);
        await check(c, [track(3), track(4)]);

        expect(c.read(songMarksProvider), isEmpty);
        expect(server.unavailableAsked, hasLength(1),
            reason: 'asked once, then the session knows');
      });
    }

    test('nothing is asked while the server is away (offline always wins)',
        () async {
      final c = container(away: true);

      await check(c, [track(1), track(2)]);

      expect(server.unavailableAsked, isEmpty);
      expect(c.read(songMarksProvider), isEmpty);
    });

    test('a plain music server (no Encore on it) is never asked', () async {
      final c = container(backendOverride: _PlainMusicServer());

      await check(c, [track(1), track(2)]);

      expect(server.unavailableAsked, isEmpty);
    });

    test(
        'a question that could not be asked (the network) is asked again the next time; it is not "no verdicts"',
        () async {
      final c = container();
      server.online = false;
      await check(c, [track(1), track(2)]);
      expect(c.read(songMarksProvider), isEmpty);

      server.online = true;
      await check(c, [track(1), track(2)]);

      expect(c.read(songMarkProvider('dz-2')), isNotNull);
    });

    test('a long list goes in questions of at most 100 songs', () async {
      final c = container();

      await check(c, [for (var i = 1; i <= 150; i++) track(i)]);

      expect([for (final q in server.unavailableAsked) q.length], [100, 50]);
      expect(c.read(songMarkProvider('dz-2')), isNotNull);
    });
  });

  group('the marks service, library rows (B-128)', () {
    late FakeEncoreServer server;
    late EncoreInstantBackend backend;
    var now = DateTime.now();
    var away = false;
    late String goneId;
    late String fineId;

    ProviderContainer container({EncoreInstantBackend? backendOverride}) {
      final c = ProviderContainer(overrides: [
        serverReachabilityProvider.overrideWith(() => ReachabilityFrom(() =>
            away ? ServerReachability.serverAway : ServerReachability.ok)),
        instantBackendProvider
            .overrideWith((ref) async => backendOverride ?? backend),
        songMarksClockProvider.overrideWithValue(() => now),
      ]);
      addTearDown(c.dispose);
      return c;
    }

    Future<void> checkRefs(ProviderContainer c, List<String> ids) =>
        c.read(songMarksCheckProvider(TrackList(const [], refIds: ids)).future);

    EncoreApi apiOf(FakeEncoreServer server) => EncoreApi(
          dio: Dio()..httpClientAdapter = server.adapter,
          baseUrl: () => Uri.parse('http://home.test:4540'),
          auth: () => {'u': 'tester', 't': 'tok', 's': 'salt'},
        );

    setUp(() {
      server = FakeEncoreServer();
      now = DateTime.now();
      away = false;
      backend = EncoreInstantBackend(api: apiOf(server), ingest: (_) async {});
      goneId = server.addRef('Lofi For Focus', 'Lofi & Sleep');
      fineId = server.addRef('Rainy Window', 'Lofi & Sleep');
      server.cannotGet['lofi for focus'] =
          (reason: 'not_found', retryIn: const Duration(days: 7));
    });

    test(
        'a library row is asked about by its ref id, with one question for the list, and marked under that id',
        () async {
      final c = container();

      await checkRefs(c, [fineId, goneId]);

      expect(c.read(songMarkProvider(goneId))?.reason, 'not_found');
      expect(c.read(songMarkProvider(fineId)), isNull);
      expect(server.unavailableIdsAsked, [
        [fineId, goneId]
      ]);
      expect(server.unavailableAsked, isEmpty,
          reason: 'no description of the song is sent');
    });

    test(
        'a server that does not list unavailable-ids is never sent the question and the session does not ask again',
        () async {
      server.hasUnavailableIds = false;
      final c = container();

      await checkRefs(c, [goneId]);
      await checkRefs(c, [fineId]);

      expect(server.idsSentToAServerWithoutThem, 0);
      expect(c.read(songMarksProvider), isEmpty);
    });

    test(
        'the older server that knows only descriptions still marks the catalogue songs of a page',
        () async {
      server.hasUnavailableIds = false;
      final c = container();

      await c.read(songMarksCheckProvider(TrackList(const [
        CatalogueTrack(
            id: 'dz-1', title: 'Lofi For Focus', artistName: 'Lofi & Sleep')
      ])).future);

      expect(c.read(songMarkProvider('dz-1'))?.reason, 'not_found');
    });

    test('nothing is asked while the server is away, and no mark is shown',
        () async {
      final c = container();
      await checkRefs(c, [goneId]);
      expect(c.read(songMarkProvider(goneId)), isNotNull);

      away = true;
      c.invalidate(serverReachabilityProvider);

      expect(c.read(songMarkProvider(goneId)), isNull,
          reason: 'offline always wins (S-12): the row says "Not downloaded"');
      final asked = server.unavailableIdsAsked.length;
      await checkRefs(c, [fineId]);
      expect(server.unavailableIdsAsked, hasLength(asked));
    });

    test(
        'a refusal voids the trust in "no problem": the lists on screen ask again at once and the song turns grey',
        () async {
      server.cannotGet.clear();
      final c = container();
      final list = TrackList(const [], refIds: [goneId]);
      final sub = c.listen(songMarksCheckProvider(list), (_, __) {});
      addTearDown(sub.close);
      await c.read(songMarksCheckProvider(list).future);
      expect(c.read(songMarkProvider(goneId)), isNull,
          reason: 'asked, no problem: trusted for ten minutes');
      // The server learns it meanwhile (this phone just tapped it and was refused).
      server.cannotGet['lofi for focus'] =
          (reason: 'not_found', retryIn: const Duration(days: 7));

      c.read(songRefusalsProvider.notifier).refused();
      await c.read(songMarksCheckProvider(list).future);

      expect(c.read(songMarkProvider(goneId))?.reason, 'not_found');
      expect(server.unavailableIdsAsked, hasLength(2));
    });

    test(
        'without a refusal a "no problem" is still trusted for ten minutes (the rule is unchanged: not a question on every redraw)',
        () async {
      server.cannotGet.clear();
      final c = container();
      await checkRefs(c, [goneId]);
      server.cannotGet['lofi for focus'] =
          (reason: 'not_found', retryIn: const Duration(days: 7));

      await checkRefs(c, [goneId]);

      expect(server.unavailableIdsAsked, hasLength(1));
      expect(c.read(songMarkProvider(goneId)), isNull);
    });

    test(
        'an answer to a question asked before the refusal is dropped: it must not leave a stale "no problem" trusted',
        () async {
      server.cannotGet.clear();
      final slow = _SlowBackend(apiOf(server));
      final c = container(backendOverride: slow);
      final list = TrackList(const [], refIds: [goneId]);
      final sub = c.listen(songMarksCheckProvider(list), (_, __) {});
      addTearDown(sub.close);
      await slow.firstAsked
          .future; // the question is on its way, its answer ("no problem") not yet back
      server.cannotGet['lofi for focus'] =
          (reason: 'not_found', retryIn: const Duration(days: 7));

      c.read(songRefusalsProvider.notifier).refused();
      slow.release();
      await Future<void>.delayed(const Duration(milliseconds: 50));
      await c.read(songMarksCheckProvider(list).future);

      expect(c.read(songMarkProvider(goneId))?.reason, 'not_found');
    });
  });

  group('the mark of a library row', () {
    final live = EncoreUnavailable(
      reason: 'not_found',
      message: 'Nothing matching that song was found.',
      retryAfter: DateTime.now().add(const Duration(days: 7)),
    );

    ProviderContainer container({
      Set<String> downloaded = const {},
      bool away = false,
    }) {
      final c = ProviderContainer(overrides: [
        serverReachabilityProvider.overrideWith(() => FixedReachability(
            away ? ServerReachability.serverAway : ServerReachability.ok)),
        downloadedIdsProvider.overrideWith((ref) => Stream.value(downloaded)),
        songMarksProvider.overrideWith(() => _FixedMarks({'sr_1': live})),
      ]);
      addTearDown(c.dispose);
      return c;
    }

    Future<EncoreUnavailable?> markOf(ProviderContainer c, TrackRow row) async {
      final downloaded = c.listen(downloadedIdsProvider, (_, __) {});
      addTearDown(downloaded.close);
      await c.read(downloadedIdsProvider.future);
      return c.read(libraryMarkProvider(row.markKey));
    }

    test('a ref with no file is marked', () async {
      final c = container();

      expect(await markOf(c, refRow('sr_1')), isNotNull);
    });

    test(
        'a song with a file is never marked, whatever the map says (a file may arrive inside the window)',
        () async {
      final c = container();

      expect(await markOf(c, refRow('sr_1', fileId: 'nd-1')), isNull);
    });

    test('a downloaded song is never marked: it is on the phone', () async {
      final c = container(downloaded: {'sr_1'});

      expect(await markOf(c, refRow('sr_1')), isNull);
    });

    test('a row of a plain music server is never marked', () async {
      final c = container();

      expect(await markOf(c, refRow('sr_1', isRef: false)), isNull);
    });

    test('offline wins: nothing is shown while the server is away', () async {
      final c = container(away: true);

      expect(await markOf(c, refRow('sr_1')), isNull);
    });
  });

  group('a row', () {
    const lofi = CatalogueTrack(
        id: 'dz-1', title: 'Lofi For Focus', artistName: 'Lofi & Sleep');
    final mark = EncoreUnavailable(
      reason: 'not_found',
      message: 'Nothing matching that song was found.',
      retryAfter: DateTime(2030),
    );

    Future<void> pumpRow(WidgetTester tester, {EncoreUnavailable? mark}) =>
        tester.pumpWidget(MaterialApp(
          theme: buildEncoreTheme(EncoreColors.dark(),
              brightness: Brightness.dark),
          home: Scaffold(
            body: CatalogueTrackTile(
              track: lofi,
              isCurrent: false,
              isPlaying: false,
              mark: mark,
            ),
          ),
        ));

    testWidgets(
        'a marked song says "Not available on your server" in place of the artist, and its semantics say so',
        (tester) async {
      await pumpRow(tester, mark: mark);

      expect(find.text(kNotAvailableWords), findsOneWidget);
      expect(find.text('Lofi & Sleep'), findsNothing);
      expect(find.bySemanticsLabel(RegExp(kNotAvailableWords)), findsOneWidget);
    });

    testWidgets('an ordinary song keeps its artist line (the control)',
        (tester) async {
      await pumpRow(tester);

      expect(find.text('Lofi & Sleep'), findsOneWidget);
      expect(find.text(kNotAvailableWords), findsNothing);
    });
  });

  group('on the artist page', () {
    late _Backend backend;
    late FakeCatalogue catalogue;
    late _Facade facade;

    const mastodon =
        CatalogueArtist(id: 'c1', name: 'Mastodon', albumCount: 3, fans: 9000);

    List<CatalogueTrack> popular() => [
          for (var i = 1; i <= 4; i++)
            CatalogueTrack(
              id: 'dz-$i',
              title: 'Mastodon Song $i',
              artistName: 'Mastodon',
              artistId: 'c1',
              duration: const Duration(minutes: 3),
            ),
        ];

    EncoreUnavailable gone() => EncoreUnavailable(
          reason: 'not_found',
          message: 'Nothing matching that song was found.',
          retryAfter: DateTime.now().add(const Duration(days: 7)),
        );

    Future<AppDatabase> openPage(WidgetTester tester,
        {Map<String, EncoreUnavailable> marks = const {},
        FakeEncoreServer? server}) async {
      backend = _Backend();
      facade = _Facade(PlaybackSnapshot.idle);
      catalogue = FakeCatalogue()
        ..artistsById['c1'] = mastodon
        ..topTracksByArtist['c1'] = popular();
      final service = InstantPlayService(
        backend: backend,
        matcher: null,
        loadSong: (songId) async =>
            trackRow(songId, title: songId.substring(5), artist: 'Mastodon'),
        pollEvery: Duration.zero,
        delay: (_) async {},
      );
      final app = await pumpApp(
        tester,
        size: const Size(390, 1800),
        overrides: [
          playbackFacadeProvider.overrideWithValue(facade),
          enginePlaybackFacadeProvider.overrideWithValue(facade),
          catalogueClientProvider.overrideWithValue(catalogue),
          instantAvailableProvider.overrideWithValue(true),
          instantPlayServiceProvider.overrideWith((ref) async => service),
          if (server == null)
            songMarksProvider.overrideWith(() => _FixedMarks(marks))
          else
            // The real service, asking a server that has the memory.
            instantBackendProvider
                .overrideWith((ref) async => EncoreInstantBackend(
                      api: EncoreApi(
                        dio: Dio()..httpClientAdapter = server.adapter,
                        baseUrl: () => Uri.parse('http://home.test:4540'),
                        auth: () => {'u': 'tester', 't': 'tok', 's': 'salt'},
                      ),
                      ingest: (_) async {},
                    )),
        ],
      );
      final container = ProviderScope.containerOf(
          tester.element(find.byType(Scaffold).first));
      await tester
          .runAsync(() => container.read(instantPlayServiceProvider.future));
      Nav.catalogueArtist(tester.element(find.byType(Scaffold).first), 'c1');
      await settle(tester);
      await tester.pump(const Duration(seconds: 1));
      await settle(tester);
      return app.db;
    }

    Future<void> press(WidgetTester tester, Finder button) async {
      await tester.runAsync(() async {
        await tester.tap(button);
        await Future<void>.delayed(const Duration(milliseconds: 80));
      });
      await settle(tester);
    }

    testWidgets(
        'the marked song is grey with the words; the others keep their artist line',
        (tester) async {
      final db = await openPage(tester, marks: {'dz-2': gone()});

      expect(find.text(kNotAvailableWords), findsOneWidget);
      expect(find.text('Mastodon'), findsWidgets);
      expect(
          find.descendant(
              of: find.ancestor(
                  of: find.text('Mastodon Song 2'),
                  matching: find.byType(CatalogueTrackTile)),
              matching: find.text(kNotAvailableWords)),
          findsOneWidget,
          reason: 'the words are under the marked song, not another');
      await closeApp(tester, db);
    });

    testWidgets(
        'the marks come from the server: one question for the whole list, asked after the page drew, and the row greys',
        (tester) async {
      final server = FakeEncoreServer()
        ..cannotGet['mastodon song 2'] =
            (reason: 'removed', retryIn: const Duration(days: 7));
      final db = await openPage(tester, server: server);
      await tester.pump(const Duration(milliseconds: 50));
      await settle(tester);

      expect(
          server.unavailableAsked,
          [
            [for (final t in popular()) t.title],
          ],
          reason: 'one request, the songs of the page in order');
      expect(find.text(kNotAvailableWords), findsOneWidget);
      await closeApp(tester, db);
    });

    testWidgets(
        'a tap on the marked song says why at once: nothing is tried, nothing spins',
        (tester) async {
      final db = await openPage(tester, marks: {'dz-2': gone()});

      await press(tester, find.text('Mastodon Song 2'));

      expect(
          find.text(
              'Nothing matching that song was found. Try again in a few days.'),
          findsOneWidget);
      expect(backend.asked, isEmpty, reason: 'the server was not asked');
      expect(find.byType(CircularProgressIndicator), findsNothing);
      await closeApp(tester, db);
    });

    testWidgets('a tap on a song the server can get plays it (the control)',
        (tester) async {
      final db = await openPage(tester, marks: {'dz-2': gone()});

      await press(tester, find.text('Mastodon Song 3'));

      expect(backend.asked, contains('Mastodon Song 3'));
      await closeApp(tester, db);
    });

    testWidgets(
        'Play leaves the marked song out of the queue, with no try and no notice',
        (tester) async {
      final db = await openPage(tester, marks: {'dz-2': gone()});

      await press(
          tester, find.byIcon(Icons.play_arrow_rounded).last); // the green Play

      expect(backend.asked, [
        'Mastodon Song 1',
        'Mastodon Song 3',
        'Mastodon Song 4',
      ]);
      expect(find.textContaining('Try again in a few days'), findsNothing);
      await closeApp(tester, db);
    });

    testWidgets('Shuffle leaves it out too, and plays each of the others once',
        (tester) async {
      final db = await openPage(tester, marks: {'dz-2': gone()});

      await press(tester, find.byTooltip('Shuffle'));

      expect(backend.asked.toSet(), {
        'Mastodon Song 1',
        'Mastodon Song 3',
        'Mastodon Song 4',
      });
      expect(backend.asked, hasLength(3));
      await closeApp(tester, db);
    });

    testWidgets(
        'a page whose songs are all marked says the first one\'s sentence and plays nothing',
        (tester) async {
      final db = await openPage(tester, marks: {
        for (var i = 1; i <= 4; i++) 'dz-$i': gone(),
      });

      await press(tester, find.byIcon(Icons.play_arrow_rounded).last);

      expect(backend.asked, isEmpty);
      expect(find.textContaining('Nothing matching that song was found.'),
          findsOneWidget);
      await closeApp(tester, db);
    });
  });

  group('in Search', () {
    const lofi = CatalogueTrack(
      id: 'dz-1',
      title: 'Lofi For Focus',
      artistName: 'Lofi & Sleep',
      duration: Duration(minutes: 3),
    );
    const rainy = CatalogueTrack(
      id: 'dz-2',
      title: 'Rainy Window',
      artistName: 'Lofi & Sleep',
      duration: Duration(minutes: 2, seconds: 41),
    );

    testWidgets(
        'the Top result and the row of a marked song are grey with the words, and a tap on either says why without trying',
        (tester) async {
      final backend = _Backend();
      final service = InstantPlayService(
        backend: backend,
        matcher: null,
        loadSong: (songId) async =>
            trackRow(songId, title: songId.substring(5), artist: 'Lofi'),
        pollEvery: Duration.zero,
        delay: (_) async {},
      );
      final app = await pumpApp(tester, overrides: [
        catalogueClientProvider.overrideWithValue(
            FakeCatalogue(const CatalogueResults(tracks: [lofi, rainy]))),
        instantAvailableProvider.overrideWithValue(true),
        instantPlayServiceProvider.overrideWith((ref) async => service),
        songMarksProvider.overrideWith(() => _FixedMarks({
              for (final id in ['dz-1', 'dz-2'])
                id: EncoreUnavailable(
                  reason: 'not_found',
                  message: 'Nothing matching that song was found.',
                  retryAfter: DateTime.now().add(const Duration(days: 7)),
                ),
            })),
      ]);
      await tester.tap(find.text('Search').last);
      await settle(tester);
      await tester.enterText(find.byType(TextField), 'lofi for focus');
      await tester.pump(const Duration(milliseconds: 90));
      await tester.pump(const Duration(milliseconds: 1000));
      await settle(tester);

      expect(find.byKey(const Key('top-result')), findsOneWidget);
      expect(
          find.descendant(
              of: find.byKey(const Key('top-result')),
              matching: find.text(kNotAvailableWords)),
          findsOneWidget,
          reason: 'the Top result card says it');
      expect(find.text(kNotAvailableWords), findsNWidgets(2),
          reason: 'the Top result card and the row of the other song');

      await tester.tap(find.byKey(const Key('top-result')));
      await settle(tester);

      expect(
          find.text(
              'Nothing matching that song was found. Try again in a few days.'),
          findsOneWidget);
      expect(backend.asked, isEmpty, reason: 'the server was asked nothing');
      await closeApp(tester, app.db);
    });
  });
}

/// Marks that are simply there, as the service would leave them.
class _FixedMarks extends SongMarks {
  _FixedMarks(this._marks);

  final Map<String, EncoreUnavailable> _marks;

  @override
  Map<String, EncoreUnavailable> build() => _marks;

  @override
  Future<void> check(TrackList list) async {}
}

/// What `playTracks` was asked, written down.
class _Facade extends FakePlaybackFacade {
  _Facade([super.initial]);
}

/// A service that gets every song at once and remembers the order it was asked in.
class _Backend implements InstantPlayBackend {
  final List<String> asked = [];

  @override
  Future<void> prepare(FetchRequest request) async {}

  @override
  Future<Result<FetchJob>> start(FetchRequest request) async {
    asked.add(request.title);
    return Ok(FetchJob(
      id: 'j${asked.length}',
      state: FetchState.ready,
      songId: 'song-${request.title}',
    ));
  }

  @override
  Future<Result<FetchJob>> status(String id) async =>
      Ok(FetchJob(id: id, state: FetchState.ready));

  @override
  Uri? streamUrlFor(FetchRequest request) => null;

  @override
  Uri? streamUri(FetchJob job) => null;
}

/// A music server with no Encore on it: it can fetch, but it has no memory of refusals to ask.
class _PlainMusicServer extends _Backend {}

/// A row of the phone's library that is a ref of an Encore server (docs/18): [fileId] is the music server's id of the file the server keeps, if any.
TrackRow refRow(String id, {String? fileId, bool isRef = true}) =>
    trackRow(id, title: 'Lofi For Focus', artist: 'Lofi & Sleep')
        .copyWith(isRef: isRef, fileId: Value(fileId));

/// An Encore backend whose answer to the first question about ref ids waits until [release] (a slow line): the answer of a question asked before
/// something happened, arriving after it.
class _SlowBackend extends EncoreInstantBackend {
  _SlowBackend(EncoreApi api) : super(api: api, ingest: (_) async {});

  final Completer<void> firstAsked = Completer<void>();
  final Completer<void> _gate = Completer<void>();
  var _asked = 0;

  void release() => _gate.complete();

  @override
  Future<({bool supported, List<EncoreUnavailable?> verdicts})?>
      unavailableAmongRefs(List<String> refIds) async {
    final answer = await super.unavailableAmongRefs(refIds);
    if (_asked++ == 0) {
      firstAsked.complete();
      await _gate.future;
    }
    return answer;
  }
}
