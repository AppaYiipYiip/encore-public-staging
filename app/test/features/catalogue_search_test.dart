import 'package:encore/core/result.dart';
import 'package:encore/data/catalogue/catalogue_models.dart';
import 'package:encore/data/requests/portal_client.dart';
import 'package:encore/features/requests/request_providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fake_catalogue.dart';
import '../support/test_app.dart';

class FakePortal implements RequestBackend {
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

const _swift = CatalogueResults(
  artists: [
    CatalogueArtist(id: '1', name: 'Taylor Swift', albumCount: 12),
  ],
  albums: [
    CatalogueAlbum(
      id: '10',
      title: 'Folklore',
      artistName: 'Taylor Swift',
      year: 2020,
      trackCount: 16,
    ),
  ],
  tracks: [
    CatalogueTrack(
      id: '100',
      title: 'Cardigan',
      artistName: 'Taylor Swift',
      albumTitle: 'Folklore',
      previewUrl: 'https://cdns-preview/cardigan.mp3',
    ),
  ],
);

void main() {
  setUpAll(loadAppFonts);

  Future<void> search(WidgetTester tester, String text) async {
    await tester.tap(find.text('Search').last);
    await settle(tester);
    await tester.enterText(find.byType(TextField), text);
    // 90 ms screen debounce + 350 ms catalogue debounce.
    await tester.pump(const Duration(milliseconds: 600));
    await settle(tester);
  }

  testWidgets('an artist the library does not have is never a dead end',
      (tester) async {
    final portal = FakePortal();
    final app = await pumpApp(tester, overrides: [
      catalogueClientProvider.overrideWithValue(FakeCatalogue(_swift)),
      requestBackendProvider.overrideWith((ref) async => portal),
    ]);

    await search(tester, 'Taylor Swift');

    expect(find.text('Not in your library yet'), findsOneWidget);
    expect(find.text('Taylor Swift'), findsWidgets);
    expect(find.text('Folklore'), findsOneWidget);
    expect(find.text('Cardigan'), findsOneWidget);
    expect(find.textContaining('No results'), findsNothing);

    await closeApp(tester, app.db);
  });

  testWidgets('Request sends it once and the chip says so', (tester) async {
    final portal = FakePortal();
    final app = await pumpApp(tester, overrides: [
      catalogueClientProvider.overrideWithValue(FakeCatalogue(_swift)),
      requestBackendProvider.overrideWith((ref) async => portal),
    ]);

    await search(tester, 'Taylor Swift');

    // The album's Request chip.
    final chips = find.text('Request');
    expect(chips, findsWidgets);
    await tester.tap(chips.at(1));
    await settle(tester);

    expect(portal.requests, contains('Taylor Swift|Folklore'));
    expect(find.text('Requested'), findsWidgets);

    await closeApp(tester, app.db);
  });

  testWidgets('tapping a song plays its preview', (tester) async {
    final app = await pumpApp(tester, overrides: [
      catalogueClientProvider.overrideWithValue(FakeCatalogue(_swift)),
      requestBackendProvider.overrideWith((ref) async => FakePortal()),
    ]);

    await search(tester, 'Taylor Swift');
    await tester.tap(find.text('Cardigan'));
    await settle(tester);

    expect(app.facade.calls, contains('preview(100)'));
    await closeApp(tester, app.db);
  });

  testWidgets('unrelated artists the catalogue pads the list with are dropped',
      (tester) async {
    final app = await pumpApp(tester, overrides: [
      catalogueClientProvider.overrideWithValue(FakeCatalogue(
        const CatalogueResults(
          artists: [
            CatalogueArtist(id: '1', name: 'Billie Eilish', albumCount: 32),
            CatalogueArtist(id: '2', name: 'Damian Marley', albumCount: 21),
            CatalogueArtist(
                id: '3', name: 'Billie Eilish & ROSALÍA', albumCount: 0),
          ],
        ),
      )),
      requestBackendProvider.overrideWith((ref) async => FakePortal()),
    ]);

    await search(tester, 'Billie Eilish');
    expect(find.text('Damian Marley'), findsNothing);
    expect(find.text('Billie Eilish & ROSALÍA'), findsOneWidget);
    expect(find.text('Artist - 32 releases'), findsOneWidget);
    expect(find.text('Artist'), findsOneWidget,
        reason: 'no "0 releases" noise for a zero-release artist');

    await closeApp(tester, app.db);
  });

  testWidgets(
      'of several artists with the name that was typed, the best known '
      'comes first (owner, Q5: the real Raid was the fifth hit, hidden)',
      (tester) async {
    // What the catalogue really answers for "raid" (fans in brackets): four
    // namesakes nobody listens to come before the one people mean.
    final app = await pumpApp(tester, overrides: [
      catalogueClientProvider.overrideWithValue(FakeCatalogue(
        const CatalogueResults(
          artists: [
            CatalogueArtist(id: '1', name: 'RAID!', fans: 4, albumCount: 1),
            CatalogueArtist(id: '2', name: 'RAID', fans: 40, albumCount: 2),
            CatalogueArtist(id: '3', name: 'R.A.I.D.', fans: 14, albumCount: 1),
            CatalogueArtist(id: '4', name: 'Raid', fans: 792, albumCount: 3),
            CatalogueArtist(id: '5', name: 'Raid', fans: 36096, albumCount: 9),
          ],
        ),
      )),
      requestBackendProvider.overrideWith((ref) async => FakePortal()),
    ]);

    await search(tester, 'raid');

    final best = find.textContaining('36K fans');
    final small = find.textContaining('792 fans');
    expect(best, findsOneWidget, reason: 'the real Raid is on the screen');
    expect(tester.getTopLeft(best).dy, lessThan(tester.getTopLeft(small).dy),
        reason: 'and above the namesake with 792 fans');
    await closeApp(tester, app.db);
  });

  testWidgets('the top hit survives even when the query was a typo',
      (tester) async {
    final app = await pumpApp(tester, overrides: [
      catalogueClientProvider.overrideWithValue(FakeCatalogue(
        const CatalogueResults(
          artists: [
            CatalogueArtist(id: '1', name: 'Billie Eilish', albumCount: 32),
          ],
        ),
      )),
      requestBackendProvider.overrideWith((ref) async => FakePortal()),
    ]);

    await search(tester, 'bilie eilsh');
    expect(find.text('Billie Eilish'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets('owned music is not offered again', (tester) async {
    final app = await pumpApp(tester, overrides: [
      catalogueClientProvider.overrideWithValue(FakeCatalogue(
        const CatalogueResults(
          albums: [
            CatalogueAlbum(id: '1', title: 'The Walk', artistName: 'Periphery'),
          ],
        ),
      )),
      requestBackendProvider.overrideWith((ref) async => FakePortal()),
    ]);

    await search(tester, 'The Walk');
    expect(find.text('Not in your library yet'), findsNothing);

    await closeApp(tester, app.db);
  });
}
