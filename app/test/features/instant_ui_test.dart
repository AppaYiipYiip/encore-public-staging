import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:encore/core/result.dart';
import 'package:encore/data/catalogue/catalogue_models.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/fetch/fetch_client.dart';
import 'package:encore/data/requests/portal_client.dart';
import 'package:encore/features/instant/instant_controller.dart';
import 'package:encore/features/instant/instant_play.dart';
import 'package:encore/features/requests/request_providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/factories.dart';
import '../support/fake_catalogue.dart';
import '../support/test_app.dart';

/// A service that gets every song at once.
class _InstantBackend implements InstantPlayBackend {
  final List<String> asked = [];
  final List<String> prepared = [];

  @override
  Future<void> prepare(FetchRequest request) async =>
      prepared.add(request.title);

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
  Uri? streamUri(FetchJob job) =>
      job.stream == null ? null : Uri.parse('http://svc${job.stream}');
}

/// A download service the person connected themselves (the author's own
/// stack); a friend on the author's server has none.
class _Portal implements RequestBackend {
  @override
  Future<Result<RequestReceipt>> request(
          {required String artist, String? album}) async =>
      Result.ok(RequestReceipt(kind: 'album', name: album ?? artist));

  @override
  Future<Result<PortalOverview>> overview() async =>
      const Result.ok(PortalOverview());

  @override
  Future<Result<String>> check() async => const Result.ok('marwa');
}

const _album = CatalogueAlbum(
  id: '10',
  title: 'Damnation',
  artistName: 'Opeth',
  artistId: '1',
  year: 2003,
  trackCount: 3,
  recordType: 'album',
);

CatalogueTrack _t(String id, String title, int no) => CatalogueTrack(
      id: id,
      title: title,
      artistName: 'Opeth',
      artistId: '1',
      albumTitle: 'Damnation',
      albumId: '10',
      duration: const Duration(minutes: 4),
      previewUrl: 'https://cdn/p.mp3',
      trackNumber: no,
    );

