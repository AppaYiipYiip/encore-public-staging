import 'dart:async';

import 'package:encore/app/connection.dart';
import 'package:encore/app/providers.dart';
import 'package:encore/core/network_validation.dart';
import 'package:encore/data/catalogue/catalogue_models.dart';
import 'package:encore/data/repos/library_repository.dart' show OnPhone;
import 'package:encore/features/common/widgets.dart' show TrackTile;
import 'package:encore/features/providers.dart'
    show downloadedIdsProvider, onPhoneProvider;
import 'package:encore/features/requests/request_providers.dart'
    show catalogueClientProvider;
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../support/fake_catalogue.dart';
import '../support/test_app.dart';

/// P1-16: Search says when the phone cannot ask the catalogue (drawn 5 Nov 2026, docs/design S-11, S-12, S-13, classes C and X).
///
/// The rule these tests hold: **while the server is away (the one state of P1-17, `serverReachabilityProvider`) the catalogue is not asked and
/// none of its rows is shown, so that "More results need your server." is true; the phone's own library still answers at once; and every
/// sentence says what cannot be DONE, in the words of the strip's own two causes (no internet found / only the server silent).** It goes by
/// itself when the connection is back. A server that goes silent counts only after the 4 s grace of a blink; having no network at all counts
/// at once (the grey rows already do, P1-09).
void main() {
  setUpAll(loadAppFonts);
  setUp(() => SharedPreferences.setMockInitialValues({}));

  // The words of the drawing, one place (a drawn word changes here once).
  const hintOffline = 'Search your music';
  const hintOnline = 'What do you want to listen to?';
  const moreNeedConnection = 'More results need a connection.';
  const moreNeedServer = 'More results need your server.';
  const browseNeedConnection = 'Browsing needs a connection.';
  const browseNeedServer = 'Browsing needs your server.';
  const connectToSearchMore = 'Connect to search more.';
  const serverNotAnswering =
      "Your server isn't answering, so only your music can be searched.";

  const dreams = CatalogueTrack(
      id: 'dz-1', title: 'Kodama Dreams', artistName: 'Someone Else');
  const catalogueKnows = CatalogueResults(tracks: [dreams]);

  /// The three ways the phone cannot reach its server, and what Android found out about the internet in each.
  List<Override> away(_Away how, {Set<String> downloaded = const {'al1-t1'}}) =>
      [
        connectionGraceProvider.overrideWithValue(Duration.zero),
        networkKindProvider.overrideWith((ref) => Stream.value(
            how == _Away.noNetwork ? NetworkKind.none : NetworkKind.wifi)),
        if (how != _Away.noNetwork) ...[
          serverFindingProvider
              .overrideWith((ref) => Stream.value(ServerFinding.silent)),
          networkValidationProvider
              .overrideWithValue(_Validation(how == _Away.serverSilent)),
        ],
        downloadedIdsProvider.overrideWith((ref) => Stream.value(downloaded)),
      ];

  Future<void> openSearch(WidgetTester tester) async {
    await tester.tap(find.text('Search').last);
    await settle(tester);
  }

  /// Types [text] and lets the catalogue's 350 ms debounce, and then some, go by: a "never asked" is only proof after that.
  Future<void> search(WidgetTester tester, String text) async {
    await tester.enterText(find.byType(TextField), text);
    await tester.pump(const Duration(milliseconds: 90));
    await tester.pump(const Duration(milliseconds: 1000));
    await settle(tester);
  }

  /// The row of the song [title]: its [TrackTile].
  TrackTile tile(WidgetTester tester, String title) => tester.widget<TrackTile>(
      find.ancestor(of: find.text(title), matching: find.byType(TrackTile)));

  bool dimmed(WidgetTester tester, String genre) => tester
      .widgetList<Opacity>(
          find.ancestor(of: find.text(genre), matching: find.byType(Opacity)))
      .any((o) => o.opacity < 1);

  group('the start page (S-11 offline)', () {
    testWidgets(
        'no network: the hint says what can be searched, the genre tiles are dimmed, the recent searches stay, and nothing is added',
        (tester) async {
      SharedPreferences.setMockInitialValues({
        'encore.recent_searches': ['pink floyd']
      });
      final app = await pumpApp(tester, overrides: away(_Away.noNetwork));
      await openSearch(tester);
      // The strip has said it once; the page itself must not need it.
      await tester.pump(const Duration(seconds: 6));

      expect(find.text(hintOffline), findsOneWidget);
      expect(find.text(hintOnline), findsNothing);
      expect(find.text('Recent searches'), findsOneWidget);
      expect(find.text('pink floyd'), findsOneWidget);
      expect(find.text('Browse all'), findsOneWidget,
          reason: 'the tiles are dimmed, not removed (S-11 offline)');
      expect(dimmed(tester, 'Pop'), isTrue);
      expect(find.textContaining('needs a connection'), findsNothing,
          reason: 'no line, no banner, no cross is added to the page');
      expect(find.textContaining('need your server'), findsNothing);
      await closeApp(tester, app.db);
    });

    testWidgets(
        'online: the hint and the tiles are as before (the control of the test above)',
        (tester) async {
      final app = await pumpApp(tester);
      await openSearch(tester);

      expect(find.text(hintOnline), findsOneWidget);
      expect(find.text(hintOffline), findsNothing);
      expect(dimmed(tester, 'Pop'), isFalse);
      await closeApp(tester, app.db);
    });

    for (final how in [_Away.noInternetFound, _Away.serverSilent]) {
      testWidgets(
          '${how.name}: the page is the same for both causes (only the words after a tap differ)',
          (tester) async {
        final app = await pumpApp(tester, overrides: away(how));
        await openSearch(tester);

        expect(find.text(hintOffline), findsOneWidget);
        expect(dimmed(tester, 'Pop'), isTrue);
        await closeApp(tester, app.db);
      });
    }
  });

  group('the genre page (S-13 offline)', () {
    final byCause = {
      _Away.noNetwork: browseNeedConnection,
      _Away.noInternetFound: browseNeedConnection,
      _Away.serverSilent: browseNeedServer,
    };
    for (final MapEntry(key: how, value: words) in byCause.entries) {
      testWidgets(
          '${how.name}: a tap on a tile says why, in the words of its cause, and asks nobody',
          (tester) async {
        final catalogue = FakeCatalogue();
        final app = await pumpApp(tester, overrides: [
          ...away(how),
          catalogueClientProvider.overrideWithValue(catalogue),
        ]);
        await openSearch(tester);

        await tester.tap(find.text('Pop'));
        await settle(tester);
        await tester.pump(const Duration(seconds: 1));

        expect(find.text('Not available right now'), findsOneWidget);
        expect(find.text(words), findsOneWidget);
        expect(find.text('Could not load this genre'), findsNothing,
            reason:
                'that card is for an error; an absent connection is not one');
        expect(find.byType(CircularProgressIndicator), findsNothing,
            reason: 'never a spinner that waits for a line that is not there');
        expect(catalogue.lookups, isEmpty,
            reason: 'the catalogue is not asked while the server is away');

        await tester.tap(find.text('Back to Search'));
        await settle(tester);
        expect(find.text(hintOffline), findsOneWidget,
            reason: 'Back to Search goes back to the Search page');
        await closeApp(tester, app.db);
      });
    }

    testWidgets(
        'control: with the server answering the same tap asks for the genre and shows what is on top',
        (tester) async {
      final catalogue = FakeCatalogue()
        ..genreCharts[132] = const CatalogueGenreChart(tracks: [
          CatalogueTrack(id: 'g1', title: 'Sparks', artistName: 'Coldplay')
        ]);
      final app = await pumpApp(tester, overrides: [
        catalogueClientProvider.overrideWithValue(catalogue),
      ]);
      await openSearch(tester);

      await tester.tap(find.text('Pop'));
      await settle(tester);

      expect(catalogue.lookups, ['genre:132']);
      expect(find.text('Sparks'), findsOneWidget);
      expect(find.text('Not available right now'), findsNothing);
      await closeApp(tester, app.db);
    });

    testWidgets(
        'the connection goes while the page is open and comes back: the page follows both ways by itself',
        (tester) async {
      final changes = StreamController<NetworkKind>.broadcast();
      addTearDown(changes.close);
      final catalogue = FakeCatalogue()
        ..genreCharts[132] = const CatalogueGenreChart(tracks: [
          CatalogueTrack(id: 'g1', title: 'Sparks', artistName: 'Coldplay')
        ]);
      final app = await pumpApp(tester, overrides: [
        connectionGraceProvider.overrideWithValue(Duration.zero),
        networkKindProvider.overrideWith((ref) async* {
          yield NetworkKind.wifi;
          yield* changes.stream;
        }),
        catalogueClientProvider.overrideWithValue(catalogue),
      ]);
      await openSearch(tester);
      await tester.tap(find.text('Pop'));
      await settle(tester);
      expect(find.text('Sparks'), findsOneWidget);

      changes.add(NetworkKind.none);
      await settle(tester);
      expect(find.text('Not available right now'), findsOneWidget);
      expect(find.text(browseNeedConnection), findsOneWidget);
      expect(find.text('Sparks'), findsNothing);

      changes.add(NetworkKind.wifi);
      await settle(tester);
      expect(find.text('Not available right now'), findsNothing);
      expect(find.text('Sparks'), findsOneWidget,
          reason: 'back online: it asks again and shows the genre');
      expect(catalogue.lookups, ['genre:132', 'genre:132']);
      await closeApp(tester, app.db);
    });
  });

  group('the results (S-12 offline)', () {
    testWidgets(
        'no network: the library answers, what is not on the phone is grey and says so, one quiet last line says what more cannot be done, nobody is asked, nothing spins',
        (tester) async {
      final catalogue = FakeCatalogue.slow(catalogueKnows);
      final app = await pumpApp(tester, overrides: [
        ...away(_Away.noNetwork),
        catalogueClientProvider.overrideWithValue(catalogue),
      ]);
      await openSearch(tester);
      await search(tester, 'kodama');

      expect(catalogue.searches, 0,
          reason:
              'a catalogue that cannot be reached is not asked, and not waited for');
      expect(find.byType(CircularProgressIndicator), findsNothing);
      expect(tile(tester, 'Opening Kodama').available, isTrue,
          reason: 'downloaded: keeps its colour');
      expect(tile(tester, 'Echoes Kodama').available, isFalse,
          reason: 'not downloaded: grey');
      expect(
          find.descendant(
              of: find.ancestor(
                  of: find.text('Echoes Kodama'),
                  matching: find.byType(TrackTile)),
              matching: find.text('Not downloaded')),
          findsOneWidget);
      expect(find.text(moreNeedConnection), findsOneWidget);
      expect(find.text(moreNeedServer), findsNothing);
      expect(find.text('Kodama Dreams'), findsNothing);
      await closeApp(tester, app.db);
    });

    testWidgets(
        'a tap on a song that is not downloaded goes to the player, which says "Not downloaded. Connect to play it." (playback_engine_test)',
        (tester) async {
      final app = await pumpApp(tester, overrides: away(_Away.noNetwork));
      await openSearch(tester);
      await search(tester, 'kodama');

      await tester.tap(find.text('Echoes Kodama'));
      await settle(tester);

      expect(app.facade.calls.last, startsWith('playTracks('),
          reason:
              'the words are the player\'s own; the page does not copy them');
      await closeApp(tester, app.db);
    });

    testWidgets(
        'a silent server on a network with internet: the catalogue (which would still answer) is not asked and none of its rows is shown, so "your server" is true',
        (tester) async {
      final catalogue = FakeCatalogue(catalogueKnows);
      final app = await pumpApp(tester, overrides: [
        ...away(_Away.serverSilent),
        catalogueClientProvider.overrideWithValue(catalogue),
      ]);
      await openSearch(tester);
      await search(tester, 'kodama');

      expect(catalogue.searches, 0);
      expect(find.text('Kodama Dreams'), findsNothing);
      expect(find.text('Opening Kodama'), findsOneWidget);
      expect(find.text(moreNeedServer), findsOneWidget);
      expect(find.text(moreNeedConnection), findsNothing);
      await closeApp(tester, app.db);
    });

    testWidgets(
        'control: with the server answering the catalogue is asked once, its row joins, and there is no last line',
        (tester) async {
      final catalogue = FakeCatalogue(catalogueKnows);
      final app = await pumpApp(tester, overrides: [
        catalogueClientProvider.overrideWithValue(catalogue),
      ]);
      await openSearch(tester);
      await search(tester, 'kodama');

      expect(catalogue.searches, 1);
      expect(find.text('Kodama Dreams'), findsOneWidget);
      expect(find.textContaining('More results need'), findsNothing);
      expect(tile(tester, 'Echoes Kodama').available, isTrue);
      await closeApp(tester, app.db);
    });

    testWidgets(
        'the albums of the library: one with a song on the phone keeps its colour, one with nothing on it is grey and says so, like in the Library (S-14)',
        (tester) async {
      final app =
          await pumpApp(tester, size: const Size(390, 2400), overrides: [
        ...away(_Away.noNetwork),
        onPhoneProvider.overrideWith(
            (ref) => Stream.value(const OnPhone(albums: {'al1'}))),
      ]);
      await openSearch(tester);
      await search(tester, 'alcest');

      /// What the album's row says under its title, and whether it is dimmed.
      Finder row(String album) => find
          .ancestor(of: find.text(album), matching: find.byType(InkWell))
          .first;
      expect(
          find.descendant(
              of: row('Les Voyages de l’âme'),
              matching: find.text('Not downloaded')),
          findsOneWidget);
      expect(
          find.descendant(
              of: row('Kodama'),
              matching: find.textContaining('Not downloaded')),
          findsNothing,
          reason:
              'one of its songs is on the phone: it plays, it keeps its colour');
      await closeApp(tester, app.db);
    });

    testWidgets(
        'the Top result is an album with nothing on the phone: it says so too',
        (tester) async {
      final app = await pumpApp(tester, overrides: away(_Away.noNetwork));
      await openSearch(tester);
      await search(tester, 'voyages');

      expect(
          find.descendant(
              of: find.byKey(const Key('top-result')),
              matching: find.text('Album • Not downloaded')),
          findsOneWidget);
      await closeApp(tester, app.db);
    });
  });

  group('nothing found (S-12 offline)', () {
    final cases = {
      _Away.noNetwork: connectToSearchMore,
      _Away.noInternetFound: connectToSearchMore,
      _Away.serverSilent: serverNotAnswering,
    };
    for (final MapEntry(key: how, value: words) in cases.entries) {
      testWidgets(
          '${how.name}: it says what could not be searched, not that there is nothing',
          (tester) async {
        final catalogue = FakeCatalogue.slow();
        final app = await pumpApp(tester, overrides: [
          ...away(how),
          catalogueClientProvider.overrideWithValue(catalogue),
        ]);
        await openSearch(tester);
        await search(tester, 'zzqqx');

        expect(find.text('Nothing in your music matches ‘zzqqx’.'),
            findsOneWidget);
        expect(find.text(words), findsOneWidget);
        expect(find.textContaining('No results for'), findsNothing,
            reason:
                'the phone simply cannot look for more: that is not "no results"');
        expect(find.byType(CircularProgressIndicator), findsNothing);
        expect(find.textContaining('Closest'), findsNothing);
        expect(find.textContaining('Ask for it'), findsNothing);
        expect(catalogue.searches, 0);
        await closeApp(tester, app.db);
      });
    }

    testWidgets('control: online, the page is the one it always was',
        (tester) async {
      final app = await pumpApp(tester);
      await openSearch(tester);
      await search(tester, 'zzqqx');

      expect(find.text('No results for "zzqqx"'), findsOneWidget);
      expect(find.textContaining('Nothing in your music'), findsNothing);
      await closeApp(tester, app.db);
    });
  });

  group('the page and the strip agree (the acceptance of the item)', () {
    final cases = {
      _Away.noNetwork: ("You're offline", moreNeedConnection),
      _Away.noInternetFound: ("You're offline", moreNeedConnection),
      _Away.serverSilent: ("Can't reach your server.", moreNeedServer),
    };
    for (final MapEntry(key: how, value: (strip, page)) in cases.entries) {
      testWidgets('${how.name}: the strip says "$strip", the page "$page"',
          (tester) async {
        final app = await pumpApp(tester, overrides: away(how));
        await openSearch(tester);
        await search(tester, 'kodama');

        // Both on the screen in the same frame (the strip is said for 5 s).
        expect(find.textContaining(strip), findsOneWidget);
        expect(find.text(page), findsOneWidget);
        await closeApp(tester, app.db);
      });
    }
  });

  group('it comes and goes by itself', () {
    testWidgets(
        'the connection returns: the last line goes, the catalogue is asked once, its rows join, the hint is the old one',
        (tester) async {
      final changes = StreamController<NetworkKind>.broadcast();
      addTearDown(changes.close);
      final catalogue = FakeCatalogue(catalogueKnows);
      final app = await pumpApp(tester, overrides: [
        connectionGraceProvider.overrideWithValue(Duration.zero),
        networkKindProvider.overrideWith((ref) async* {
          yield NetworkKind.none;
          yield* changes.stream;
        }),
        catalogueClientProvider.overrideWithValue(catalogue),
      ]);
      await openSearch(tester);
      await search(tester, 'kodama');
      expect(find.text(moreNeedConnection), findsOneWidget);
      expect(catalogue.searches, 0);

      changes.add(NetworkKind.wifi);
      await tester.pump(const Duration(milliseconds: 50));
      await tester.pump(const Duration(milliseconds: 1000));
      await settle(tester);

      expect(find.text(moreNeedConnection), findsNothing);
      expect(catalogue.searches, 1);
      expect(find.text('Kodama Dreams'), findsOneWidget);
      expect(tile(tester, 'Echoes Kodama').available, isTrue);
      await closeApp(tester, app.db);
    });

    testWidgets(
        'the connection goes while a catalogue answer is on its way: the answer is not shown',
        (tester) async {
      final changes = StreamController<NetworkKind>.broadcast();
      addTearDown(changes.close);
      final catalogue = FakeCatalogue.slow(catalogueKnows);
      final app = await pumpApp(tester, overrides: [
        connectionGraceProvider.overrideWithValue(Duration.zero),
        networkKindProvider.overrideWith((ref) async* {
          yield NetworkKind.wifi;
          yield* changes.stream;
        }),
        catalogueClientProvider.overrideWithValue(catalogue),
      ]);
      await openSearch(tester);
      await search(tester, 'kodama');
      expect(catalogue.searches, 1, reason: 'online: it was asked');

      changes.add(NetworkKind.none);
      await settle(tester);
      catalogue.answerSearches();
      await settle(tester);

      expect(find.text('Kodama Dreams'), findsNothing,
          reason: 'what the server being away has stopped is not shown');
      expect(find.text(moreNeedConnection), findsOneWidget);
      await closeApp(tester, app.db);
    });

    testWidgets(
        'having no network at all counts at once, before the strip has appeared (the grey rows already do, P1-09)',
        (tester) async {
      final app = await pumpApp(tester, overrides: [
        networkKindProvider
            .overrideWith((ref) => Stream.value(NetworkKind.none)),
        downloadedIdsProvider.overrideWith((ref) => Stream.value({'al1-t1'})),
      ]);
      await openSearch(tester);

      expect(find.textContaining("You're offline"), findsNothing,
          reason: 'the strip waits for its 4 s grace');
      expect(find.text(hintOffline), findsOneWidget,
          reason: 'the page does not');
      await closeApp(tester, app.db);
    });

    testWidgets(
        'a silent server counts only after the 4 s grace (a blink is not news): nothing changes before it, everything after it',
        (tester) async {
      final catalogue = FakeCatalogue(catalogueKnows);
      final app = await pumpApp(tester, overrides: [
        networkKindProvider
            .overrideWith((ref) => Stream.value(NetworkKind.wifi)),
        serverFindingProvider
            .overrideWith((ref) => Stream.value(ServerFinding.silent)),
        networkValidationProvider.overrideWithValue(_Validation(true)),
        downloadedIdsProvider.overrideWith((ref) => Stream.value({'al1-t1'})),
        catalogueClientProvider.overrideWithValue(catalogue),
      ]);
      await openSearch(tester);
      await search(tester, 'kodama');

      // About 3 s in (the test's own clock): the server has been silent for less than the 4 s grace.
      expect(find.text(moreNeedServer), findsNothing);
      expect(tile(tester, 'Echoes Kodama').available, isTrue,
          reason: 'nothing is greyed during the first 4 s');
      expect(catalogue.searches, 1);
      expect(find.text('Kodama Dreams'), findsOneWidget);

      await tester.pump(const Duration(seconds: 4));
      await settle(tester);

      expect(find.text(moreNeedServer), findsOneWidget);
      expect(tile(tester, 'Echoes Kodama').available, isFalse);
      expect(find.text('Kodama Dreams'), findsNothing);
      await closeApp(tester, app.db);
    });
  });
}

/// How the phone cannot reach its server: no network at all; a network on which Android found no internet (4G with no data, a sign-in page)
/// and a silent server; a network with internet and a silent server (CN-1, CN-4b).
enum _Away { noNetwork, noInternetFound, serverSilent }

class _Validation implements NetworkValidation {
  _Validation(this.answer);

  final bool? answer;

  @override
  Future<bool?> validated() async => answer;
}
