import 'package:encore/app/navigation.dart';
import 'package:encore/core/result.dart';
import 'package:encore/data/catalogue/catalogue_models.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/fetch/fetch_client.dart';
import 'package:encore/features/common/widgets.dart';
import 'package:encore/features/instant/instant_controller.dart';
import 'package:encore/features/instant/instant_play.dart';
import 'package:encore/features/player/playback_facade.dart';
import 'package:encore/features/providers.dart';
import 'package:encore/features/requests/request_providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import '../support/factories.dart';
import '../support/fake_catalogue.dart';
import '../support/test_app.dart';

/// N-24 (owner, 13 Nov 2026): "search an artist and press one button to play all their songs", instead of choosing songs from albums.
/// The artist page (S-19, drawn with Shuffle and the green Play next to each other) has two forms:
///
/// * the library's page (the server has the artist): Play and Shuffle are every song of the artist the server holds, the same buttons,
///   the same playback call and the same "offline plays only what is downloaded" as an album or a playlist;
/// * the catalogue's page (the server does not have the artist): they are the songs the page lists as Popular; each is fetched as it is
///   needed, as a tap on a row does.

/// What `playTracks` was asked, beyond what [FakePlaybackFacade] writes in `calls` (changing that line would break many tests).
class _Facade extends FakePlaybackFacade {
  _Facade([super.initial]);

  final List<
          ({int count, String? sourceId, bool shuffle, bool skipUnavailable})>
      plays = [];

  @override
  Future<void> playTracks(
    List<TrackRow> tracks, {
    int startIndex = 0,
    String? sourceName,
    String? sourceId,
    bool shuffle = false,
    bool skipUnavailable = false,
  }) {
    plays.add((
      count: tracks.length,
      sourceId: sourceId,
      shuffle: shuffle,
      skipUnavailable: skipUnavailable,
    ));
    return super.playTracks(tracks,
        startIndex: startIndex,
        sourceName: sourceName,
        sourceId: sourceId,
        shuffle: shuffle,
        skipUnavailable: skipUnavailable);
  }
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
        songId: 'song-${request.title}'));
  }

  @override
  Future<Result<FetchJob>> status(String id) async =>
      Ok(FetchJob(id: id, state: FetchState.ready));

  @override
  Uri? streamUrlFor(FetchRequest request) => null;

  @override
  Uri? streamUri(FetchJob job) => null;
}

/// The seeded library has Opeth (`ar3`) with two albums of five songs. The catalogue knows the same Opeth, with seven popular songs.
FakeCatalogue _opethInTheCatalogue() {
  final c = FakeCatalogue(const CatalogueResults(
    artists: [
      CatalogueArtist(id: 'o1', name: 'Opeth', fans: 1200000, albumCount: 14),
    ],
  ));
  c.albumsByArtist['o1'] = const [
    CatalogueAlbum(
        id: 'a1',
        title: 'Blackwater Park',
        artistName: 'Opeth',
        year: 2001,
        recordType: 'album'),
    CatalogueAlbum(
        id: 'a2',
        title: 'Ghost Reveries',
        artistName: 'Opeth',
        year: 2005,
        recordType: 'album'),
  ];
  c.topTracksByArtist['o1'] = [
    for (var i = 1; i <= 7; i++)
      CatalogueTrack(
          id: 'p$i',
          title: 'Popular Song $i',
          artistName: 'Opeth',
          albumTitle: 'Blackwater Park'),
  ];
  return c;
}

const _mastodon = CatalogueArtist(id: 'c1', name: 'Mastodon', fans: 5000);

List<CatalogueTrack> _popular(int n) => [
      for (var i = 1; i <= n; i++)
        CatalogueTrack(
            id: 'm$i',
            title: 'Mastodon Song $i',
            artistName: 'Mastodon',
            artistId: 'c1',
            albumTitle: 'Leviathan'),
    ];

