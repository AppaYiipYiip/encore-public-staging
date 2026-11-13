import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:drift/native.dart';
import 'package:encore/app/providers.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/repos/library_repository.dart';
import 'package:encore/design/theme.dart';
import 'package:encore/design/tokens.dart';
import 'package:encore/features/common/widgets.dart';
import 'package:encore/features/detail/detail_screens.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import '../support/test_app.dart';

/// Owner, 7 Nov 2026: the artist of "Sunflower" opened a page that was a bare spinner for ever, with no way back. A page of one thing (an artist,
/// an album, a playlist) for which the phone has no row must say so after a moment, and always have the way back. A song tagged "A, B" has an
/// artist link to nothing the phone lists: its page is the page of the artist of its albums.
void main() {
  setUpAll(loadAppFonts);

  Widget app(Widget home, {List<Override> overrides = const []}) =>
      ProviderScope(
        overrides: overrides,
        child: MaterialApp(
          theme: buildEncoreTheme(EncoreColors.dark(),
              brightness: Brightness.dark),
          home: home,
        ),
      );

  /// Moves the test's clock past the page's patience in small steps, so the database's answer (an event of its own) is taken in between.
  Future<void> looked(WidgetTester tester) async {
    for (var i = 0; i < 20; i++) {
      await tester.pump(const Duration(milliseconds: 500));
    }
  }

  /// A stream of the database that is cancelled leaves a zero-length timer of its own: unmount the page and let it run before the test ends.
  Future<void> leave(WidgetTester tester) async {
    await tester.pumpWidget(const SizedBox());
    await tester.pump(const Duration(seconds: 1));
  }

  group('the placeholder of a page whose row is not there', () {
    testWidgets('is a spinner with a way back while the row is awaited',
        (tester) async {
      await tester.pumpWidget(app(const DetailPlaceholder(what: 'album')));

      expect(find.byType(CircularProgressIndicator), findsOneWidget);
      expect(find.byType(BackButton), findsOneWidget);
      await tester.pump(const Duration(seconds: 30));
      expect(find.byType(CircularProgressIndicator), findsOneWidget,
          reason: 'a row that has not been looked for is still awaited');
    });

    testWidgets(
        'says the thing is not on this phone once the row was looked for and '
        'is still not there, and keeps the way back', (tester) async {
      await tester.pumpWidget(
          app(const DetailPlaceholder(what: 'album', missing: true)));

      expect(find.byType(CircularProgressIndicator), findsOneWidget,
          reason: 'a moment of patience: a row can be a sync behind');
      await tester.pump(const Duration(seconds: 5));

      expect(find.byType(CircularProgressIndicator), findsNothing);
      expect(find.text('This album is not on this phone'), findsOneWidget);
      expect(find.byType(BackButton), findsOneWidget);
    });

    testWidgets('goes back to the spinner when the row turns up',
        (tester) async {
      Widget build(bool missing) =>
          app(DetailPlaceholder(what: 'playlist', missing: missing));
      await tester.pumpWidget(build(true));
      await tester.pump(const Duration(seconds: 5));
      expect(find.text('This playlist is not on this phone'), findsOneWidget);

      await tester.pumpWidget(build(false));

      expect(find.byType(CircularProgressIndicator), findsOneWidget);
    });
  });

  group('the pages of an album, a playlist and an artist the phone lacks', () {
    late AppDatabase db;
    late int serverId;
    late LibraryRepository repo;

    setUp(() async {
      db = AppDatabase(NativeDatabase.memory());
      serverId = await db.into(db.servers).insert(ServersCompanion.insert(
            name: 'Home',
            username: 'friend',
            endpointsJson: '[]',
            createdAtMs: 0,
          ));
      repo = LibraryRepository(db, serverId);
    });

    tearDown(() => db.close());

    List<Override> over() => [
          libraryRepositoryProvider.overrideWithValue(repo),
          activeServerProvider.overrideWith((ref) => const Stream.empty()),
        ];

    testWidgets('an album that is not there is said, with the way back',
        (tester) async {
      await tester.pumpWidget(
          app(const AlbumScreen(albumId: 'nope'), overrides: over()));
      await looked(tester);

      expect(find.text('This album is not on this phone'), findsOneWidget);
      expect(find.byType(BackButton), findsOneWidget);
      await leave(tester);
    });

    testWidgets('a playlist that is not there is said, with the way back',
        (tester) async {
      await tester.pumpWidget(
          app(const PlaylistScreen(playlistId: 'nope'), overrides: over()));
      await looked(tester);

      expect(find.text('This playlist is not on this phone'), findsOneWidget);
      expect(find.byType(BackButton), findsOneWidget);
      await leave(tester);
    });

    testWidgets(
        'an artist nobody can stand in for is said, with the way back, and '
        'not a spinner for ever', (tester) async {
      await tester.pumpWidget(
          app(const ArtistScreen(artistId: 'nope'), overrides: over()));
      await looked(tester);

      expect(find.text('This artist is not on this phone'), findsOneWidget);
      expect(find.byType(BackButton), findsOneWidget);
      expect(find.byType(CircularProgressIndicator), findsNothing);
      await leave(tester);
    });

    testWidgets(
        'the artist a song is tagged with ("Post Malone, Swae Lee") opens the '
        'page of the artist of its album, in its place', (tester) async {
      await db.into(db.artists).insert(ArtistsCompanion.insert(
          serverId: serverId,
          id: 'pm',
          name: 'Post Malone',
          albumCount: const Value(1)));
      await db.into(db.albums).insert(AlbumsCompanion.insert(
          serverId: serverId,
          id: 'al1',
          name: 'Album',
          artistId: const Value('pm')));
      await db.into(db.tracks).insert(TracksCompanion.insert(
            serverId: serverId,
            id: 's1',
            title: 'Sunflower',
            artistId: const Value('pm-sl'),
            albumId: const Value('al1'),
            artist: const Value('Post Malone, Swae Lee'),
          ));
      final router = GoRouter(
        initialLocation: '/library/artist/pm-sl',
        routes: [
          GoRoute(
              path: '/library/artist/:id',
              builder: (context, state) => state.pathParameters['id'] == 'pm'
                  ? const Scaffold(body: Text('the page of Post Malone'))
                  : ArtistScreen(artistId: state.pathParameters['id']!)),
        ],
      );
      await tester.pumpWidget(ProviderScope(
        overrides: over(),
        child: MaterialApp.router(
          theme: buildEncoreTheme(EncoreColors.dark(),
              brightness: Brightness.dark),
          routerConfig: router,
        ),
      ));
      await tester.pumpAndSettle(const Duration(milliseconds: 100));

      expect(find.text('the page of Post Malone'), findsOneWidget);
      expect(router.routerDelegate.currentConfiguration.uri.path,
          '/library/artist/pm');
      await leave(tester);
    });
  });
}
