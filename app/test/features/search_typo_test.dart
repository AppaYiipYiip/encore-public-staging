import 'package:drift/drift.dart' show Value;
import 'package:encore/data/catalogue/catalogue_models.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/features/providers.dart' show SearchResults;
import 'package:encore/features/requests/request_providers.dart'
    show catalogueClientProvider;
import 'package:encore/features/search/search_assembly.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/factories.dart';
import '../support/fake_catalogue.dart';
import '../support/test_app.dart';

/// N-23 (owner, 13 Nov 2026): typing "landmarks" must find the band "Landmvrks" in the library, offline.
///
/// The rule these tests hold: **when no artist of the library has a name that begins with the typed words, an artist whose name is
/// one letter off (two from 9 letters on) is found and scored below every exact or prefix answer** (`artistMatch`,
/// `lib/domain/artist_typo.dart`). The library's own text search cannot do it: it only matches the start of words.
void main() {
  setUpAll(loadAppFonts);

  ArtistRow artist(String id, String name) => ArtistRow(
      serverId: 1,
      id: id,
      name: name,
      albumCount: 1,
      fingerprint: 'f',
      syncRun: 1);

  String top(AssembledSearch page) => switch (page.top) {
        final SongHit s => 'song: ${s.artist} - ${s.title}',
        final ArtistHit a => 'artist: ${a.name}',
        final AlbumHit a => 'album: ${a.title}',
        null => 'nothing',
      };

  group('where a guessed artist stands among the answers', () {
    test('it is the Top result when nothing answers better', () {
      final page = assembleSearch('landmarks',
          local: SearchResults(artists: [artist('1', 'Landmvrks')]));

      expect(top(page), 'artist: Landmvrks');
    });

    test('an exact title of the library is a better answer than a guess', () {
      final page = assembleSearch('landmarks',
          local: SearchResults(
            artists: [artist('1', 'Landmvrks')],
            tracks: [trackRow('t', title: 'Landmarks', artist: 'Someone Else')],
          ));

      expect(top(page), 'song: Someone Else - Landmarks');
      expect([for (final a in page.artists) a.name], ['Landmvrks'],
          reason: 'the guess is still listed, below');
    });

    test('an artist the library has that the catalogue spells right is one row',
        () {
      const catalogue = CatalogueResults(
        artists: [
          CatalogueArtist(
              id: 'dz1', name: 'Landmvrks', fans: 90000, albumCount: 8)
        ],
        ownedArtists: {'dz1': '1'},
      );
      final page = assembleSearch('landmarks',
          local: SearchResults(artists: [artist('1', 'Landmvrks')]),
          catalogue: catalogue);

      final hit = page.top as ArtistHit;
      expect(hit.local?.id, '1', reason: 'the row of the library is attached');
      expect(hit.catalogue?.fans, 90000);
      expect(page.artists, isEmpty, reason: 'one row, not two');
    });
  });

  Future<void> search(WidgetTester tester, String text) async {
    await tester.tap(find.text('Search').last);
    await settle(tester);
    await tester.enterText(find.byType(TextField), text);
    // 90 ms screen debounce + 350 ms catalogue debounce.
    await tester.pump(const Duration(milliseconds: 600));
    await settle(tester);
  }

  /// An artist of the library with one song (the library lists an artist only when it has something).
  Future<void> addArtist(AppDatabase db, int serverId, String id, String name,
      {String song = 'A Song'}) async {
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

  testWidgets('"landmarks" finds the band "Landmvrks" and puts it on top',
      (tester) async {
    final app = await pumpApp(tester, overrides: [
      catalogueClientProvider
          .overrideWithValue(FakeCatalogue(CatalogueResults.empty)),
    ]);
    await addArtist(app.db, app.serverId, 'ar-landmvrks', 'Landmvrks');

    await search(tester, 'landmarks');

    final card = find.byKey(const Key('top-result'));
    expect(card, findsOneWidget, reason: 'the band is the Top result');
    expect(find.descendant(of: card, matching: find.text('Landmvrks')),
        findsOneWidget);
    expect(find.descendant(of: card, matching: find.textContaining('Artist')),
        findsOneWidget);

    await closeApp(tester, app.db);
  });

  testWidgets('two letters wrong in a long name still find it', (tester) async {
    final app = await pumpApp(tester, overrides: [
      catalogueClientProvider
          .overrideWithValue(FakeCatalogue(CatalogueResults.empty)),
    ]);
    await addArtist(app.db, app.serverId, 'ar-be', 'Billie Eilish');

    await search(tester, 'bilie eilsh');

    final card = find.byKey(const Key('top-result'));
    expect(find.descendant(of: card, matching: find.text('Billie Eilish')),
        findsOneWidget);

    await closeApp(tester, app.db);
  });

  testWidgets('an artist that begins with the words is an answer: no guessing',
      (tester) async {
    final app = await pumpApp(tester, overrides: [
      catalogueClientProvider
          .overrideWithValue(FakeCatalogue(CatalogueResults.empty)),
    ]);
    await addArtist(app.db, app.serverId, 'ar-landmvrks', 'Landmvrks');
    await addArtist(app.db, app.serverId, 'ar-band', 'Landmarks Band');

    await search(tester, 'landmarks');

    final card = find.byKey(const Key('top-result'));
    expect(find.descendant(of: card, matching: find.text('Landmarks Band')),
        findsOneWidget);
    expect(find.text('Landmvrks'), findsNothing,
        reason: 'a prefix answer exists, so a name that is merely close is '
            'not looked for');

    await closeApp(tester, app.db);
  });

  testWidgets('a name of four letters is never guessed', (tester) async {
    final app = await pumpApp(tester, overrides: [
      catalogueClientProvider
          .overrideWithValue(FakeCatalogue(CatalogueResults.empty)),
    ]);
    await addArtist(app.db, app.serverId, 'ar-muse', 'Muse');

    await search(tester, 'mose');

    expect(find.text('Muse'), findsNothing);

    await closeApp(tester, app.db);
  });
}