void main() {
  setUpAll(loadAppFonts);

  Future<({AppDatabase db, _Facade facade})> openLibraryArtist(
    WidgetTester tester, {
    String id = 'ar3',
    PlaybackSnapshot? playing,
    bool instant = true,
    FakeCatalogue? catalogue,
    Future<void> Function(AppDatabase db, int serverId)? seed,
  }) async {
    final facade = _Facade(playing ?? PlaybackSnapshot.idle);
    final app = await pumpApp(
      tester,
      size: const Size(390, 1800),
      overrides: [
        playbackFacadeProvider.overrideWithValue(facade),
        enginePlaybackFacadeProvider.overrideWithValue(facade),
        catalogueClientProvider
            .overrideWithValue(catalogue ?? _opethInTheCatalogue()),
        instantAvailableProvider.overrideWithValue(instant),
      ],
    );
    await seed?.call(app.db, app.serverId);
    GoRouter.of(tester.element(find.byType(Scaffold).first))
        .go('/library/artist/$id');
    await settle(tester);
    await tester.pump(const Duration(seconds: 1));
    await settle(tester);
    return (db: app.db, facade: facade);
  }

  Finder playButton() => find.byType(PlayButton);

  group('the library artist page', () {
    testWidgets(
        'Shuffle plays every song of the artist the server holds, shuffled, '
        'and passes over what is not downloaded when offline', (tester) async {
      final app = await openLibraryArtist(tester);

      await tester.tap(find.byTooltip('Shuffle'));
      await settle(tester);

      expect(
          app.facade.plays,
          [
            (
              count: 10,
              sourceId: 'artist:ar3',
              shuffle: true,
              skipUnavailable: true
            ),
          ],
          reason: 'two albums of five songs, as one list');
      expect(app.facade.calls,
          ['playTracks(10, start=0, source=Opeth, shuffle=true)']);
      await closeApp(tester, app.db);
    });

    testWidgets(
        'Play plays the same list from the start, also when the catalogue '
        'lists popular songs (those are not "all")', (tester) async {
      final app = await openLibraryArtist(tester);
      expect(find.text('Popular Song 1'), findsOneWidget,
          reason: 'precondition: the catalogue answered with its Popular list');

      await tester.tap(playButton());
      await settle(tester);

      expect(app.facade.plays, [
        (
          count: 10,
          sourceId: 'artist:ar3',
          shuffle: false,
          skipUnavailable: true
        ),
      ]);
      expect(app.facade.calls,
          ['playTracks(10, start=0, source=Opeth, shuffle=false)']);
      await closeApp(tester, app.db);
    });

    testWidgets('with no catalogue at all Play and Shuffle are the same',
        (tester) async {
      final app = await openLibraryArtist(tester,
          instant: false, catalogue: FakeCatalogue());

      await tester.tap(find.byTooltip('Shuffle'));
      await settle(tester);
      await tester.tap(playButton());
      await settle(tester);

      expect(app.facade.plays.map((p) => (p.count, p.shuffle)),
          [(10, true), (10, false)]);
      await closeApp(tester, app.db);
    });

    testWidgets(
        'while this artist plays, Play shows pause and pauses, and Shuffle '
        'shows that the player\'s shuffle is on', (tester) async {
      final app = await openLibraryArtist(
        tester,
        playing: const PlaybackSnapshot(
          isPlaying: true,
          shuffle: true,
          sourceName: 'Opeth',
          sourceId: 'artist:ar3',
        ),
      );

      expect(
          find.descendant(
              of: playButton(), matching: find.byIcon(Icons.pause_rounded)),
          findsOneWidget);
      expect(find.byTooltip('Shuffle on'), findsOneWidget);

      await tester.tap(playButton());
      await settle(tester);

      expect(app.facade.calls, ['toggle']);
      expect(app.facade.plays, isEmpty, reason: 'it does not start over');
      await closeApp(tester, app.db);
    });

    testWidgets(
        'while something else plays, Play is Play and Shuffle is not lit',
        (tester) async {
      final app = await openLibraryArtist(
        tester,
        playing: const PlaybackSnapshot(
          isPlaying: true,
          shuffle: true,
          sourceName: 'The Walk',
          sourceId: 'album:al3',
        ),
      );

      expect(
          find.descendant(
              of: playButton(),
              matching: find.byIcon(Icons.play_arrow_rounded)),
          findsOneWidget);
      expect(find.byTooltip('Shuffle'), findsOneWidget);
      await closeApp(tester, app.db);
    });

    testWidgets(
        'an artist the server holds no song of has both buttons switched off '
        '(S-19, "nothing yet")', (tester) async {
      final app = await openLibraryArtist(
        tester,
        id: 'ar9',
        catalogue: FakeCatalogue(),
        seed: (db, serverId) => db.into(db.artists).insert(
            ArtistsCompanion.insert(
                serverId: serverId, id: 'ar9', name: 'Nobody')),
      );
      expect(find.text('Nobody'), findsWidgets,
          reason: 'precondition: the page opened');

      await tester.tap(playButton(), warnIfMissed: false);
      await tester.tap(find.byTooltip('Shuffle'), warnIfMissed: false);
      await settle(tester);

      expect(app.facade.plays, isEmpty);
      final faded =
          find.descendant(of: playButton(), matching: find.byType(Opacity));
      expect(tester.widget<Opacity>(faded).opacity, lessThan(0.5),
          reason: 'a filled green Play that cannot play looks like a bug');
      await closeApp(tester, app.db);
    });
  });

  group('the catalogue artist page', () {
    late _Backend backend;

    Future<({AppDatabase db, _Facade facade})> openCatalogueArtist(
      WidgetTester tester, {
      required List<CatalogueTrack> popular,
      PlaybackSnapshot? playing,
    }) async {
      backend = _Backend();
      final service = InstantPlayService(
        backend: backend,
        matcher: null,
        loadSong: (songId) async =>
            trackRow(songId, title: songId.substring(5), artist: 'Mastodon'),
        pollEvery: Duration.zero,
        delay: (_) async {},
      );
      final catalogue = FakeCatalogue()
        ..artistsById['c1'] = _mastodon
        ..topTracksByArtist['c1'] = popular;
      final facade = _Facade(playing ?? PlaybackSnapshot.idle);
      final app = await pumpApp(
        tester,
        size: const Size(390, 1800),
        overrides: [
          playbackFacadeProvider.overrideWithValue(facade),
          enginePlaybackFacadeProvider.overrideWithValue(facade),
          catalogueClientProvider.overrideWithValue(catalogue),
          instantAvailableProvider.overrideWithValue(true),
          instantPlayServiceProvider.overrideWith((ref) async => service),
        ],
      );
      // Created in real time, as in the instant-play page tests: a tap waits on it.
      final container = ProviderScope.containerOf(
          tester.element(find.byType(Scaffold).first));
      await tester
          .runAsync(() => container.read(instantPlayServiceProvider.future));
      Nav.catalogueArtist(tester.element(find.byType(Scaffold).first), 'c1');
      await settle(tester);
      await tester.pump(const Duration(seconds: 1));
      await settle(tester);
      return (db: app.db, facade: facade);
    }

    Future<void> press(WidgetTester tester, Finder button) async {
      await tester.runAsync(() async {
        await tester.tap(button);
        await Future<void>.delayed(const Duration(milliseconds: 80));
      });
      await settle(tester);
    }

    testWidgets(
        'Play plays the Popular songs from the first, in the page\'s order',
        (tester) async {
      final app = await openCatalogueArtist(tester, popular: _popular(12));
      expect(find.text('Mastodon Song 1'), findsOneWidget,
          reason: 'precondition: the Popular list is on the page');

      await press(tester, playButton());

      expect(backend.asked, [for (var i = 1; i <= 12; i++) 'Mastodon Song $i']);
      expect(app.facade.calls.first,
          'playTracks(1, start=0, source=Mastodon, shuffle=false)');
      await closeApp(tester, app.db);
    });

    testWidgets(
        'Shuffle plays the same songs, each once, in a different order from '
        'the page\'s', (tester) async {
      final app = await openCatalogueArtist(tester, popular: _popular(12));

      await press(tester, find.byTooltip('Shuffle'));

      final inPageOrder = [for (var i = 1; i <= 12; i++) 'Mastodon Song $i'];
      expect(backend.asked, hasLength(12));
      expect(backend.asked.toSet(), inPageOrder.toSet(),
          reason: 'every song once, none dropped');
      expect(backend.asked, isNot(inPageOrder),
          reason: 'the run is shuffled before the first song is asked for '
              '(1 chance in 479001600 that it is not)');
      expect(app.facade.calls.first, startsWith('playTracks(1, start=0'));
      await closeApp(tester, app.db);
    });

    testWidgets('an artist with no popular songs has both buttons switched off',
        (tester) async {
      final app = await openCatalogueArtist(tester, popular: const []);

      await tester.tap(playButton(), warnIfMissed: false);
      await tester.tap(find.byTooltip('Shuffle'), warnIfMissed: false);
      await settle(tester);

      expect(backend.asked, isEmpty);
      expect(app.facade.calls, isEmpty);
      await closeApp(tester, app.db);
    });

    testWidgets(
        'while this artist plays, Play pauses it instead of starting over',
        (tester) async {
      final app = await openCatalogueArtist(
        tester,
        popular: _popular(3),
        playing: const PlaybackSnapshot(
          isPlaying: true,
          sourceName: 'Mastodon',
          sourceId: 'catalogue-artist:c1',
        ),
      );

      await tester.tap(playButton());
      await settle(tester);

      expect(app.facade.calls, ['toggle']);
      expect(backend.asked, isEmpty);
      await closeApp(tester, app.db);
    });
  });
}
