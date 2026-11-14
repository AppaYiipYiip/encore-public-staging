import 'package:dio/dio.dart';
import 'package:drift/drift.dart' show Value;
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/encore/encore_api.dart';
import 'package:encore/data/encore/encore_instant.dart';
import 'package:encore/features/common/playability.dart'
    show kNotAvailableWords, kNotDownloadedWords, serverAwayProvider;
import 'package:encore/features/common/widgets.dart';
import 'package:encore/features/instant/instant_controller.dart';
import 'package:encore/features/providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import '../support/fake_encore_server.dart';
import '../support/test_app.dart';

/// B-128, the playlist (S-17) and Liked Songs (S-15) rows (drawn in #59): a song of the library that the server holds no file of and already knows it
/// cannot get is grey, with "Not available on your server" in place of the artist.
///
/// * a tap says why and tries nothing; Play and Shuffle leave the song out and the others play on;
/// * **the question is bounded**: by ref id, only for rows with no file that are not downloaded, one question for each stretch of 100 rows that is
///   built, and none for a list whose songs all have files;
/// * offline wins (the row says "Not downloaded"), and a song with a file is never marked.
void main() {
  setUpAll(loadAppFonts);

  const sentence =
      'Nothing matching that song was found. Try again in a few days.';

  late FakeEncoreServer server;
  late _Recording facade;

  Future<AppDatabase> open(
    WidgetTester tester, {
    required String location,
    required Future<void> Function(AppDatabase db, int serverId) seed,
    bool away = false,
  }) async {
    server = FakeEncoreServer();
    facade = _Recording();
    final app = await pumpApp(tester, size: const Size(390, 1400), overrides: [
      playbackFacadeProvider.overrideWithValue(facade),
      enginePlaybackFacadeProvider.overrideWithValue(facade),
      serverAwayProvider.overrideWith((ref) => away),
      instantBackendProvider.overrideWith((ref) async => EncoreInstantBackend(
            api: EncoreApi(
              dio: Dio()..httpClientAdapter = server.adapter,
              baseUrl: () => Uri.parse('http://home.test:4540'),
              auth: () => {'u': 'tester', 't': 'tok', 's': 'salt'},
            ),
            ingest: (_) async {},
          )),
    ]);
    await seed(app.db, app.serverId);
    GoRouter.of(tester.element(find.byType(Scaffold).first)).go(location);
    await settle(tester);
    await tester.pump(const Duration(seconds: 1));
    await settle(tester);
    return app.db;
  }

  /// A song of the library: a ref of the server, with a file there (or not).
  Future<String> song(AppDatabase db, int serverId, String title,
      {bool file = false, bool liked = false}) async {
    final id = server.addRef(title, 'Lofi & Sleep');
    await db.into(db.tracks).insert(TracksCompanion.insert(
          serverId: serverId,
          id: id,
          title: title,
          isRef: const Value(true),
          fileId: Value(file ? 'nd-$title' : null),
          artist: const Value('Lofi & Sleep'),
          artistsJson: const Value('["Lofi & Sleep"]'),
          starredAtMs: Value(liked ? 1000 : null),
        ));
    return id;
  }

  Future<void> playlist(
      AppDatabase db, int serverId, List<String> trackIds) async {
    await db.into(db.playlists).insert(PlaylistsCompanion.insert(
          serverId: serverId,
          id: 'pl-marks',
          name: 'Late night drive',
          songCount: Value(trackIds.length),
          entriesFetchedAtMs: const Value(1),
        ));
    for (var i = 0; i < trackIds.length; i++) {
      await db.into(db.playlistEntries).insert(PlaylistEntriesCompanion.insert(
            serverId: serverId,
            playlistId: 'pl-marks',
            position: i,
            trackId: trackIds[i],
          ));
    }
  }

  Finder snack(String text) => find.descendant(
      of: find.byType(SnackBar), matching: find.textContaining(text));

  for (final page in ['playlist', 'liked']) {
    group('PB-F21 the $page page (B-128)', () {
      final location =
          page == 'playlist' ? '/home/playlist/pl-marks' : '/home/liked';
      late List<String> ids;

      Future<AppDatabase> openPage(WidgetTester tester,
          {bool away = false}) async {
        late final List<String> made;
        final db = await open(tester, location: location, away: away,
            seed: (db, serverId) async {
          // The server already knows it cannot get this one (a stream of it was refused for good, or somebody else's tap).
          server.cannotGet['lofi for focus'] =
              (reason: 'not_found', retryIn: const Duration(days: 7));
          made = [
            await song(db, serverId, 'Nude', file: true, liked: true),
            await song(db, serverId, 'Lofi For Focus', liked: true),
            await song(db, serverId, 'Time', file: true, liked: true),
          ];
          if (page == 'playlist') await playlist(db, serverId, made);
        });
        ids = made;
        return db;
      }

      testWidgets(
          'the song the server cannot get is grey with the words; the others keep their artist line; one question, by ref id, for that row only',
          (tester) async {
        final db = await openPage(tester);

        expect(find.text(kNotAvailableWords), findsOneWidget);
        expect(find.text('Lofi & Sleep'), findsNWidgets(2),
            reason: 'the two songs the server can get');
        expect(
            server.unavailableIdsAsked,
            [
              [ids[1]]
            ],
            reason: 'only the row with no file is asked about');
        expect(server.unavailableAsked, isEmpty);
        await closeApp(tester, db);
      });

      testWidgets(
          'a tap on it says why and plays nothing; a tap on another song plays the list from it without the grey one',
          (tester) async {
        final db = await openPage(tester);

        await tester.tap(find.text('Lofi For Focus'));
        await settle(tester);
        expect(snack(sentence), findsOneWidget);
        expect(facade.played, isEmpty);

        await tester.pump(const Duration(seconds: 6));
        await tester.tap(find.text('Nude'));
        await settle(tester);
        expect(facade.played, hasLength(1));
        expect(facade.played.single, containsAll([ids[0], ids[2]]));
        expect(facade.played.single, isNot(contains(ids[1])),
            reason: 'the grey song is not queued behind the others');
        expect(facade.played.single[facade.starts.single], ids[0],
            reason: 'the list plays on from the song that was tapped');
        await closeApp(tester, db);
      });

      testWidgets('Play and Shuffle leave it out, with no notice',
          (tester) async {
        final db = await openPage(tester);

        await tester.tap(find.byType(PlayButton));
        await settle(tester);
        await tester.tap(find.byTooltip('Shuffle'));
        await settle(tester);

        expect(facade.played, hasLength(2));
        for (final queue in facade.played) {
          expect(queue, containsAll([ids[0], ids[2]]));
          expect(queue, isNot(contains(ids[1])));
        }
        expect(facade.shuffles, [false, true]);
        expect(find.byType(SnackBar), findsNothing,
            reason: 'a whole-list play says nothing about a song it passes');
        await closeApp(tester, db);
      });

      testWidgets(
          'offline wins: nothing is asked, and the row says "Not downloaded", never the mark',
          (tester) async {
        final db = await openPage(tester, away: true);

        expect(find.text(kNotAvailableWords), findsNothing);
        expect(find.text(kNotDownloadedWords), findsWidgets);
        expect(server.unavailableIdsAsked, isEmpty);
        await closeApp(tester, db);
      });
    });
  }

  group('PB-F21 the question is bounded (B-128)', () {
    testWidgets(
        'a playlist of 250 songs with no file asks only for the stretches that are built, 100 rows at a time',
        (tester) async {
      late List<String> ids;
      final db = await open(tester, location: '/home/playlist/pl-marks',
          seed: (db, serverId) async {
        ids = [
          for (var i = 0; i < 250; i++)
            await song(db, serverId, 'Song ${i.toString().padLeft(3, '0')}'),
        ];
        await playlist(db, serverId, ids);
      });

      expect(find.text('Song 000'), findsOneWidget,
          reason: 'precondition: the top of the list is built');
      expect(find.text('Song 249'), findsNothing,
          reason: 'precondition: the end is not');
      expect(server.unavailableIdsAsked, hasLength(1),
          reason: 'one stretch is built, one question');
      expect(server.unavailableIdsAsked.single, ids.take(100).toList(),
          reason: 'the ids of the first 100 rows, in order');

      await tester.drag(
          find.byType(CustomScrollView).first, const Offset(0, -20000));
      await settle(tester);
      await tester.pump(const Duration(seconds: 1));
      await settle(tester);

      expect(find.text('Song 249'), findsOneWidget);
      expect(server.unavailableIdsAsked, hasLength(3),
          reason:
              'the stretches the person scrolled to, never the whole list at once');
      expect([for (final q in server.unavailableIdsAsked) q.length],
          everyElement(lessThanOrEqualTo(100)));
      await closeApp(tester, db);
    });

    testWidgets('a playlist whose songs all have files asks nothing',
        (tester) async {
      final db = await open(tester, location: '/home/playlist/pl-marks',
          seed: (db, serverId) async {
        await playlist(db, serverId, [
          for (var i = 0; i < 30; i++)
            await song(db, serverId, 'Kept $i', file: true),
        ]);
      });

      expect(find.text('Kept 0'), findsOneWidget);
      expect(server.unavailableIdsAsked, isEmpty);
      expect(server.unavailableAsked, isEmpty);
      await closeApp(tester, db);
    });
  });
}

/// A player that writes down what it was given (ids, where to start, whether shuffled), in order.
class _Recording extends FakePlaybackFacade {
  final List<List<String>> played = [];
  final List<int> starts = [];
  final List<bool> shuffles = [];

  @override
  Future<void> playTracks(List<TrackRow> tracks,
      {int startIndex = 0,
      String? sourceName,
      String? sourceId,
      bool shuffle = false,
      bool skipUnavailable = false}) {
    played.add([for (final t in tracks) t.id]);
    starts.add(startIndex);
    shuffles.add(shuffle);
    return super.playTracks(tracks,
        startIndex: startIndex,
        sourceName: sourceName,
        sourceId: sourceId,
        shuffle: shuffle,
        skipUnavailable: skipUnavailable);
  }
}
