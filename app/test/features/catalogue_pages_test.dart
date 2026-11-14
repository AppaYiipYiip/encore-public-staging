import 'package:encore/app/server_kind.dart';
import 'package:encore/core/result.dart';
import 'package:encore/data/catalogue/catalogue_models.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/requests/portal_client.dart';
import 'package:encore/features/catalogue/catalogue_providers.dart';
import 'package:encore/features/catalogue/catalogue_widgets.dart';
import 'package:encore/features/instant/instant_controller.dart';
import 'package:encore/features/instant/tap_play.dart' show kPlainServerLine;
import 'package:encore/features/requests/request_providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import '../support/fake_catalogue.dart';
import '../support/test_app.dart';

class _Portal implements RequestBackend {
  final List<String> requests = [];

  @override
  Future<Result<RequestReceipt>> request(
      {required String artist, String? album}) async {
    requests.add('$artist|${album ?? ''}');
    return Result.ok(RequestReceipt(kind: 'album', name: album ?? artist));
  }

  @override
  Future<Result<PortalOverview>> overview() async =>
      const Result.ok(PortalOverview());

  @override
  Future<Result<String>> check() async => const Result.ok('marwa');
}

const _folklore = CatalogueAlbum(
  id: '10',
  title: 'Folklore',
  artistName: 'Taylor Swift',
  artistId: '1',
  year: 2020,
  trackCount: 3,
  recordType: 'album',
);

const _swift = CatalogueArtist(
  id: '1',
  name: 'Taylor Swift',
  fans: 1200000,
  albumCount: 12,
);

CatalogueTrack _track(String id, String title) => CatalogueTrack(
      id: id,
      title: title,
      artistName: 'Taylor Swift',
      artistId: '1',
      albumTitle: 'Folklore',
      albumId: '10',
      duration: const Duration(minutes: 3, seconds: 59),
    );

FakeCatalogue _catalogue() {
  final c = FakeCatalogue(const CatalogueResults(
    artists: [_swift],
    albums: [_folklore],
  ));
  c.albumsById['10'] = _folklore;
  c.artistsById['1'] = _swift;
  c.tracksByAlbum['10'] = [
    _track('t1', 'the 1'),
    _track('t2', 'cardigan'),
    _track('t3', 'the last great american dynasty'),
  ];
  c.topTracksByArtist['1'] = [
    _track('t2', 'cardigan'),
    _track('t9', 'Anti-Hero'),
  ];
  c.albumsByArtist['1'] = [
    const CatalogueAlbum(
      id: '10',
      title: 'Folklore',
      artistName: 'Taylor Swift',
      year: 2020,
      recordType: 'album',
    ),
    // Clean/explicit duplicates of one release are folded.
    const CatalogueAlbum(
      id: '11',
      title: 'Folklore (Deluxe Edition)',
      artistName: 'Taylor Swift',
      year: 2020,
      recordType: 'album',
    ),
    const CatalogueAlbum(
      id: '12',
      title: 'Midnights',
      artistName: 'Taylor Swift',
      year: 2022,
      recordType: 'album',
    ),
    const CatalogueAlbum(
      id: '13',
      title: 'Lavender Haze',
      artistName: 'Taylor Swift',
      year: 2022,
      recordType: 'single',
    ),
  ];
  return c;
}

