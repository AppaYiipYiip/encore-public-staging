import 'package:dio/dio.dart';
import 'package:drift/drift.dart' show Value;
import 'package:encore/app/connection.dart'
    show ServerReachability, serverReachabilityProvider;
import 'package:encore/data/catalogue/catalogue_models.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/encore/encore_api.dart';
import 'package:encore/data/encore/encore_instant.dart';
import 'package:encore/data/encore/encore_models.dart';
import 'package:encore/design/theme.dart';
import 'package:encore/design/tokens.dart';
import 'package:encore/features/common/playability.dart'
    show kNotAvailableWords, kNotDownloadedWords;
import 'package:encore/features/common/widgets.dart';
import 'package:encore/features/instant/instant_controller.dart';
import 'package:encore/features/instant/song_refusals.dart';
import 'package:encore/features/providers.dart';
import 'package:encore/features/requests/request_providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/factories.dart';
import '../support/fake_catalogue.dart';
import '../support/fake_encore_server.dart';
import '../support/reachability.dart';
import '../support/test_app.dart';

/// B-128 (found 14 Nov 2026 on an emulator): N-13's grey row was missing on the phone that tapped the song.
///
/// A tap on a catalogue song makes it a **row of the phone's own library** (a ref with no file); Search then shows that library row and the mark was
/// read only from the catalogue hit, so the owner's own scenario (tap an unfindable song, then search again) drew a playable-looking row, and a library
/// or playlist row was never marked at all. The rules these tests hold:
///
/// * a library row is marked by its **ref id** (the exact identity), so the merge with the catalogue's hit cannot lose it;
/// * a marked library row **never tries**: its tap says why, its menu's Play next, Add to queue and Download say it, its swipe says it, and a whole-list
///   play leaves it out (the drawing, S-12 and S-34);
/// * a refusal makes the song grey at once, without waiting for the ten minutes a "no problem" is otherwise trusted;
/// * offline always wins, and a song that can be played is never marked.
void main() {
  setUpAll(loadAppFonts);

  const lofiCatalogue = CatalogueTrack(
    id: 'dz-1',
    title: 'Lofi For Focus',
    artistName: 'Lofi & Sleep',
    duration: Duration(minutes: 3),
  );
  const sentence =
      'Nothing matching that song was found. Try again in a few days.';

  group('PB-F21 TrackTile (B-128)', () {
    final mark = EncoreUnavailable(
      reason: 'not_found',
      message: 'Nothing matching that song was found.',
      retryAfter: DateTime(2030),
    );

    Future<void> pump(WidgetTester tester,
            {EncoreUnavailable? mark, bool available = true}) =>
        tester.pumpWidget(ProviderScope(
            child: MaterialApp(
          theme: buildEncoreTheme(EncoreColors.dark(),
              brightness: Brightness.dark),
          home: Scaffold(
            body: TrackTile(
              track: trackRow('sr_1',
                  title: 'Lofi For Focus', artist: 'Lofi & Sleep'),
              mark: mark,
              available: available,
            ),
          ),
        )));

    testWidgets(
        'a marked song says "Not available on your server" in place of the artist, and its semantics say so',
        (tester) async {
      await pump(tester, mark: mark);

      expect(find.text(kNotAvailableWords), findsOneWidget);
      expect(find.text('Lofi & Sleep'), findsNothing);
      expect(find.bySemanticsLabel(RegExp(kNotAvailableWords)), findsOneWidget);
      expect(find.byIcon(Icons.cloud_off_rounded), findsNothing,
          reason:
              'the cloud is offline\'s: the song is not away, it is not there');
    });

    testWidgets('a song with no mark is exactly what it was (the control)',
        (tester) async {
      await pump(tester);

      expect(find.text('Lofi & Sleep'), findsOneWidget);
      expect(find.text(kNotAvailableWords), findsNothing);
    });

    testWidgets('offline wins: "Not downloaded" is said, never both',
        (tester) async {
      await pump(tester, mark: mark, available: false);

      expect(find.text(kNotDownloadedWords), findsOneWidget);
      expect(find.text(kNotAvailableWords), findsNothing);
    });
  });

  group('PB-F21 in Search, on the phone that tapped the song (B-128)', () {
    late FakeEncoreServer server;
    late _Recording facade;
    late String refId;

    /// The phone of the owner's scenario: the song is a row of the library (made by the tap, no file) and the catalogue lists it too.
    Future<AppDatabase> openSearch(
      WidgetTester tester, {
      bool away = false,
      List<CatalogueTrack> catalogueTracks = const [lofiCatalogue],
      List<String> alsoInLibrary = const [],
      bool withLibraryRow = true,
    }) async {
      server = FakeEncoreServer();
      facade = _Recording();
      refId = server.addRef('Lofi For Focus', 'Lofi & Sleep');
      final app = await pumpApp(tester, overrides: [
        playbackFacadeProvider.overrideWithValue(facade),
        enginePlaybackFacadeProvider.overrideWithValue(facade),
        catalogueClientProvider.overrideWithValue(
            FakeCatalogue(CatalogueResults(tracks: catalogueTracks))),
        serverReachabilityProvider.overrideWith(() => ReachabilityFrom(() =>
            away ? ServerReachability.serverAway : ServerReachability.ok)),
        instantBackendProvider.overrideWith((ref) async => EncoreInstantBackend(
              api: EncoreApi(
                dio: Dio()..httpClientAdapter = server.adapter,
                baseUrl: () => Uri.parse('http://home.test:4540'),
                auth: () => {'u': 'tester', 't': 'tok', 's': 'salt'},
              ),
              ingest: (_) async {},
            )),
      ]);
      Future<void> addRef(String id, String title) =>
          app.db.into(app.db.tracks).insert(TracksCompanion.insert(
                serverId: app.serverId,
                id: id,
                title: title,
                isRef: const Value(true),
                artist: const Value('Lofi & Sleep'),
                artistsJson: const Value('["Lofi & Sleep"]'),
              ));
      if (withLibraryRow) await addRef(refId, 'Lofi For Focus');
      for (final title in alsoInLibrary) {
        await addRef(server.addRef(title, 'Lofi & Sleep'), title);
      }
      return app.db;
    }

    Future<void> search(WidgetTester tester, String text) async {
      await tester.tap(find.text('Search').last);
      await settle(tester);
      await tester.enterText(find.byType(TextField), text);
      await tester.pump(const Duration(milliseconds: 600));
      await settle(tester);
      await tester.pump(const Duration(seconds: 1));
      await settle(tester);
    }

    final topCard = find.byKey(const Key('top-result'));
    Finder inTop(Finder what) => find.descendant(of: topCard, matching: what);
    Finder snack(String text) => find.descendant(
        of: find.byType(SnackBar), matching: find.textContaining(text));

    testWidgets(
        'the owner\'s scenario: tap an unfindable song, get refused, search again: the merged row is grey, and a second tap says why without trying',
        (tester) async {
      final db = await openSearch(tester);
      await search(tester, 'lofi for focus');
      expect(inTop(find.text('Lofi For Focus')), findsOneWidget,
          reason: 'precondition: the library row is the Top result');
      expect(inTop(find.byIcon(Icons.play_circle_fill_rounded)), findsOneWidget,
          reason: 'before the tap nothing is known: a normal Play circle');
      expect(inTop(find.text(kNotAvailableWords)), findsNothing);

      // The first tap: the player is given the library row, the server searches once, finds nothing, remembers it and refuses the stream.
      await tester.tap(topCard);
      await settle(tester);
      expect(facade.played, [
        [refId]
      ]);
      server.cannotGet['lofi for focus'] =
          (reason: 'not_found', retryIn: const Duration(days: 7));
      ProviderScope.containerOf(tester.element(find.byType(Scaffold).first))
          .read(songRefusalsProvider.notifier)
          .refused(); // what the player says when the stream's answer is `song_unavailable`
      await tester.pump(const Duration(milliseconds: 200));
      await settle(tester);

      expect(inTop(find.text(kNotAvailableWords)), findsOneWidget,
          reason: 'grey at once, without the ten minutes of trust');
      expect(inTop(find.byIcon(Icons.remove_circle_outline_rounded)),
          findsOneWidget,
          reason: 'the quiet circle of the drawing');
      expect(inTop(find.byIcon(Icons.play_circle_fill_rounded)), findsNothing);
      expect(inTop(find.byTooltip('More options')), findsOneWidget,
          reason: 'the Top result of a library song keeps its "..." button');

      // The second tap: nothing is tried, nothing is asked of the player, the sentence is said.
      await tester.tap(topCard);
      await settle(tester);
      expect(snack(sentence), findsOneWidget);
      expect(facade.played, hasLength(1), reason: 'no second try');
      expect(server.calls['POST refs/resolve'] ?? 0, 0,
          reason: 'the server was asked nothing about playing it');
      await closeApp(tester, db);
    });

    testWidgets(
        'a phone with no row for the song: the row of the catalogue greys at once after a refusal too (asked by description, as before)',
        (tester) async {
      final db = await openSearch(tester, withLibraryRow: false);
      await search(tester, 'lofi for focus');
      expect(inTop(find.text('Lofi For Focus')), findsOneWidget);
      expect(inTop(find.text(kNotAvailableWords)), findsNothing);
      expect(server.unavailableAsked, hasLength(1),
          reason: 'a catalogue song has no ref on the phone: it is described');

      server.cannotGet['lofi for focus'] =
          (reason: 'not_found', retryIn: const Duration(days: 7));
      ProviderScope.containerOf(tester.element(find.byType(Scaffold).first))
          .read(songRefusalsProvider.notifier)
          .refused();
      await tester.pump(const Duration(milliseconds: 200));
      await settle(tester);

      expect(inTop(find.text(kNotAvailableWords)), findsOneWidget);
      expect(server.unavailableAsked, hasLength(2));
      expect(server.unavailableIdsAsked, isEmpty);
      await closeApp(tester, db);
    });

    testWidgets(
        'a song of the library that the server already cannot get is grey in the Songs list too, and its tap says why',
        (tester) async {
      final db = await openSearch(tester,
          catalogueTracks: const [], alsoInLibrary: ['Lofi']);
      server.cannotGet['lofi for focus'] =
          (reason: 'not_found', retryIn: const Duration(days: 7));
      await search(tester, 'lofi');

      expect(inTop(find.text('Lofi')), findsOneWidget,
          reason:
              'precondition: the exact title is the Top result, the marked song is a row below');
      expect(find.text(kNotAvailableWords), findsOneWidget,
          reason: 'only the song the server cannot get');
      expect(server.unavailableIdsAsked, hasLength(1),
          reason: 'one question for the list, by ref id');
      expect(server.unavailableAsked, isEmpty);

      await tester.tap(find.text('Lofi For Focus').first);
      await settle(tester);
      expect(snack(sentence), findsOneWidget);
      expect(facade.played, isEmpty);
      await closeApp(tester, db);
    });

    testWidgets(
        'a tap on a song that can be had plays the library songs of the list from it and leaves the marked one out',
        (tester) async {
      final db = await openSearch(tester,
          catalogueTracks: const [],
          alsoInLibrary: ['Lofi', 'Lofi Rain', 'Lofi Dusk']);
      server.cannotGet['lofi for focus'] =
          (reason: 'removed', retryIn: const Duration(days: 7));
      await search(tester, 'lofi');
      expect(find.text(kNotAvailableWords), findsOneWidget);

      await tester.tap(find.text('Lofi Rain'));
      await settle(tester);

      expect(facade.played, hasLength(1));
      final titles = [
        for (final id in facade.played.single) server.refs[id]!['title']
      ];
      expect(titles, isNot(contains('Lofi For Focus')),
          reason: 'a song the server cannot get is not queued behind it');
      expect(titles, containsAll(['Lofi Rain', 'Lofi Dusk']));
      expect(titles[facade.starts.single], 'Lofi Rain',
          reason: 'the list plays on from the song that was tapped');
      await closeApp(tester, db);
    });

    testWidgets(
        'the "..." menu of a marked song says the words, and Play next, Add to queue and Download say why instead of acting',
        (tester) async {
      final db = await openSearch(tester,
          catalogueTracks: const [], alsoInLibrary: ['Lofi']);
      server.cannotGet['lofi for focus'] =
          (reason: 'not_found', retryIn: const Duration(days: 7));
      await search(tester, 'lofi');

      Future<void> openMenu() async {
        await tester.tap(find
            .descendant(
                of: find.ancestor(
                    of: find.text('Lofi For Focus'),
                    matching: find.byType(TrackTile)),
                matching: find.byTooltip('More options'))
            .first);
        await settle(tester);
      }

      await openMenu();
      expect(find.text(kNotAvailableWords), findsNWidgets(2),
          reason: 'the row, and the song line of the menu');
      for (final (i, action)
          in ['Play next', 'Add to queue', 'Download'].indexed) {
        if (i > 0) {
          await tester
              .pump(const Duration(seconds: 6)); // the last snackbar goes
          await settle(tester);
          await openMenu();
        }
        await tester.tap(find.text(action));
        await settle(tester);
        expect(snack(sentence), findsOneWidget, reason: action);
        expect(facade.calls.where((c) => c.startsWith('queue(')), isEmpty,
            reason: action);
        expect(facade.calls.where((c) => c.startsWith('next(')), isEmpty,
            reason: action);
      }
      await closeApp(tester, db);
    });

    testWidgets(
        'the control: the menu of a song that can be had acts as it always did',
        (tester) async {
      final db = await openSearch(tester,
          catalogueTracks: const [], alsoInLibrary: []);
      await search(tester, 'lofi for focus');
      await tester.tap(find.byTooltip('More options').first);
      await settle(tester);

      await tester.tap(find.text('Add to queue'));
      await settle(tester);

      expect(facade.calls, contains('queue($refId)'));
      await closeApp(tester, db);
    });

    testWidgets('a swipe right on a marked song says why and queues nothing',
        (tester) async {
      final db = await openSearch(tester,
          catalogueTracks: const [], alsoInLibrary: ['Lofi']);
      server.cannotGet['lofi for focus'] =
          (reason: 'not_found', retryIn: const Duration(days: 7));
      await search(tester, 'lofi');

      await tester.drag(
          find.text('Lofi For Focus').first, const Offset(300, 0));
      await settle(tester);

      expect(snack(sentence), findsOneWidget);
      expect(facade.calls.where((c) => c.startsWith('queue(')), isEmpty);
      await closeApp(tester, db);
    });

    testWidgets(
        'offline wins: nothing is asked, and the row says "Not downloaded", never the mark',
        (tester) async {
      final db = await openSearch(tester,
          away: true, catalogueTracks: const [], alsoInLibrary: ['Lofi']);
      server.cannotGet['lofi for focus'] =
          (reason: 'not_found', retryIn: const Duration(days: 7));
      await search(tester, 'lofi');

      expect(find.text(kNotAvailableWords), findsNothing);
      expect(find.text(kNotDownloadedWords), findsWidgets);
      expect(server.unavailableIdsAsked, isEmpty);
      await closeApp(tester, db);
    });

    testWidgets(
        'a song with a file on the server is never marked, whatever the server remembers about an older try',
        (tester) async {
      final db = await openSearch(tester, catalogueTracks: const []);
      await db
          .update(db.tracks)
          .write(const TracksCompanion(fileId: Value('nd-1')));
      server.cannotGet['lofi for focus'] =
          (reason: 'not_found', retryIn: const Duration(days: 7));
      await search(tester, 'lofi');

      expect(find.text(kNotAvailableWords), findsNothing);
      expect(server.unavailableIdsAsked, isEmpty,
          reason: 'a row with a file is not even asked about');
      await closeApp(tester, db);
    });
  });
}

/// A player that writes down which songs it was given (by id) and where it was told to start, in order.
class _Recording extends FakePlaybackFacade {
  final List<List<String>> played = [];
  final List<int> starts = [];

  @override
  Future<void> playTracks(List<TrackRow> tracks,
      {int startIndex = 0,
      String? sourceName,
      String? sourceId,
      bool shuffle = false,
      bool skipUnavailable = false}) {
    played.add([for (final t in tracks) t.id]);
    starts.add(startIndex);
    return super.playTracks(tracks,
        startIndex: startIndex,
        sourceName: sourceName,
        sourceId: sourceId,
        shuffle: shuffle,
        skipUnavailable: skipUnavailable);
  }
}
