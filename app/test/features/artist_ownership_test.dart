import 'package:encore/core/result.dart';
import 'package:encore/data/catalogue/catalogue_models.dart';
import 'package:encore/data/requests/portal_client.dart';
import 'package:encore/features/requests/request_providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import '../support/fake_catalogue.dart';
import '../support/test_app.dart';

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

/// The seeded library has Opeth with two albums (Ghost Reveries, Blackwater
/// Park). The catalogue knows two artists called Opeth: the real one with a
/// long discography and a tiny namesake.
FakeCatalogue _catalogue() {
  final c = FakeCatalogue(const CatalogueResults(
    artists: [
      CatalogueArtist(id: 'o1', name: 'Opeth', fans: 1200000, albumCount: 14),
      CatalogueArtist(id: 'o2', name: 'Opeth', fans: 310, albumCount: 1),
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
    CatalogueAlbum(
        id: 'a3',
        title: 'Damnation',
        artistName: 'Opeth',
        year: 2003,
        recordType: 'album'),
    CatalogueAlbum(
        id: 'a4',
        title: 'Deliverance',
        artistName: 'Opeth',
        year: 2002,
        recordType: 'album'),
  ];
  c.albumsByArtist['o2'] = const [
    CatalogueAlbum(
        id: 'b1', title: 'Garage Demo', artistName: 'Opeth', year: 2019),
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

  testWidgets('an artist the library has is kept, marked and shows its fans',
      (tester) async {
    final app = await pumpApp(
      tester,
      size: const Size(390, 1800),
      overrides: [
        catalogueClientProvider.overrideWithValue(_catalogue()),
        requestBackendProvider.overrideWith((ref) async => _Portal()),
      ],
    );

    await search(tester, 'opeth');

    // The well-known Opeth is the library's and is the Top result, with the catalogue's fans; the namesake is a stranger.
    final top = find.byKey(const Key('top-result'));
    expect(
        find.descendant(of: top, matching: find.text('Opeth')), findsOneWidget);
    expect(find.descendant(of: top, matching: find.textContaining('1.2M fans')),
        findsOneWidget);
    expect(find.text('Artist - 310 fans - 1 release'), findsOneWidget);
    expect(find.text('Request'), findsWidgets);
    await closeApp(tester, app.db);
  });

  testWidgets('the library artist page lists what the library lacks',
      (tester) async {
    final app = await pumpApp(
      tester,
      size: const Size(390, 2200),
      overrides: [
        catalogueClientProvider.overrideWithValue(_catalogue()),
        requestBackendProvider.overrideWith((ref) async => _Portal()),
      ],
    );

    final element = tester.element(find.byType(Scaffold).first);
    GoRouter.of(element).go('/library/artist/ar3');
    await settle(tester);
    await tester.pump(const Duration(seconds: 1));
    await settle(tester);

    expect(find.text('Discography'), findsOneWidget);
    expect(find.text('More from Opeth'), findsOneWidget);
    expect(
        find.textContaining('2 releases not in your library'), findsOneWidget);
    expect(find.text('Damnation'), findsOneWidget);
    expect(find.text('Deliverance'), findsOneWidget);
    // Owned releases are in the grid above, not offered again.
    expect(find.text('Garage Demo'), findsNothing,
        reason: 'the namesake is not this artist');
    expect(find.textContaining('1.2M fans'), findsOneWidget);
    // What the artist made next to what the library holds: not "2 albums",
    // which made a band with four look like one with two.
    expect(find.textContaining('2 of 4 albums on your server'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets('with no network the artist page is just the library',
      (tester) async {
    final app = await pumpApp(tester, overrides: [
      catalogueClientProvider.overrideWithValue(FakeCatalogue()),
      requestBackendProvider.overrideWith((ref) async => _Portal()),
    ]);
    final element = tester.element(find.byType(Scaffold).first);
    GoRouter.of(element).go('/library/artist/ar3');
    await settle(tester);

    expect(find.text('Discography'), findsOneWidget);
    expect(find.textContaining('More from'), findsNothing);
    await closeApp(tester, app.db);
  });
}