void main() {
  setUpAll(loadAppFonts);

  late _InstantBackend backend;

  FakeCatalogue catalogue({List<CatalogueTrack> found = const []}) {
    final c = FakeCatalogue(CatalogueResults(
      albums: const [_album],
      tracks: found,
    ));
    c.albumsById['10'] = _album;
    c.tracksByAlbum['10'] = [
      _t('t1', 'Windowpane', 5),
      _t('t2', 'In My Time of Need', 6),
      _t('t3', 'Death Whispered a Lullaby', 7),
    ];
    return c;
  }

  Future<({AppDatabase db, FakePlaybackFacade facade, int serverId})> open(
    WidgetTester tester, {
    bool instant = true,
    RequestBackend? portal,
    List<CatalogueTrack> found = const [],
  }) async {
    backend = _InstantBackend();
    final service = InstantPlayService(
      backend: backend,
      matcher: null,
      loadSong: (songId) async =>
          trackRow(songId, title: songId.substring(5), artist: 'Opeth'),
      pollEvery: Duration.zero,
      delay: (_) async {},
    );
    final app = await pumpApp(tester, overrides: [
      catalogueClientProvider.overrideWithValue(catalogue(found: found)),
      instantAvailableProvider.overrideWithValue(instant),
      instantPlayServiceProvider.overrideWith((ref) async => service),
      requestBackendProvider.overrideWith((ref) async => portal),
    ]);
    // The service's future is created here, in real time: a page's warm-up
    // would otherwise create it inside the test's fake-async zone, and a tap
    // (real time) would wait for a clock that only `pump` advances.
    final container =
        ProviderScope.containerOf(tester.element(find.byType(Scaffold).first));
    await tester
        .runAsync(() => container.read(instantPlayServiceProvider.future));
    return app;
  }

  Future<void> openAlbum(WidgetTester tester) async {
    await tester.tap(find.text('Search').last);
    await settle(tester);
    await tester.enterText(find.byType(TextField), 'Damnation');
    await tester.pump(const Duration(milliseconds: 600));
    await settle(tester);
    await tester.tap(find.text('Opeth - 2003 - 3 songs'));
    await settle(tester);
  }

  testWidgets('with the service, a catalogue song plays the whole song',
      (tester) async {
    final app = await open(tester);
    await openAlbum(tester);

    expect(find.textContaining('Tap a song to play it'), findsOneWidget);
    expect(find.text('Add to library'), findsOneWidget);

    await tester.runAsync(() async {
      await tester.tap(find.text('In My Time of Need'));
      await Future<void>.delayed(const Duration(milliseconds: 50));
    });
    await settle(tester);

    // The tapped song starts, then the rest of the album is queued in order.
    expect(app.facade.calls, [
      'playTracks(1, start=0, source=Damnation, shuffle=false)',
      'queue(song-Death Whispered a Lullaby)',
      'queue(song-Windowpane)',
    ]);
    expect(backend.asked, containsAll(['In My Time of Need', 'Windowpane']));
    await closeApp(tester, app.db);
  });

  testWidgets(
      'the page speaks plainly: Add to library, Download, and a menu - no '
      '"Request" button', (tester) async {
    final app = await open(tester);
    await openAlbum(tester);

    expect(find.text('Add to library'), findsOneWidget);
    expect(find.byTooltip('Download Damnation for offline listening'),
        findsOneWidget);
    expect(find.text('Request'), findsNothing);
    // Rows on the page carry no button of their own either.
    expect(find.text('Requested'), findsNothing);

    await tester.tap(find.byTooltip('More options'));
    await settle(tester);
    expect(find.text('How does this work?'), findsWidgets);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'a phone with instant play and no download service is never offered '
      'the way to connect one', (tester) async {
    // The owner, 2026-10-17, on a friend's phone: the album's menu led to
    // "Connect your download service", something a friend cannot have.
    final app = await open(tester);
    await openAlbum(tester);

    await tester.tap(find.byTooltip('More options'));
    await settle(tester);

    expect(find.text('Ask for better quality'), findsNothing);
    expect(find.text('Connect your download service'), findsNothing);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'a person who did connect a download service still sees "Ask for '
      'better quality"', (tester) async {
    final app = await open(tester, portal: _Portal());
    await openAlbum(tester);

    await tester.tap(find.byTooltip('More options'));
    await settle(tester);

    expect(find.text('Ask for better quality'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets('the help says what each word means, in four short lines',
      (tester) async {
    final app = await open(tester);
    await openAlbum(tester);

    await tester.tap(find.text('How does this work?').first);
    await settle(tester);
    expect(find.text('How adding music works'), findsOneWidget);
    for (final word in const [
      'Play',
      'Add to library',
      'Download',
      'Ask for better quality',
    ]) {
      expect(find.text(word), findsWidgets, reason: word);
    }
    expect(find.textContaining('without internet'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'Download adds the album to the library and keeps it on the '
      'phone', (tester) async {
    final app = await open(tester);
    await openAlbum(tester);
    // The library gets the album as the songs arrive (the fake service
    // does not scan, so the row is there beforehand).
    await app.db.into(app.db.albums).insert(AlbumsCompanion.insert(
          serverId: app.serverId,
          id: 'dam1',
          name: 'Damnation',
          artist: const Value('Opeth'),
        ));

    await tester
        .tap(find.byTooltip('Download Damnation for offline listening'));
    await settle(tester);
    expect(find.textContaining('Getting Damnation'), findsOneWidget);
    // The songs arrive in real time (provider futures), the page stays up.
    for (var i = 0; i < 20; i++) {
      await tester.runAsync(
          () => Future<void>.delayed(const Duration(milliseconds: 50)));
      await settle(tester);
      if ((await app.db.select(app.db.pins).get()).isNotEmpty) break;
    }

    expect(backend.asked, hasLength(3), reason: 'every song was fetched');
    final pins = await app.db.select(app.db.pins).get();
    expect(pins.map((p) => (p.targetType, p.targetId)), [('album', 'dam1')]);
    await closeApp(tester, app.db);
  });

  group('while the person reads the search results', () {
    Future<void> search(WidgetTester tester, String text) async {
      await tester.tap(find.text('Search').last);
      await settle(tester);
      await tester.enterText(find.byType(TextField), text);
      await tester.pump(const Duration(milliseconds: 600));
      await settle(tester);
      await tester.runAsync(
          () => Future<void>.delayed(const Duration(milliseconds: 50)));
      await settle(tester);
    }

    testWidgets(
        'the service looks up the top song, so the tap that follows '
        'starts at the download (measured: 4.6 s of the wait)', (tester) async {
      final app = await open(tester, found: [
        _t('t1', 'Windowpane', 5),
        _t('t2', 'In My Time of Need', 6),
      ]);

      await search(tester, 'Windowpane');

      expect(backend.prepared, ['Windowpane'],
          reason: 'the first song only, once');
      await closeApp(tester, app.db);
    });

    testWidgets('a different search prepares its own top song', (tester) async {
      final app = await open(tester, found: [_t('t1', 'Windowpane', 5)]);
      await search(tester, 'Windowpane');
      (app.db);

      await tester.enterText(find.byType(TextField), 'Windowpane live');
      await tester.pump(const Duration(milliseconds: 600));
      await settle(tester);
      await tester.runAsync(
          () => Future<void>.delayed(const Duration(milliseconds: 50)));
      await settle(tester);

      expect(backend.prepared, ['Windowpane'],
          reason: 'the same song is not asked for twice');
      await closeApp(tester, app.db);
    });

    testWidgets('nothing is prepared without the service', (tester) async {
      final app = await open(tester, instant: false, found: [
        _t('t1', 'Windowpane', 5),
      ]);

      await search(tester, 'Windowpane');

      expect(backend.prepared, isEmpty);
      await closeApp(tester, app.db);
    });
  });

  testWidgets('opening an album page prepares its first song, once',
      (tester) async {
    final app = await open(tester);
    await openAlbum(tester);
    await tester
        .runAsync(() => Future<void>.delayed(const Duration(milliseconds: 50)));
    await settle(tester);

    expect(backend.prepared, ['Windowpane']);
    expect(backend.asked, isEmpty, reason: 'only looked up, not fetched');
    await closeApp(tester, app.db);
  });

  testWidgets('without the service nothing is prepared', (tester) async {
    final app = await open(tester, instant: false);
    await openAlbum(tester);
    await tester
        .runAsync(() => Future<void>.delayed(const Duration(milliseconds: 50)));
    await settle(tester);

    expect(backend.prepared, isEmpty);
    await closeApp(tester, app.db);
  });

  testWidgets('"Add to library" gets every song without playing',
      (tester) async {
    final app = await open(tester);
    await openAlbum(tester);

    await tester.runAsync(() async {
      await tester.tap(find.text('Add to library'));
      await Future<void>.delayed(const Duration(milliseconds: 50));
    });
    await settle(tester);

    expect(backend.asked, hasLength(3));
    expect(app.facade.calls.where((c) => c.startsWith('playTracks')), isEmpty);
    expect(find.text('In your library'), findsWidgets);
    await closeApp(tester, app.db);
  });

  testWidgets('without the service the page keeps previews only',
      (tester) async {
    final app = await open(tester, instant: false);
    await openAlbum(tester);

    expect(find.textContaining('30 seconds'), findsOneWidget);
    expect(find.text('Add to library'), findsNothing);

    await tester.tap(find.text('Windowpane'));
    await settle(tester);
    expect(app.facade.calls, contains('previews(t1,t2,t3, start=0)'));
    expect(backend.asked, isEmpty);
    await closeApp(tester, app.db);
  });
}
