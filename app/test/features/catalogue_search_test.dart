import 'package:encore/core/result.dart';
import 'package:encore/data/catalogue/catalogue_models.dart';
import 'package:encore/data/requests/portal_client.dart';
import 'package:encore/features/instant/tap_play.dart' show kPlainServerLine;
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

    expect(find.text('Top result'), findsOneWidget);
    expect(find.text('Not in your library yet'), findsNothing,
        reason: 'whether the library has it is never a header');
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

  testWidgets(
      'on a server that only plays what it has, tapping a song says so and plays nothing',
      (tester) async {
    final app = await pumpApp(tester, overrides: [
      catalogueClientProvider.overrideWithValue(FakeCatalogue(_swift)),
      requestBackendProvider.overrideWith((ref) async => FakePortal()),
    ]);

    await search(tester, 'Taylor Swift');
    await tester.tap(find.text('Cardigan'));
    await settle(tester);

    expect(find.text(kPlainServerLine), findsOneWidget);
    expect(app.facade.calls.where((c) => c.startsWith('streamed')), isEmpty);
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
    expect(
        find.descendant(
            of: find.byKey(const Key('top-result')),
            matching: find.text('Billie Eilish')),
        findsOneWidget,
        reason: 'the artist who was typed is the Top result');
    // The Top result's line and the collaboration's row both say just "Artist": no "0 releases" noise.
    expect(find.text('Artist'), findsNWidgets(2));

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
    expect(
        find.descendant(
            of: find.byKey(const Key('top-result')),
            matching: find.text('The Walk')),
        findsOneWidget,
        reason: 'the library has it: it is the Top result');
    expect(find.text('Albums'), findsNothing,
        reason: 'and the catalogue copy is not offered a second time');

    await closeApp(tester, app.db);
  });

  testWidgets(
      'the song that was typed is the Top result, with no header about the library',
      (tester) async {
    final app = await pumpApp(tester, overrides: [
      catalogueClientProvider.overrideWithValue(FakeCatalogue(_swift)),
      requestBackendProvider.overrideWith((ref) async => FakePortal()),
    ]);

    await search(tester, 'taylor swift cardigan');

    expect(find.text('Top result'), findsOneWidget);
    expect(find.text('Cardigan'), findsOneWidget,
        reason: 'on top, and not listed a second time below it');
    expect(find.text('Not in your library yet'), findsNothing);
    expect(find.textContaining('added to your library first'), findsNothing);

    await tester.tap(find.byKey(const Key('top-result')));
    await settle(tester);
    expect(find.text(kPlainServerLine), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'a song the library has is the Top result too, and the catalogue copy is not listed',
      (tester) async {
    final app = await pumpApp(tester, overrides: [
      catalogueClientProvider.overrideWithValue(FakeCatalogue(
        const CatalogueResults(
          tracks: [
            CatalogueTrack(
                id: '9',
                title: 'Opening Kodama',
                artistName: 'Alcest',
                albumTitle: 'Kodama'),
          ],
        ),
      )),
      requestBackendProvider.overrideWith((ref) async => FakePortal()),
    ]);

    await search(tester, 'alcest opening kodama');

    expect(find.text('Top result'), findsOneWidget);
    expect(find.text('Opening Kodama'), findsOneWidget,
        reason: 'the library has it: one row, not two');
    await closeApp(tester, app.db);
  });

  testWidgets(
      'what the library has and what it has not are mixed in one list of songs',
      (tester) async {
    final app = await pumpApp(tester, overrides: [
      catalogueClientProvider.overrideWithValue(FakeCatalogue(
        const CatalogueResults(
          tracks: [
            CatalogueTrack(
                id: '1', title: 'Echoes of Spring', artistName: 'Somebody'),
            CatalogueTrack(
                id: '2', title: 'Echoes Return', artistName: 'Somebody Else'),
          ],
        ),
      )),
      requestBackendProvider.overrideWith((ref) async => FakePortal()),
    ]);

    await search(tester, 'echoes');

    expect(find.text('Songs'), findsOneWidget, reason: 'one list');
    expect(find.text('Echoes Kodama'), findsOneWidget,
        reason: 'from the library');
    expect(find.text('Echoes of Spring'), findsOneWidget,
        reason: 'from the catalogue');
    expect(find.text('Not in your library yet'), findsNothing);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'a barely known artist with the name of a song does not take the Top result',
      (tester) async {
    final app = await pumpApp(tester, overrides: [
      catalogueClientProvider.overrideWithValue(FakeCatalogue(
        const CatalogueResults(
          artists: [
            CatalogueArtist(
                id: '1', name: 'Hotel California', fans: 7812, albumCount: 1),
          ],
          tracks: [
            CatalogueTrack(
                id: '2',
                title: 'Hotel California',
                artistName: 'Eagles',
                albumTitle: 'Hotel California'),
          ],
        ),
      )),
      requestBackendProvider.overrideWith((ref) async => FakePortal()),
    ]);

    await search(tester, 'hotel california');

    final top = find.byKey(const Key('top-result'));
    expect(find.descendant(of: top, matching: find.textContaining('Eagles')),
        findsOneWidget,
        reason: 'the song by Eagles is on top, not the artist with 7,812 fans');
    await closeApp(tester, app.db);
  });
}
