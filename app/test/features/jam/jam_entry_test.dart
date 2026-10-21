import 'dart:async';

import 'package:encore/core/result.dart';
import 'package:encore/data/catalogue/catalogue_models.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/features/jam/jam_providers.dart';
import 'package:encore/features/jam/jam_speaker.dart';
import 'package:encore/features/jam/jam_wiring.dart';
import 'package:encore/features/requests/request_providers.dart';
import 'package:encore_session/encore_session.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import '../../support/fake_catalogue.dart';
import '../../support/fake_jam_api.dart';
import '../../support/test_app.dart';

class _AlwaysPlays implements JamSongPlayer {
  @override
  Future<bool> play(QueueEntry entry) async => true;

  @override
  bool alreadyPlaying(QueueEntry entry) => false;

  @override
  Future<void> preload(QueueEntry entry) async {}
}

/// How a person finds Jam (the owner: "I looked at the entirety of the app, I
/// still do not know how to make a jam session, I do not know where to look or
/// press") and how they put songs in it.
void main() {
  setUpAll(loadAppFonts);

  late FakeJamApi api;

  Future<AppDatabase> open(WidgetTester tester,
      {List<CatalogueTrack> catalogue = const []}) async {
    api = FakeJamApi();
    final app = await pumpApp(tester, size: const Size(390, 1800), overrides: [
      jamApiProvider.overrideWith((ref) async => api),
      jamBackoffProvider.overrideWithValue(const [Duration(milliseconds: 1)]),
      jamClockEveryProvider.overrideWithValue(const Duration(days: 1)),
      jamSongPlayerProvider.overrideWithValue(_AlwaysPlays()),
      catalogueClientProvider.overrideWithValue(
          FakeCatalogue(CatalogueResults(tracks: catalogue))),
    ]);
    return app.db;
  }

  Future<void> startJam(WidgetTester tester) async {
    final element = tester.element(find.byType(Scaffold).first);
    unawaited(GoRouter.of(element).push<void>('/home/jam'));
    await settle(tester);
    await tester.tap(find.text('Start a Jam'));
    await settle(tester);
  }

  Future<void> search(WidgetTester tester, String text) async {
    await tester.tap(find.text('Add songs'));
    await settle(tester);
    await tester.enterText(
        find.widgetWithText(TextField, 'Search songs'), text);
    await tester
        .pump(const Duration(milliseconds: 400)); // the person stops typing
    await settle(tester);
  }

  testWidgets('Home has a Jam button, and it opens the Jam screen',
      (tester) async {
    final db = await open(tester);

    expect(find.text('Jam'), findsOneWidget);
    await tester.tap(find.text('Jam'));
    await settle(tester);

    expect(find.text('Listen together'), findsOneWidget);
    await closeApp(tester, db);
  });

  group('adding songs', () {
    testWidgets(
        'a song from the library goes in with what it is, not just an id',
        (tester) async {
      final db = await open(tester);
      await startJam(tester);

      api.commandAnswer = Result.ok(FakeJamApi.alone('owner', rev: 9));
      await search(tester, 'Echoes Ghost');
      expect(find.text('In your library'), findsOneWidget);
      await tester.tap(find.widgetWithText(ListTile, 'Echoes Ghost'));
      await settle(tester);

      final added = api.commands.last.$2 as Add;
      expect(added.trackId, 'al4-t2');
      expect(added.title, 'Echoes Ghost');
      expect(added.artist, 'Opeth');
      expect(added.album, 'Ghost Reveries');
      expect(find.byIcon(Icons.check_rounded), findsOneWidget,
          reason: 'the row says it is in');
      await closeApp(tester, db);
    });

    testWidgets('a song the library does not have is added by name',
        (tester) async {
      final db = await open(tester, catalogue: const [
        CatalogueTrack(
          id: 'dz-77',
          title: 'Sommaire',
          artistName: 'Raid',
          artistId: '4242',
          albumTitle: 'Lmorphine',
          coverUrl: 'https://cdn/lmorphine.jpg',
          duration: Duration(minutes: 3, seconds: 20),
        ),
      ]);
      await startJam(tester);

      await search(tester, 'Sommaire');
      expect(find.text('Not in your library yet'), findsOneWidget);
      await tester.tap(find.widgetWithText(ListTile, 'Sommaire'));
      await settle(tester);

      final added = api.commands.last.$2 as Add;
      expect(added.trackId, 'cat:dz-77');
      expect((added.title, added.artist, added.album),
          ('Sommaire', 'Raid', 'Lmorphine'));
      expect((
        added.artistRef,
        added.imageUrl,
        added.durationSec
      ), (
        '4242',
        'https://cdn/lmorphine.jpg',
        200
      ), reason: 'so every phone can show it and open the artist');
      await closeApp(tester, db);
    });

    testWidgets('when the Jam refuses, the row is not left looking added',
        (tester) async {
      final db = await open(tester);
      await startJam(tester);
      api.commandAnswer = const Result.err(ServerFailure('the queue is full'));

      await search(tester, 'Echoes Ghost');
      await tester.tap(find.widgetWithText(ListTile, 'Echoes Ghost'));
      await settle(tester);

      expect(find.byIcon(Icons.check_rounded), findsNothing);
      expect(find.byIcon(Icons.add_circle_outline_rounded), findsWidgets);
      await closeApp(tester, db);
    });

    testWidgets('searching for nothing found says so', (tester) async {
      final db = await open(tester);
      await startJam(tester);

      await search(tester, 'qqzzxx');

      expect(find.textContaining('No songs found'), findsOneWidget);
      await closeApp(tester, db);
    });
  });
}
