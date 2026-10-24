import 'dart:async';

import 'package:encore/app/providers.dart';
import 'package:encore/app/session.dart';
import 'package:encore/data/catalogue/catalogue_models.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/fetch/fetch_client.dart';
import 'package:encore/features/catalogue/catalogue_screens.dart'
    show CatalogueArtistScreen;
import 'package:encore/features/detail/detail_screens.dart' show ArtistScreen;
import 'package:encore/features/instant/instant_controller.dart';
import 'package:encore/features/instant/instant_play.dart';
import 'package:encore/features/instant/library_resolver.dart';
import 'package:encore/features/player/now_playing_screen.dart';
import 'package:encore/features/player/playback_facade.dart';
import 'package:encore/features/player/streamed_song.dart';
import 'package:encore/features/requests/request_providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import '../support/factories.dart';
import '../support/fake_catalogue.dart';
import '../support/fake_http.dart';
import '../support/test_app.dart';

/// A song the instant-play service fetched plays from the service's stream
/// at once, but it can only be liked or put in a playlist once the music
/// server has listed it (ADR-066). Until then the player says so instead of
/// quietly doing nothing - or, as it did, starring an id the server never
/// heard of.
class _Resolver implements LibraryResolver {
  _Resolver(this.rows, {this.after = 0});

  final Map<String, TrackRow> rows;

  /// How many looks come back empty before the library has it (a test may
  /// change it: "the music server lists the song now").
  int after;
  int looks = 0;

  @override
  Future<TrackRow?> find({
    required String artist,
    required String title,
    String? album,
  }) async {
    looks++;
    return looks > after ? rows[title] : null;
  }
}

PlaybackSnapshot _playingStream({
  String id = 'cat-1',
  String? catalogueArtistId,
  String artist = 'Alcest',
}) =>
    PlaybackSnapshot(
      track: NowPlayingTrack(
        id: id,
        title: 'Opening',
        artist: artist,
        catalogueArtistId: catalogueArtistId,
        album: 'Kodama',
        imageUrl: 'https://cdn/cover.jpg',
        duration: const Duration(minutes: 4),
      ),
      isPlaying: true,
      duration: const Duration(minutes: 4),
      queueIndex: 0,
      queueLength: 1,
      sourceName: 'Kodama',
    );