void main() {
  setUpAll(loadAppFonts);

  Future<void> search(WidgetTester tester, String text) async {
    await tester.tap(find.text('Search').last);
    await settle(tester);
    await tester.enterText(find.byType(TextField), text);
    await tester.pump(const Duration(milliseconds: 600));
    await settle(tester);
  }

  group('album page', () {
    testWidgets(
        'opens from search and lists songs; on a server that only plays what it has, a tap says so and plays nothing (D-64: no preview)',
        (tester) async {
      final app = await pumpApp(tester, overrides: [
        catalogueClientProvider.overrideWithValue(_catalogue()),
        requestBackendProvider.overrideWith((ref) async => _Portal()),
      ]);

      await search(tester, 'Taylor Swift');
      await tester.tap(find.text('Folklore'));
      await settle(tester);

      expect(find.text('Taylor Swift'), findsWidgets);
      expect(find.text('2020 • 3 songs • Album'), findsOneWidget);
      expect(find.text('the 1'), findsOneWidget);
      expect(find.text('cardigan'), findsOneWidget);
      expect(find.textContaining('only plays songs it already has'),
          findsOneWidget);

      await tester.tap(find.text('cardigan'));
      await settle(tester);

      expect(find.text(kPlainServerLine), findsOneWidget);
      expect(app.facade.calls.where((c) => c.startsWith('streamed')), isEmpty,
          reason: 'nothing plays, not even a snippet');
      await closeApp(tester, app.db);
    });

    testWidgets(
        'on an Encore server no Request chip is offered, whatever the play '
        'switch says (AUDIT A-7, M3)', (tester) async {
      final app = await pumpApp(tester, overrides: [
        catalogueClientProvider.overrideWithValue(_catalogue()),
        requestBackendProvider.overrideWith((ref) async => _Portal()),
        serverKindProvider.overrideWithValue(ServerKind.encore),
        instantAvailableProvider.overrideWithValue(false),
      ]);

      await search(tester, 'Taylor Swift');
      expect(find.text('Request'), findsNothing, reason: 'the search results');
      await tester.tap(find.text('Folklore'));
      await settle(tester);

      expect(find.text('Request'), findsNothing, reason: 'the album page');
      await closeApp(tester, app.db);
    });

    // Artists and a song the library does not have: their rows and an artist's page are where the Request chips would be. The first artist
    // is the Top result, the second one gets a row of its own.
    Future<AppDatabase> openUnownedArtists(WidgetTester tester,
        {required bool encore}) async {
      const phoebe = CatalogueArtist(
          id: '7', name: 'Phoebe Bridgers', fans: 500000, albumCount: 4);
      const julien = CatalogueArtist(
          id: '8', name: 'Phoebe Snow', fans: 300000, albumCount: 3);
      final song = CatalogueTrack(
        id: 't7',
        title: 'Motion Sickness',
        artistName: 'Phoebe Bridgers',
        artistId: '7',
        albumTitle: 'Stranger in the Alps',
        albumId: '70',
        duration: const Duration(minutes: 3, seconds: 49),
      );
      final c = FakeCatalogue(
          CatalogueResults(artists: const [phoebe, julien], tracks: [song]))
        ..artistsById['7'] = phoebe
        ..artistsById['8'] = julien
        ..topTracksByArtist['7'] = [song]
        ..topTracksByArtist['8'] = [song];
      final app = await pumpApp(tester, overrides: [
        catalogueClientProvider.overrideWithValue(c),
        requestBackendProvider.overrideWith((ref) async => _Portal()),
        if (encore) serverKindProvider.overrideWithValue(ServerKind.encore),
        instantAvailableProvider.overrideWithValue(false),
      ]);
      await search(tester, 'Phoebe');
      return app.db;
    }

    testWidgets(
        'a plain server without the instant service still offers Request on '
        'artists and songs (the control of the next test)', (tester) async {
      final db = await openUnownedArtists(tester, encore: false);

      expect(find.textContaining('releases'), findsOneWidget,
          reason: 'the artist that is not the Top result has a row of its own');
      expect(find.text('Request'), findsAtLeastNWidgets(2),
          reason: 'on the song and on that artist');
      await closeApp(tester, db);
    });

    testWidgets(
        'on an Encore server artists and songs you do not have carry no '
        'Request chip, in the results or on an artist page (AUDIT A-7, M3)',
        (tester) async {
      final db = await openUnownedArtists(tester, encore: true);

      expect(find.textContaining('releases'), findsOneWidget,
          reason: 'the artist row is there');
      expect(find.text('Motion Sickness'), findsWidgets,
          reason: 'and so is the song row');
      expect(find.text('Request'), findsNothing, reason: 'the search results');
      await tester.tap(find.textContaining('releases'));
      await settle(tester);

      expect(find.text('Popular'), findsWidgets,
          reason: 'the artist page opened');
      expect(find.text('Request'), findsNothing, reason: 'the artist page');
      await closeApp(tester, db);
    });

    testWidgets('Request on the page sends artist and album', (tester) async {
      final portal = _Portal();
      final app = await pumpApp(tester, overrides: [
        catalogueClientProvider.overrideWithValue(_catalogue()),
        requestBackendProvider.overrideWith((ref) async => portal),
      ]);

      await search(tester, 'Taylor Swift');
      await tester.tap(find.text('Folklore'));
      await settle(tester);

      await tester.tap(find.text('Request').first);
      await settle(tester);

      expect(portal.requests, ['Taylor Swift|Folklore']);
      expect(find.text('Requested'), findsWidgets);
      await closeApp(tester, app.db);
    });

    testWidgets('deep link without a search hit fetches the release',
        (tester) async {
      final catalogue = _catalogue();
      final app = await pumpApp(tester, overrides: [
        catalogueClientProvider.overrideWithValue(catalogue),
        requestBackendProvider.overrideWith((ref) async => _Portal()),
      ]);

      final element = tester.element(find.byType(Scaffold).first);
      GoRouter.of(element).go('/search/catalogue/album/10');
      await settle(tester);

      expect(catalogue.lookups, contains('album:10'));
      expect(find.text('Folklore'), findsWidgets);
      expect(find.text('cardigan'), findsOneWidget);
      await closeApp(tester, app.db);
    });

    testWidgets('an unreachable catalogue explains itself and can retry',
        (tester) async {
      final catalogue = FakeCatalogue(); // knows nothing: every lookup fails
      final app = await pumpApp(tester, overrides: [
        catalogueClientProvider.overrideWithValue(catalogue),
        requestBackendProvider.overrideWith((ref) async => _Portal()),
      ]);

      final element = tester.element(find.byType(Scaffold).first);
      GoRouter.of(element).go('/search/catalogue/album/404');
      await settle(tester);

      expect(find.text("Couldn't load this release"), findsOneWidget);
      final before = catalogue.lookups.length;
      await tester.tap(find.text('Try again'));
      await settle(tester);
      expect(catalogue.lookups.length, greaterThan(before));
      await closeApp(tester, app.db);
    });
  });

  group('artist page', () {
    testWidgets('shows popular songs and releases; duplicates folded',
        (tester) async {
      final app = await pumpApp(
        tester,
        // Tall enough that the lists below the hero are built.
        size: const Size(390, 1800),
        overrides: [
          catalogueClientProvider.overrideWithValue(_catalogue()),
          requestBackendProvider.overrideWith((ref) async => _Portal()),
        ],
      );

      await search(tester, 'Taylor Swift');
      // The artist that was typed is the Top result.
      await tester.tap(find.byKey(const Key('top-result')));
      await settle(tester);

      expect(find.text('1.2M fans'), findsOneWidget);
      expect(find.text('Popular'), findsOneWidget);
      expect(find.text('cardigan'), findsOneWidget);
      expect(find.text('Anti-Hero'), findsOneWidget);
      expect(find.text('Albums'), findsOneWidget);
      expect(find.text('Singles and EPs'), findsOneWidget);
      expect(find.text('Midnights'), findsOneWidget);
      expect(find.text('Folklore'), findsOneWidget,
          reason: 'deluxe edition folded into one row');
      expect(find.textContaining('Deluxe'), findsNothing);

      await tester.tap(find.text('Anti-Hero'));
      await settle(tester);
      expect(find.text(kPlainServerLine), findsOneWidget);
      expect(app.facade.calls.where((c) => c.startsWith('streamed')), isEmpty);
      await closeApp(tester, app.db);
    });

    testWidgets('a release the user owns opens the library album',
        (tester) async {
      // "The Walk" by Periphery is in the seeded library.
      final catalogue = FakeCatalogue();
      catalogue.artistsById['77'] =
          const CatalogueArtist(id: '77', name: 'Periphery', fans: 900);
      catalogue.albumsByArtist['77'] = [
        const CatalogueAlbum(
            id: '1', title: 'The Walk', artistName: 'Periphery', year: 2023),
        const CatalogueAlbum(
            id: '2', title: 'Periphery V', artistName: 'Periphery', year: 2023),
      ];
      final app = await pumpApp(
        tester,
        size: const Size(390, 1800),
        overrides: [
          catalogueClientProvider.overrideWithValue(catalogue),
          requestBackendProvider.overrideWith((ref) async => _Portal()),
        ],
      );

      final element = tester.element(find.byType(Scaffold).first);
      GoRouter.of(element).go('/search/catalogue/artist/77');
      await settle(tester);

      expect(find.text('900 fans'), findsOneWidget);
      expect(find.byIcon(Icons.library_music_rounded), findsOneWidget);

      await tester.tap(find.text('The Walk'));
      await settle(tester);

      // Landed on the library album page: its own songs are listed.
      expect(find.text('Opening The'), findsOneWidget);
      await closeApp(tester, app.db);
    });
  });

  group('helpers', () {
    test('foldReleases sorts newest first and folds editions', () {
      const albums = [
        CatalogueAlbum(id: '1', title: 'Old', artistName: 'A', year: 2001),
        CatalogueAlbum(id: '2', title: 'New', artistName: 'A', year: 2024),
        CatalogueAlbum(
            id: '3',
            title: 'New (Deluxe Edition)',
            artistName: 'A',
            year: 2024),
        CatalogueAlbum(id: '4', title: 'Undated', artistName: 'A'),
      ];
      final folded = foldReleases(albums);
      expect(folded.map((a) => a.id), ['2', '1', '4']);
    });

    test('groupReleases separates albums, singles/EPs and compilations', () {
      ArtistRelease r(String id, String? type) => ArtistRelease(
            CatalogueAlbum(
                id: id, title: 't$id', artistName: 'A', recordType: type),
          );
      final groups = groupReleases([
        r('1', 'album'),
        r('2', 'single'),
        r('3', 'ep'),
        r('4', 'compile'),
        r('5', null),
      ]);
      expect(groups.albums.map((e) => e.album.id), ['1', '5']);
      expect(groups.singles.map((e) => e.album.id), ['2', '3']);
      expect(groups.compilations.map((e) => e.album.id), ['4']);
      expect(groupReleases(const []).isEmpty, isTrue);
    });

    test('formatFans is short and honest', () {
      expect(formatFans(1), '1 fan');
      expect(formatFans(900), '900 fans');
      expect(formatFans(12345), '12K fans');
      expect(formatFans(1234567), '1.2M fans');
      expect(formatFans(25000000), '25M fans');
    });

    test('recordTypeLabel maps the catalogue vocabulary', () {
      expect(recordTypeLabel('ep'), 'EP');
      expect(recordTypeLabel('compile'), 'Compilation');
      expect(recordTypeLabel('weird'), isNull);
    });
  });
}
