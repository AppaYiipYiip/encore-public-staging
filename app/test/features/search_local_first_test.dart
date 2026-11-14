import 'package:drift/drift.dart' show Value;
import 'package:encore/data/catalogue/catalogue_models.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/features/requests/request_providers.dart'
    show catalogueClientProvider;
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fake_catalogue.dart';
import '../support/test_app.dart';

/// P1-07 (owner, 14 Nov 2026, an emulator under load): after typing in Search nothing at all was drawn for about 35 s, then everything
/// came at once, although the phone's own index held the answer. Offline the same screen was instant.
///
/// The rule these tests hold: **what the library answers is drawn as soon as the library has answered, whatever the catalogue (Deezer,
/// over the line) is doing; the catalogue's rows are added when they arrive and take nothing away.** A stranger on a slow line must not
/// look at an empty page for as long as the catalogue takes; offline is only the case in which the catalogue fails at once.
void main() {
  setUpAll(loadAppFonts);

  /// An artist of the library with one song (the library lists an artist only when it has something).
  Future<void> addArtist(AppDatabase db, int serverId, String id, String name,
      {required String song}) async {
    await db.into(db.artists).insert(ArtistsCompanion.insert(
        serverId: serverId, id: id, name: name, albumCount: const Value(1)));
    await db.into(db.tracks).insert(TracksCompanion.insert(
          serverId: serverId,
          id: '$id-t1',
          title: song,
          artistId: Value(id),
          artist: Value(name),
        ));
  }

  /// Types [text] and lets the 90 ms of the screen's debounce go by, nothing more: the catalogue's own 350 ms debounce is still running
  /// after this, and the caller decides how much time passes.
  Future<void> type(WidgetTester tester, String text) async {
    await tester.tap(find.text('Search').last);
    await settle(tester);
    await tester.enterText(find.byType(TextField), text);
    await tester.pump(const Duration(milliseconds: 90));
  }

  final topCard = find.byKey(const Key('top-result'));

  /// What the library answered for "eminem", as a stranger sees it: the artist on top and its song in the list.
  void expectLibraryRows() {
    expect(topCard, findsOneWidget, reason: 'the Top result is drawn');
    expect(find.descendant(of: topCard, matching: find.text('Eminem')),
        findsOneWidget);
    expect(
        find.descendant(of: topCard, matching: find.textContaining('Artist')),
        findsOneWidget);
    expect(find.text('Lose Yourself'), findsOneWidget,
        reason: 'the library\'s song is a row');
    expect(find.byType(CircularProgressIndicator), findsNothing,
        reason: 'a page that has rows is not a page that is loading');
  }

  testWidgets(
      'the library\'s answer is on screen while the catalogue has not answered at all',
      (tester) async {
    final catalogue = FakeCatalogue.slow();
    final app = await pumpApp(tester, overrides: [
      catalogueClientProvider.overrideWithValue(catalogue),
    ]);
    await addArtist(app.db, app.serverId, 'ar-eminem', 'Eminem',
        song: 'Lose Yourself');

    await type(tester, 'eminem');
    // One second of the line doing nothing: the catalogue's debounce (350 ms) has passed and the question is out.
    await tester.pump(const Duration(milliseconds: 1000));

    expect(catalogue.searches, 1,
        reason: 'the catalogue was asked and is still not answering');
    expectLibraryRows();

    await closeApp(tester, app.db);
  });

  testWidgets(
      'a catalogue that answers late adds its rows and takes none of the library\'s away',
      (tester) async {
    final catalogue = FakeCatalogue.slow(const CatalogueResults(
      artists: [
        CatalogueArtist(
            id: 'dz-eminem', name: 'Eminem', fans: 20000000, albumCount: 40)
      ],
      tracks: [
        CatalogueTrack(id: 'dz-wm', title: 'Without Me', artistName: 'Eminem')
      ],
      ownedArtists: {'dz-eminem': 'ar-eminem'},
    ));
    final app = await pumpApp(tester, overrides: [
      catalogueClientProvider.overrideWithValue(catalogue),
    ]);
    await addArtist(app.db, app.serverId, 'ar-eminem', 'Eminem',
        song: 'Lose Yourself');

    await type(tester, 'eminem');
    await tester.pump(const Duration(milliseconds: 1000));
    expectLibraryRows();
    expect(find.text('Without Me'), findsNothing,
        reason: 'the catalogue has not answered yet');

    catalogue.answerSearches();

    // Frame by frame while the answer arrives and the rows are worked out again: the library's rows are on screen in every one of them.
    for (var frame = 0; frame < 12; frame++) {
      await tester.pump(const Duration(milliseconds: 50));
      expectLibraryRows();
    }
    expect(find.text('Without Me'), findsOneWidget,
        reason: 'the catalogue\'s song joined the list');

    await closeApp(tester, app.db);
  });
}