void main() {
  setUpAll(loadAppFonts);

  late FakeHttpAdapter adapter;

  setUp(() {
    adapter = FakeHttpAdapter(routes: {
      'ping': (_) => FakeResponse.json(subsonicOk({})),
      'star': (_) => FakeResponse.json(subsonicOk({})),
      'unstar': (_) => FakeResponse.json(subsonicOk({})),
    });
  });

  Future<({AppDatabase db, FakePlaybackFacade facade, int serverId})>
      openPlayer(
    WidgetTester tester, {
    required _Resolver resolver,
    InstantStatus? status,
    String id = 'cat-1',
    String? catalogueArtistId,
    String artist = 'Alcest',
    FakeCatalogue? catalogue,
  }) async {
    final app = await pumpApp(
      tester,
      size: const Size(390, 1000),
      playing: _playingStream(
          id: id, catalogueArtistId: catalogueArtistId, artist: artist),
      session: (ref) async {
        final db = ref.read(databaseProvider);
        final server = (await db.select(db.servers).get()).first;
        final session = await ServerSession.create(
          verifyAddresses: false,
          db: db,
          server: server,
          password: 'x',
          dio: fakeDio(adapter),
        );
        ref.onDispose(() => unawaited(session.dispose()));
        return session;
      },
      overrides: [
        if (catalogue != null)
          catalogueClientProvider.overrideWithValue(catalogue),
        libraryResolverProvider.overrideWithValue(resolver),
        libraryLookDelaysProvider.overrideWithValue(const [
          Duration(milliseconds: 5),
          Duration(milliseconds: 5),
          Duration(milliseconds: 5),
        ]),
        if (status != null) instantStatusProvider(id).overrideWithValue(status),
      ],
    );
    final element = tester.element(find.byType(Scaffold).first);
    unawaited(GoRouter.of(element).push<void>('/player'));
    await settle(tester);
    return app;
  }

  Future<void> wait(WidgetTester tester) async {
    await tester
        .runAsync(() => Future<void>.delayed(const Duration(milliseconds: 60)));
    await settle(tester);
  }

  const onItsWay = InstantStatus.working(FetchState.downloading);
  final ready = InstantStatus.ready(null, streamUri: Uri.parse('http://svc/a'));

  testWidgets(
      'a song still on its way to the library offers the menu but explains '
      'instead of acting', (tester) async {
    final app = await openPlayer(
      tester,
      resolver: _Resolver(const {}, after: 1000),
      status: onItsWay,
    );

    expect(find.byType(NowPlayingScreen), findsOneWidget);
    expect(find.byTooltip('More options'), findsOneWidget);

    await tester.tap(find.byTooltip('More options'));
    await settle(tester);
    expect(find.textContaining('Still being added to your library'),
        findsOneWidget);

    await tester.tap(find.byTooltip('Add to Liked Songs'));
    await settle(tester);
    // Nothing was queued or sent for an id the server has never heard of.
    expect(await app.db.select(app.db.outbox).get(), isEmpty);
    expect(adapter.requests.where((r) => r.apiMethod == 'star'), isEmpty);
    await closeApp(tester, app.db);
  });

  testWidgets('once the library lists it, like and the menu act on that copy',
      (tester) async {
    final resolver = _Resolver({
      'Opening': trackRow('al2-t3', title: 'Opening', artist: 'Alcest'),
    }, after: 2);
    final app = await openPlayer(tester, resolver: resolver, status: ready);

    await wait(tester);
    await wait(tester);

    expect(resolver.looks, greaterThan(2));
    await tester.tap(find.byTooltip('Add to Liked Songs'));
    await settle(tester);
    await wait(tester); // the queued star is delivered
    // The library copy is starred, and the server was told about *that* id.
    final stored = await (app.db.select(app.db.tracks)
          ..where((t) => t.id.equals('al2-t3')))
        .getSingle();
    expect(stored.starredAtMs, isNotNull);
    final sent = adapter.requests.where((r) => r.apiMethod == 'star').toList();
    expect(sent, hasLength(1));
    expect(sent.single.params.values.expand((v) => v), contains('al2-t3'));
    expect(
        sent.single.params.values.expand((v) => v), isNot(contains('cat-1')));

    await tester.tap(find.byTooltip('More options'));
    await settle(tester);
    expect(find.text('Add to playlist'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  group(
      'the heart on a song fetched by the service (owner, 2026-10-17: "the heart '
      'does not turn green until I leave the player and come back")', () {
    /// What the person sees: the heart and what it would do next.
    bool heartIsFilled(WidgetTester tester) =>
        find.byTooltip('Remove from Liked Songs').evaluate().isNotEmpty;

    Color? heartColour(WidgetTester tester) {
      final icon = tester.widget<Icon>(find.descendant(
        of: find.byTooltip('Remove from Liked Songs'),
        matching: find.byIcon(Icons.favorite_rounded),
      ));
      return icon.color;
    }

    Future<AppDatabase> openWithRow(
      WidgetTester tester, {
      required bool rowComesFromTheFetchStatus,
    }) async {
      final row = trackRow('al2-t3', title: 'Opening', artist: 'Alcest');
      final app = await openPlayer(
        tester,
        resolver: _Resolver({'Opening': row}),
        status: rowComesFromTheFetchStatus ? InstantStatus.ready(row) : ready,
      );
      await wait(tester);
      return app.db;
    }

    for (final fromStatus in [true, false]) {
      final how = fromStatus
          ? 'the fetch status carried the library row'
          : 'the player found the row by looking';

      testWidgets('turns on at once when pressed ($how)', (tester) async {
        final db =
            await openWithRow(tester, rowComesFromTheFetchStatus: fromStatus);
        expect(heartIsFilled(tester), isFalse, reason: 'it starts empty');

        await tester.tap(find.byTooltip('Add to Liked Songs'));
        await tester.pump(); // ONE frame: a person sees the answer now

        expect(heartIsFilled(tester), isTrue,
            reason: 'the heart must answer on the next frame, not after a '
                'trip to the server or a visit to another screen');
        expect(heartColour(tester), isNot(const Color(0xFFFFFFFF)),
            reason: 'and it is the accent colour, not the empty heart');
        await closeApp(tester, db);
      });

      testWidgets('turns off again when pressed again ($how)', (tester) async {
        final db =
            await openWithRow(tester, rowComesFromTheFetchStatus: fromStatus);

        await tester.tap(find.byTooltip('Add to Liked Songs'));
        await tester.pump();
        await tester.tap(find.byTooltip('Remove from Liked Songs'));
        await tester.pump();

        expect(heartIsFilled(tester), isFalse);
        expect(find.byTooltip('Add to Liked Songs'), findsOneWidget);
        await closeApp(tester, db);
      });

      testWidgets('is still on after the delivery to the server ($how)',
          (tester) async {
        final db =
            await openWithRow(tester, rowComesFromTheFetchStatus: fromStatus);

        await tester.tap(find.byTooltip('Add to Liked Songs'));
        await settle(tester);
        await wait(tester); // the queued star is delivered
        await settle(tester);

        expect(heartIsFilled(tester), isTrue);
        await closeApp(tester, db);
      });
    }
  });

  group(
      'liking a song that is still being added to the library (owner, '
      '2026-10-17: "pressing like on a song not in the server... hella slow")',
      () {
    bool heartIsFilled() =>
        find.byTooltip('Remove from Liked Songs').evaluate().isNotEmpty;

    Future<({AppDatabase db, FakePlaybackFacade facade, int serverId})> open(
      WidgetTester tester,
      _Resolver resolver,
    ) =>
        openPlayer(tester, resolver: resolver, status: onItsWay);

    Future<int> starsSent() async =>
        adapter.requests.where((r) => r.apiMethod == 'star').length;

    testWidgets('the heart turns on at once and nothing is said',
        (tester) async {
      final app = await open(tester, _Resolver(const {}, after: 1000));

      await tester.tap(find.byTooltip('Add to Liked Songs'));
      await tester.pump(); // one frame

      expect(heartIsFilled(), isTrue,
          reason:
              'the answer to a tap is immediate, whatever the server is doing');
      expect(find.textContaining('Still being added'), findsNothing,
          reason: 'no message: the like is kept and delivered');
      expect(await starsSent(), 0,
          reason: 'there is no library song to star yet');
      await closeApp(tester, app.db);
    });

    testWidgets('it is delivered once, to the library song, when it is listed',
        (tester) async {
      final resolver = _Resolver({
        'Opening': trackRow('al2-t3', title: 'Opening', artist: 'Alcest'),
      }, after: 1000);
      final app = await open(tester, resolver);

      await tester.tap(find.byTooltip('Add to Liked Songs'));
      await tester.pump();
      expect(await starsSent(), 0, reason: 'not listed yet: nothing to star');
      resolver.after = 0; // the music server lists the song now
      await wait(tester);
      await wait(tester);
      await wait(tester);

      final stored = await (app.db.select(app.db.tracks)
            ..where((t) => t.id.equals('al2-t3')))
          .getSingle();
      expect(stored.starredAtMs, isNotNull,
          reason: 'the library copy is liked');
      final sent =
          adapter.requests.where((r) => r.apiMethod == 'star').toList();
      expect(sent, hasLength(1), reason: 'exactly once');
      expect(sent.single.params.values.expand((v) => v), contains('al2-t3'));
      expect(heartIsFilled(), isTrue,
          reason: 'and the heart never flickered off');
      await closeApp(tester, app.db);
    });

    testWidgets('pressing again before it arrives takes the like back',
        (tester) async {
      final resolver = _Resolver({
        'Opening': trackRow('al2-t3', title: 'Opening', artist: 'Alcest'),
      }, after: 1000);
      final app = await open(tester, resolver);

      await tester.tap(find.byTooltip('Add to Liked Songs'));
      await tester.pump();
      await tester.tap(find.byTooltip('Remove from Liked Songs'));
      await tester.pump();
      expect(heartIsFilled(), isFalse);

      resolver.after = 0; // it is listed now, and nobody wants it liked
      await wait(tester);
      await wait(tester);
      await wait(tester);

      expect(await starsSent(), 0, reason: 'a cancelled like is never sent');
      final stored = await (app.db.select(app.db.tracks)
            ..where((t) => t.id.equals('al2-t3')))
          .getSingleOrNull();
      expect(stored?.starredAtMs, isNull);
      await closeApp(tester, app.db);
    });

    testWidgets('it is still delivered after the player is closed',
        (tester) async {
      final resolver = _Resolver({
        'Opening': trackRow('al2-t3', title: 'Opening', artist: 'Alcest'),
      }, after: 1000);
      final app = await open(tester, resolver);

      await tester.tap(find.byTooltip('Add to Liked Songs'));
      await tester.pump();
      await tester.tap(find.byTooltip('Close player'));
      resolver.after = 0; // listed just as the person leaves the player
      await settle(tester);
      expect(find.byType(NowPlayingScreen), findsNothing);
      await wait(tester);
      await wait(tester);
      await wait(tester);

      expect(await starsSent(), 1,
          reason: 'the person pressed the heart and left: it still counts');
      await closeApp(tester, app.db);
    });

    testWidgets(
        'if the song never arrives the heart goes back off, with a reason',
        (tester) async {
      final app = await open(tester, _Resolver(const {}, after: 1000));

      await tester.tap(find.byTooltip('Add to Liked Songs'));
      await tester.pump();
      expect(heartIsFilled(), isTrue);

      await wait(tester); // the few short looks of this test are used up
      await wait(tester);
      await wait(tester);

      expect(heartIsFilled(), isFalse, reason: 'what is shown is what is true');
      expect(find.textContaining('was not liked'), findsOneWidget);
      expect(find.textContaining('Opening'), findsWidgets);
      expect(await starsSent(), 0);
      await closeApp(tester, app.db);
    });
  });

  testWidgets(
      'a 30-second sample shows no lyrics: they belong to the whole song, '
      'not to the clip (owner, B34)', (tester) async {
    final app = await openPlayer(
      tester,
      resolver: _Resolver(const {}),
      status: null, // not fetched by the service: a catalogue sample
    );

    expect(find.byType(NowPlayingScreen), findsOneWidget);
    expect(find.text('Lyrics'), findsNothing);
    await closeApp(tester, app.db);
  });

  testWidgets('a song the service fetched keeps its lyrics button',
      (tester) async {
    final app = await openPlayer(
      tester,
      resolver: _Resolver(const {}, after: 1000),
      status: ready,
    );

    expect(find.text('Lyrics'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  group('the artist of a song that came from the catalogue', () {
    testWidgets(
        'can be tapped to open the artist, as for any song (owner, Q3: "i cant '
        'press the raid text")', (tester) async {
      final catalogue = FakeCatalogue()
        ..artistsById['77'] =
            const CatalogueArtist(id: '77', name: 'Alcest', fans: 90000);
      final app = await openPlayer(
        tester,
        resolver: _Resolver(const {}, after: 1000),
        status: ready,
        catalogueArtistId: '77',
        catalogue: catalogue,
      );

      await tester.tap(find.text('Alcest'));
      await settle(tester);

      expect(find.byType(NowPlayingScreen), findsNothing,
          reason: 'the player closes and the artist opens');
      expect(catalogue.lookups, contains('artist:77'));
      await closeApp(tester, app.db);
    });

    testWidgets(
        'with no id to open, the name is looked up and the best known artist '
        'of that name opens (owner: "i still cant press dizzy dros")',
        (tester) async {
      final catalogue = FakeCatalogue(const CatalogueResults(artists: [
        CatalogueArtist(id: '5', name: 'Dizzy DROS Tribute', fans: 12),
        CatalogueArtist(id: '77', name: 'Dizzy DROS', fans: 90000),
      ]))
        ..artistsById['77'] =
            const CatalogueArtist(id: '77', name: 'Dizzy DROS', fans: 90000);
      final app = await openPlayer(
        tester,
        resolver: _Resolver(const {}, after: 1000),
        status: ready,
        artist: 'Dizzy DROS',
        catalogue: catalogue,
      );

      await tester.tap(find.text('Dizzy DROS'));
      await settle(tester);

      expect(catalogue.queries, ['Dizzy DROS']);
      expect(find.byType(NowPlayingScreen), findsNothing,
          reason: 'the player closes and the artist opens');
      expect(find.byType(CatalogueArtistScreen), findsOneWidget);
      await closeApp(tester, app.db);
    });

    testWidgets('an artist the library has opens the page from the library',
        (tester) async {
      final catalogue = FakeCatalogue();
      final app = await openPlayer(
        tester,
        resolver: _Resolver(const {}, after: 1000),
        status: ready,
        catalogue: catalogue,
      );

      await tester.tap(find.text('Alcest'));
      await settle(tester);

      expect(find.byType(ArtistScreen), findsOneWidget);
      await closeApp(tester, app.db);
    });

    testWidgets('when nobody of that name is found it says so and stays',
        (tester) async {
      final catalogue = FakeCatalogue();
      final app = await openPlayer(
        tester,
        resolver: _Resolver(const {}, after: 1000),
        status: ready,
        artist: 'Dizzy DROS',
        catalogue: catalogue,
      );

      await tester.tap(find.text('Dizzy DROS'));
      await settle(tester);

      expect(find.byType(NowPlayingScreen), findsOneWidget);
      expect(find.textContaining('Could not find Dizzy DROS'), findsOneWidget);
      await closeApp(tester, app.db);
    });
  });

  testWidgets('a 30-second sample cannot be liked and has no menu',
      (tester) async {
    final app = await openPlayer(
      tester,
      resolver: _Resolver(const {}),
      status: null, // not fetched by the service: a catalogue sample
    );

    expect(find.byTooltip('More options'), findsNothing);
    final heart = tester.widget<IconButton>(
        find.widgetWithIcon(IconButton, Icons.favorite_border_rounded));
    expect(heart.onPressed, isNull);
    await closeApp(tester, app.db);
  });
}
