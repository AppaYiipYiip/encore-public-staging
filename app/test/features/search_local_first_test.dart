import 'dart:async';

import 'package:drift/drift.dart'
    show ApplyInterceptor, QueryExecutor, QueryInterceptor, Value;
import 'package:drift/native.dart';
import 'package:encore/app/providers.dart' show databaseProvider;
import 'package:encore/data/api/opensubsonic/models.dart';
import 'package:encore/data/catalogue/catalogue_models.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/sync/library_writer.dart';
import 'package:encore/features/providers.dart' show artistsProvider;
import 'package:encore/features/requests/request_providers.dart'
    show catalogueClientProvider;
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
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

  testWidgets(
      'the typo guess still joins when the list of artists arrives after the answer, and stays when it arrives again',
      (tester) async {
    // The list of artists is held back by the test: the search must answer without it, then take it in when it comes.
    final list = StreamController<List<ArtistRow>>();
    addTearDown(list.close);
    final app = await pumpApp(tester, overrides: [
      catalogueClientProvider.overrideWithValue(FakeCatalogue.slow()),
      artistsProvider.overrideWith((ref) => list.stream),
    ]);
    await addArtist(app.db, app.serverId, 'ar-landmvrks', 'Landmvrks',
        song: 'A Song');
    final landmvrks = await (app.db.select(app.db.artists)
          ..where((a) => a.id.equals('ar-landmvrks')))
        .getSingle();

    await type(tester, 'landmarks');
    await tester.pump(const Duration(milliseconds: 1000));
    expect(topCard, findsNothing, reason: 'nothing answers "landmarks" yet');

    list.add([landmvrks]);
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.descendant(of: topCard, matching: find.text('Landmvrks')),
        findsOneWidget,
        reason: 'the list arrived: the band one letter off is the guess');

    // The same list again and again (a sync writing): the guess stays, in every frame.
    for (var i = 0; i < 10; i++) {
      list.add([landmvrks]);
      await tester.pump(const Duration(milliseconds: 100));
      expect(find.descendant(of: topCard, matching: find.text('Landmvrks')),
          findsOneWidget);
    }

    await closeApp(tester, app.db);
  });

  group('while the library is being written to (a sync, a download)', () {
    /// One page of a sync, written the way the sync engine writes it ([LibraryWriter]).
    Future<void> write(AppDatabase db, int serverId, int i, _Write what) async {
      switch (what) {
        case _Write.song:
          // A song of an artist the library has: the list of artists arrives again with the same names.
          await LibraryWriter(db).upsertTracks(serverId, 1, [
            SsSong(
                id: 'sync-t-$i',
                title: 'Song $i',
                artistId: 'ar1',
                artist: 'Alcest'),
          ]);
        case _Write.songOfNewArtist:
          // The list of artists really changes.
          await LibraryWriter(db).upsertArtists(serverId, 1,
              [SsArtist(id: 'sync-ar-$i', name: 'Band $i', albumCount: 1)]);
          await LibraryWriter(db).upsertTracks(serverId, 1, [
            SsSong(
                id: 'sync-t-$i',
                title: 'Song $i',
                artistId: 'sync-ar-$i',
                artist: 'Band $i'),
          ]);
        case _Write.serverRow:
          await (db.update(db.servers)..where((t) => t.id.equals(serverId)))
              .write(ServersCompanion(name: Value('Home server $i')));
        case _Write.nothing:
      }
    }

    /// Searches "eminem" while one page of [what] is written every 100 ms for three seconds. [readTime] is how long one read of the
    /// database takes (a phone that is busy; zero is a database that answers at once).
    ///
    /// The rows must be on screen within a second of typing, and once there, in every frame.
    Future<void> searchWhileWriting(WidgetTester tester, _Write what,
        {Duration readTime = Duration.zero}) async {
      final reads = _SlowReads();
      final db = AppDatabase(NativeDatabase.memory().interceptWith(reads));
      final serverId = await Seed.library(db);
      final app = await pumpApp(tester, seeded: false, overrides: [
        databaseProvider.overrideWithValue(db),
        catalogueClientProvider.overrideWithValue(FakeCatalogue.slow()),
      ]);
      await addArtist(db, serverId, 'ar-eminem', 'Eminem',
          song: 'Lose Yourself');

      // The artists' list is what a write of songs re-sends: count it, so that the test shows the writes really reach the search.
      final container = ProviderScope.containerOf(
          tester.element(find.byType(Scaffold).first));
      var artistLists = 0;
      container.listen(artistsProvider, (_, __) => artistLists++);

      await tester.tap(find.text('Search').last);
      await settle(tester);
      reads.delay = readTime;
      await tester.enterText(find.byType(TextField), 'eminem');
      await tester.pump(const Duration(milliseconds: 90));

      // The pages are not awaited: on a busy phone the writer's own reads take their time too, and time only passes in `pump`.
      final pages = <Future<void>>[];
      int? shownAt;
      for (var step = 1; step <= 30; step++) {
        pages.add(write(db, serverId, step, what));
        await tester.pump(const Duration(milliseconds: 100));
        final shown = topCard.evaluate().isNotEmpty &&
            find.text('Lose Yourself').evaluate().isNotEmpty;
        if (shown) shownAt ??= step;
        if (shownAt != null) expectLibraryRows();
      }

      if (what == _Write.song || what == _Write.songOfNewArtist) {
        expect(artistLists, greaterThan(10),
            reason: 'the writes really made the list of artists arrive again');
      }
      expect(shownAt, isNotNull,
          reason: 'the rows of the library were not drawn during three '
              'seconds of writing');
      expect(shownAt!, lessThanOrEqualTo(10),
          reason: 'within about a second of typing (the pages are 100 ms '
              'apart), not when the writing stopped');

      reads.delay = Duration.zero;
      await tester.pump(const Duration(seconds: 2));
      await Future.wait(pages);
      await closeApp(tester, db);
      await app.db.close();
    }

    const busy = Duration(milliseconds: 40);

    testWidgets('a song written every 100 ms', (tester) async {
      await searchWhileWriting(tester, _Write.song);
    });

    testWidgets('a song of a new artist written every 100 ms', (tester) async {
      await searchWhileWriting(tester, _Write.songOfNewArtist);
    });

    // A phone that is busy takes time over every read; then a search lasts longer than the pause between two writes, and a search that
    // starts over at each write never finishes (found 14 Nov 2026: 30 starts in 3 s, 30 abandoned).
    testWidgets(
        'control, a busy phone (every read takes 40 ms), nothing written',
        (tester) async {
      await searchWhileWriting(tester, _Write.nothing, readTime: busy);
    });

    testWidgets('a busy phone, a song written every 100 ms', (tester) async {
      await searchWhileWriting(tester, _Write.song, readTime: busy);
    });

    testWidgets('a busy phone, a song of a new artist written every 100 ms',
        (tester) async {
      await searchWhileWriting(tester, _Write.songOfNewArtist, readTime: busy);
    });

    testWidgets('a busy phone, the server\'s own row rewritten every 100 ms',
        (tester) async {
      await searchWhileWriting(tester, _Write.serverRow, readTime: busy);
    });
  });
}

/// What a sync or a download writes, one page every 100 ms.
enum _Write { song, songOfNewArtist, serverRow, nothing }

/// A phone that is busy: once [delay] is set, every read of the database takes that long (in the test's own time). Writes are not slowed.
class _SlowReads extends QueryInterceptor {
  Duration delay = Duration.zero;

  @override
  Future<List<Map<String, Object?>>> runSelect(
      QueryExecutor executor, String statement, List<Object?> args) async {
    if (delay > Duration.zero) await Future<void>.delayed(delay);
    return executor.runSelect(statement, args);
  }
}
