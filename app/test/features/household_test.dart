import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:encore/app/providers.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/sync/sync_scheduler.dart';
import 'package:encore/domain/household.dart';
import 'package:encore/features/settings/settings_controller.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../support/test_app.dart';

/// A server shared by a household (ADR-049): Home and Your Library open on
/// this account's music; everyone else's is one tap away, not in the face.
void main() {
  setUpAll(loadAppFonts);
  setUp(() => SharedPreferences.setMockInitialValues({}));

  const tall = Size(390, 2600);

  /// Other people's music on the same server: a stranger's album (newest on
  /// the server), a fresh album by an artist this account plays, and two
  /// playlists owned by "sara".
  Future<void> addHousehold(AppDatabase db, int serverId) async {
    await db.into(db.artists).insert(ArtistsCompanion.insert(
        serverId: serverId, id: 'ar9', name: 'Strangers'));
    await db.into(db.albums).insert(AlbumsCompanion.insert(
          serverId: serverId,
          id: 'al9',
          name: 'Other People Music',
          artistId: const Value('ar9'),
          artist: const Value('Strangers'),
          songCount: const Value(1),
          createdAtMs: const Value(1800000000000),
        ));
    await db.into(db.tracks).insert(TracksCompanion.insert(
          serverId: serverId,
          id: 'al9-t1',
          title: 'Not For Me',
          albumId: const Value('al9'),
          artistId: const Value('ar9'),
          album: const Value('Other People Music'),
          artist: const Value('Strangers'),
        ));
    await db.into(db.albums).insert(AlbumsCompanion.insert(
          serverId: serverId,
          id: 'al8',
          name: 'Fresh Alcest',
          artistId: const Value('ar1'),
          artist: const Value('Alcest'),
          songCount: const Value(1),
          createdAtMs: const Value(1800000001000),
        ));
    await db.into(db.tracks).insert(TracksCompanion.insert(
          serverId: serverId,
          id: 'al8-t1',
          title: 'Just Dropped',
          albumId: const Value('al8'),
          artistId: const Value('ar1'),
          album: const Value('Fresh Alcest'),
          artist: const Value('Alcest'),
        ));
    for (final (id, name, smart) in const [
      ('pl9', 'Sara road trip', false),
      ('pl10', 'Sara favourites', true),
    ]) {
      await db.into(db.playlists).insert(PlaylistsCompanion.insert(
            serverId: serverId,
            id: id,
            name: name,
            owner: const Value('sara'),
            isPublic: const Value(true),
            readonly: Value(smart),
            songCount: const Value(1),
            changedAtMs: const Value(1700000000000),
            entriesFetchedAtMs: const Value(1700000000000),
          ));
    }
  }

  Future<void> openRoute(WidgetTester tester, String location) async {
    final element = tester.element(find.byType(Scaffold).first);
    GoRouter.of(element).go(location);
    await settle(tester);
  }

  ProviderContainer containerOf(WidgetTester tester) =>
      ProviderScope.containerOf(tester.element(find.byType(Scaffold).first));

  group('Home', () {
    testWidgets('other people\'s playlists never appear', (tester) async {
      final app = await pumpApp(tester, size: tall);
      await addHousehold(app.db, app.serverId);
      await settle(tester);

      expect(find.text('Prog Snob'), findsWidgets, reason: 'mine is there');
      expect(find.text('Sara road trip'), findsNothing);
      expect(find.text('Sara favourites'), findsNothing,
          reason: 'her generated playlist is not "made for" this account');
      await closeApp(tester, app.db);
    });

    testWidgets('new music is split: from my artists, and from everyone',
        (tester) async {
      final app = await pumpApp(tester, size: tall);
      await addHousehold(app.db, app.serverId);
      await settle(tester);
      await tester.pump(const Duration(milliseconds: 200));

      expect(find.text('New from artists you play'), findsOneWidget);
      expect(find.text('Fresh Alcest'), findsOneWidget);
      expect(find.text('New on the server'), findsOneWidget);
      expect(find.text('Other People Music'), findsOneWidget,
          reason: 'once - in its shelf, not in the quick-access grid');
      await closeApp(tester, app.db);
    });

    testWidgets('"New on the server" can be switched off', (tester) async {
      final app = await pumpApp(tester, size: tall);
      await addHousehold(app.db, app.serverId);
      await settle(tester);
      containerOf(tester)
          .read(settingsProvider.notifier)
          .setShowNewOnServer(false);
      await settle(tester);

      expect(find.text('New on the server'), findsNothing);
      expect(find.text('Other People Music'), findsNothing);
      expect(find.text('Fresh Alcest'), findsOneWidget,
          reason: 'releases from artists I play always show');
      await closeApp(tester, app.db);
    });
  });

  group('Your Library', () {
    testWidgets(
        'opens on my music with nothing chosen, however little there is',
        (tester) async {
      final app = await pumpApp(tester, size: tall);
      await addHousehold(app.db, app.serverId);
      await openRoute(tester, '/library');
      await tester.tap(find.text('Albums'));
      await settle(tester);

      expect(find.text('Only your music'), findsOneWidget);
      expect(find.text('Other People Music'), findsNothing,
          reason: 'the whole server is a view the person asks for');
      expect(containerOf(tester).read(settingsProvider).libraryScope,
          LibraryScope.mine);
      await closeApp(tester, app.db);
    });

    testWidgets('opens on my music and can show everything', (tester) async {
      SharedPreferences.setMockInitialValues({'encore.libraryScope': 'mine'});
      final app = await pumpApp(tester, size: tall);
      await addHousehold(app.db, app.serverId);
      await openRoute(tester, '/library');
      await tester.tap(find.text('Albums'));
      await settle(tester);

      expect(find.text('Only your music'), findsOneWidget);
      expect(find.text('Kodama'), findsOneWidget);
      expect(find.text('Other People Music'), findsNothing,
          reason: 'nobody here played, liked or saved it');

      await tester.tap(find.text('Show the whole server'));
      await settle(tester);

      expect(find.text('Everything on the server'), findsOneWidget);
      expect(find.text('Other People Music'), findsOneWidget);
      expect(containerOf(tester).read(settingsProvider).libraryScope,
          LibraryScope.everything);
      await closeApp(tester, app.db);
    });

    testWidgets('shared playlists appear only with "everything", labelled',
        (tester) async {
      SharedPreferences.setMockInitialValues({'encore.libraryScope': 'mine'});
      final app = await pumpApp(tester, size: tall);
      await addHousehold(app.db, app.serverId);
      await openRoute(tester, '/library');
      await tester.tap(find.text('Playlists'));
      await settle(tester);

      expect(find.text('Prog Snob'), findsOneWidget);
      expect(find.text('Sara road trip'), findsNothing);

      containerOf(tester)
          .read(settingsProvider.notifier)
          .setLibraryScope(LibraryScope.everything);
      await settle(tester);

      expect(find.text('Sara road trip'), findsOneWidget);
      expect(find.text('Playlist • by sara'), findsWidgets);
      await closeApp(tester, app.db);
    });

    testWidgets('a new account sees why it is empty and how to see more',
        (tester) async {
      SharedPreferences.setMockInitialValues({'encore.libraryScope': 'mine'});
      final app = await pumpApp(
        tester,
        size: tall,
        // The first sync has finished, so "empty" is the real answer.
        overrides: [
          syncStatusProvider.overrideWith(
              (ref) => Stream.value(const SyncStatus(initialSyncDone: true))),
        ],
      );
      // Nothing played, liked, downloaded or in a playlist of its own.
      await app.db.delete(app.db.playlistEntries).go();
      await app.db.delete(app.db.playlists).go();
      await (app.db.update(app.db.tracks))
          .write(const TracksCompanion(starredAtMs: Value(null)));
      await openRoute(tester, '/library');
      // "Mine" is re-evaluated at most every few seconds.
      await tester.pump(const Duration(seconds: 4));
      await settle(tester);

      expect(find.text('Nothing of yours yet'), findsOneWidget);

      await tester.tap(find.text('Browse the whole server'));
      await settle(tester);

      expect(find.text('Nothing of yours yet'), findsNothing);
      await closeApp(tester, app.db);
    });
  });

  group('Settings > Home, library & privacy', () {
    testWidgets('chooses the scope and private listening', (tester) async {
      final app = await pumpApp(tester, size: tall);
      await openRoute(tester, '/settings/home');

      expect(find.text('Automatic'), findsNothing);
      expect(find.text('Only my music'), findsOneWidget);
      expect(find.text('Everything on the server'), findsOneWidget);
      expect(find.text('Signed in as marwa'), findsOneWidget);

      await tester.tap(find.text('Everything on the server'));
      await settle(tester);
      await tester.tap(find.text('Private listening'));
      await settle(tester);

      final settings = containerOf(tester).read(settingsProvider);
      expect(settings.libraryScope, LibraryScope.everything);
      expect(settings.privateListening, isTrue);
      await closeApp(tester, app.db);
    });

    testWidgets('private listening is a line of the player\'s "..." menu',
        (tester) async {
      final app = await pumpApp(tester, playing: samplePlaying());
      await tester.tap(find.text('Opening The').first);
      await settle(tester);

      await tester.tap(find.byTooltip('More options'));
      await settle(tester);
      await tester.tap(find.text('Private listening: off'));
      await settle(tester);

      expect(
          containerOf(tester).read(settingsProvider).privateListening, isTrue);
      await tester.tap(find.byTooltip('More options'));
      await settle(tester);
      expect(find.text('Private listening: on'), findsOneWidget);
      await closeApp(tester, app.db);
    });
  });
}
