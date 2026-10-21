import 'dart:async';

import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:encore/core/result.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/requests/portal_client.dart';
import 'package:encore/features/requests/request_providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../support/test_app.dart';

class _FakeImports implements ImportBackend {
  final List<String> calls = [];
  Result<ImportReceipt> next =
      const Ok(ImportReceipt(kind: 'playlist', name: 'Road trip'));

  @override
  Future<Result<ImportReceipt>> importLink(
      {required String url, String? name}) async {
    calls.add('import($url, name=$name)');
    return next;
  }

  @override
  Future<Result<void>> removeImport(String name) async {
    calls.add('removeImport($name)');
    return const Ok(null);
  }

  @override
  Future<Result<void>> removeArtist(String id) async {
    calls.add('removeArtist($id)');
    return const Ok(null);
  }

  @override
  Future<Result<void>> pickArtist(
      {required String id, required String mbid}) async {
    calls.add('pick($id, $mbid)');
    return const Ok(null);
  }
}

void main() {
  setUpAll(loadAppFonts);

  const connected = {'encore.requestPortal': 'http://portal:8700'};

  late _FakeImports backend;
  var overview = const PortalOverview();

  setUp(() {
    backend = _FakeImports();
    overview = const PortalOverview();
    SharedPreferences.setMockInitialValues(connected);
  });

  Future<({AppDatabase db, FakePlaybackFacade facade, int serverId})> open(
    WidgetTester tester, {
    String? shared,
    bool withBackend = true,
  }) async {
    final app = await pumpApp(
      tester,
      size: const Size(390, 1600),
      overrides: [
        importBackendProvider
            .overrideWith((ref) async => withBackend ? backend : null),
        portalOverviewProvider
            .overrideWith((ref) => Stream.value(withBackend ? overview : null)),
      ],
    );
    final element = tester.element(find.byType(Scaffold).first);
    unawaited(
        GoRouter.of(element).push<void>('/settings/import', extra: shared));
    await settle(tester);
    return app;
  }

  testWidgets('without a connected service it says what is missing',
      (tester) async {
    SharedPreferences.setMockInitialValues({});
    final app = await open(tester, withBackend: false);

    expect(find.text('Your server needs its download service'), findsOneWidget);
    final button = tester.widget<FilledButton>(find.byType(FilledButton));
    expect(button.onPressed, isNull);
    await closeApp(tester, app.db);
  });

  testWidgets('a playlist link is recognised and imported with a name',
      (tester) async {
    final app = await open(tester);

    await tester.enterText(find.byType(TextField).first,
        'https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=zz');
    await settle(tester);
    expect(find.text('Spotify playlist'), findsOneWidget);
    expect(find.text('Playlist name (optional)'), findsOneWidget);

    await tester.enterText(find.byType(TextField).last, 'Road trip');
    await tester.tap(find.text('Import playlist'));
    await settle(tester);

    const clean = 'https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M';
    expect(backend.calls, ['import($clean, name=Road trip)']);
    expect(find.textContaining('Importing "Road trip"'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets('an artist link asks for everything, without a name field',
      (tester) async {
    backend.next = const Ok(ImportReceipt(kind: 'artist', name: 'Alcest'));
    final app = await open(tester);

    await tester.enterText(find.byType(TextField).first,
        'https://open.spotify.com/artist/0OdUWJ0sBjDrqHygGUXeCF');
    await settle(tester);

    expect(find.text('Playlist name (optional)'), findsNothing);
    await tester.tap(find.text('Get everything by this artist'));
    await settle(tester);

    expect(
        backend.calls.single,
        'import(https://open.spotify.com/artist/0OdUWJ0sBjDrqHygGUXeCF, '
        'name=null)');
    expect(
        find.textContaining('Asked for everything by Alcest'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets('several links pasted together are imported one after another',
      (tester) async {
    final app = await open(tester);

    await tester.enterText(
        find.byType(TextField).first,
        'https://open.spotify.com/playlist/aaa\n'
        'https://open.spotify.com/playlist/bbb\n'
        'https://open.spotify.com/artist/ccc\n'
        'https://open.spotify.com/track/ddd');
    await settle(tester);

    expect(
        find.textContaining('2 playlists and 1 artist found'), findsOneWidget);
    expect(find.textContaining('1 other link skipped'), findsOneWidget);
    expect(find.text('Playlist name (optional)'), findsNothing);

    await tester.tap(find.text('Import 3 links'));
    await settle(tester);

    expect(backend.calls, [
      'import(https://open.spotify.com/playlist/aaa, name=null)',
      'import(https://open.spotify.com/playlist/bbb, name=null)',
      'import(https://open.spotify.com/artist/ccc, name=null)',
    ]);
    expect(find.textContaining('Sent all 3 links'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets('a batch reports what could not be sent', (tester) async {
    backend.next = Err(const ServerFailure('Playlist is private'));
    final app = await open(tester);

    await tester.enterText(find.byType(TextField).first,
        'https://open.spotify.com/playlist/aaa https://open.spotify.com/playlist/bbb');
    await settle(tester);
    await tester.tap(find.text('Import 2 links'));
    await settle(tester);

    expect(find.textContaining('2 could not be sent: Playlist is private'),
        findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets('an album or song link is explained and cannot be sent',
      (tester) async {
    final app = await open(tester);

    await tester.enterText(
        find.byType(TextField).first, 'https://open.spotify.com/album/1A2b3C');
    await settle(tester);

    expect(find.textContaining('single album'), findsOneWidget);
    final button = tester.widget<FilledButton>(find.byType(FilledButton));
    expect(button.onPressed, isNull);
    expect(backend.calls, isEmpty);
    await closeApp(tester, app.db);
  });

  testWidgets('the portal\'s refusal is shown and nothing is cleared',
      (tester) async {
    backend.next = Err(const ServerFailure('That playlist is private'));
    final app = await open(tester);

    await tester.enterText(
        find.byType(TextField).first, 'https://open.spotify.com/playlist/abc');
    await settle(tester);
    await tester.tap(find.text('Import playlist'));
    await settle(tester);

    expect(find.text('That playlist is private'), findsOneWidget);
    expect(find.text('https://open.spotify.com/playlist/abc'), findsOneWidget,
        reason: 'the link stays so it can be corrected');
    await closeApp(tester, app.db);
  });

  testWidgets('a link shared from another app arrives filled in',
      (tester) async {
    final app = await open(tester,
        shared: 'Road trip on Spotify '
            'https://open.spotify.com/playlist/AbC123?si=q');

    expect(find.text('Spotify playlist'), findsOneWidget);
    final field = tester.widget<TextField>(find.byType(TextField).first);
    expect(
        field.controller!.text, contains('open.spotify.com/playlist/AbC123'));
    await closeApp(tester, app.db);
  });

  testWidgets('imports show their progress and can be removed', (tester) async {
    overview = const PortalOverview(imports: [
      PortalImport(
        name: 'Road trip',
        state: 'reading',
        tracks: 52,
        inLibrary: 37,
        albums: 9,
        albumsRequested: 6,
      ),
      PortalImport(name: 'Done list', state: 'done', tracks: 10, inLibrary: 10),
    ]);
    final app = await open(tester);

    expect(find.text('Road trip'), findsOneWidget);
    expect(
        find.textContaining('37 of 52 songs on your server'), findsOneWidget);
    expect(find.textContaining('6 of 9 albums asked for'), findsOneWidget);
    expect(
        find.text('Complete - 10 of 10 songs on your server'), findsOneWidget);

    await tester.tap(find.byTooltip('Remove import').first);
    await settle(tester);
    expect(find.text('Remove this import?'), findsOneWidget);
    await tester.tap(find.text('Remove'));
    await settle(tester);

    expect(backend.calls, ['removeImport(Road trip)']);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'an import the portal still calls "waiting" shows the playlist that '
      'already exists', (tester) async {
    overview = const PortalOverview(imports: [
      PortalImport(
        name: 'Technical Death Metal 50 Essential Tracks',
        state: 'waiting for the first sync',
      ),
      PortalImport(name: 'Not made yet', state: 'waiting for the first sync'),
    ]);
    final app = await open(tester);
    await app.db.into(app.db.playlists).insert(PlaylistsCompanion.insert(
          serverId: app.serverId,
          id: 'tdm',
          name: 'Technical Death Metal 50 Essential Tracks',
          songCount: const Value(3),
        ));
    await settle(tester);

    expect(find.text('Your playlist has 3 songs so far'), findsOneWidget);
    expect(find.text('Tap to open it'), findsOneWidget);
    // One that has no playlist yet says what happens next, not just "waiting".
    expect(
        find.textContaining('picks it up within half an hour'), findsOneWidget);
    expect(find.textContaining('waiting for the first sync'), findsNothing);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'an artist you asked for says what has arrived and that it can '
      'be played now', (tester) async {
    overview = const PortalOverview(artists: [
      PortalArtist(
        id: 'a1',
        name: 'Pause',
        state: 'added',
        albums: 3,
        tracksHave: 0,
        tracksAll: 18,
      ),
    ]);
    final app = await open(tester);

    expect(
        find.text('Asked for - 3 albums - 0 of 18 full-quality songs have '
            'arrived'),
        findsOneWidget);
    expect(find.text('You can already play them: tap here'), findsOneWidget);
    expect(find.textContaining('songs here'), findsNothing);
    await closeApp(tester, app.db);
  });

  testWidgets('an ambiguous artist offers its candidates', (tester) async {
    overview = const PortalOverview(artists: [
      PortalArtist(
        id: 'a9',
        name: 'Pause',
        state: 'pick',
        candidates: [
          (mbid: 'm1', label: 'Pause (FR, rock)'),
          (mbid: 'm2', label: 'Pause (DE, techno)'),
        ],
      ),
    ]);
    final app = await open(tester);

    expect(find.text('Which one is yours?'), findsOneWidget);
    await tester.tap(find.text('Pause (DE, techno)'));
    await settle(tester);

    expect(backend.calls, ['pick(a9, m2)']);
    await closeApp(tester, app.db);
  });
}
