import 'dart:async';

import 'package:encore/core/result.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/fetch/fetch_client.dart';
import 'package:encore/data/fetch/import_models.dart';
import 'package:encore/features/common/widgets.dart';
import 'package:encore/features/import/import_providers.dart';
import 'package:encore/features/instant/instant_controller.dart';
import 'package:encore/features/instant/instant_play.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import '../support/factories.dart';
import '../support/test_app.dart';

/// The owner, 2026-10-18: "waiting to import a song instead of it being
/// instant is not right". An imported playlist lists every song at once and
/// every song plays at once (ADR-102): one that is not in the library yet is
/// fetched when it is tapped, while the import carries on behind it.

class _Import implements PlaylistImportBackend {
  List<ImportSong> songs = const [];
  ImportState state = ImportState.running;
  Result<ImportJob>? failure;
  int asked = 0;
  final List<List<int>> skipped = [];

  ImportJob job() => ImportJob(
        id: 'aaaaaaaaaaaa',
        name: 'Evening drive',
        kind: 'playlist',
        state: state,
        total: songs.length,
        done: songs.where((s) => s.state != ImportSongState.waiting).length,
        added: songs.where((s) => s.state == ImportSongState.ready).length,
        missing: songs.where((s) => s.state == ImportSongState.missing).length,
        playlistId: 'pl-1',
        playlistReady: true,
        songs: songs,
        updatedAt: 0,
      );

  @override
  Future<Result<ImportJob>> importStatus(String id,
      {bool songs = false}) async {
    asked++;
    return failure ?? Ok(job());
  }

  @override
  Future<Result<List<ImportJob>>> imports() async => Ok([job()]);

  @override
  Future<Result<ImportJob>> skipSongs(String id, List<int> indexes) async {
    skipped.add(indexes);
    songs = [
      for (var i = 0; i < songs.length; i++)
        indexes.contains(i) && songs[i].state == ImportSongState.waiting
            ? ImportSong(
                title: songs[i].title,
                artist: songs[i].artist,
                state: ImportSongState.missing,
                reason: 'skipped',
                message: 'You chose not to import this song.',
              )
            : songs[i],
    ];
    return Ok(job());
  }

  @override
  Future<Result<ImportedPlaylist>> readPlaylist(String url) =>
      throw UnimplementedError();

  @override
  Future<Result<ImportJob>> startImport({
    required String name,
    required String source,
    required List<ImportedTrack> tracks,
    bool liked = false,
  }) =>
      throw UnimplementedError();

  @override
  Future<Result<ImportJob>> cancelImport(String id) =>
      throw UnimplementedError();
}

/// The "play any song" service: it gets every song at once.
class _Songs implements InstantPlayBackend {
  final List<FetchRequest> asked = [];

  @override
  Future<void> prepare(FetchRequest request) async {}

  @override
  Future<Result<FetchJob>> start(FetchRequest request) async {
    asked.add(request);
    return Ok(FetchJob(
      id: 'j${asked.length}',
      state: FetchState.ready,
      songId: 'song-${request.title}',
    ));
  }

  @override
  Future<Result<FetchJob>> status(String id) async =>
      Ok(FetchJob(id: id, state: FetchState.ready));

  @override
  Uri? streamUrlFor(FetchRequest request) => null;

  @override
  Uri? streamUri(FetchJob job) => null;
}

ImportSong _song(String title, ImportSongState state,
        {String? videoId, bool official = false, String? message}) =>
    ImportSong(
      title: title,
      artist: 'Opeth',
      state: state,
      durationSec: 240,
      videoId: videoId,
      official: official,
      reason: message == null ? null : 'not_found',
      message: message,
    );

void main() {
  setUpAll(loadAppFonts);

  late _Import server;
  late _Songs songs;

  setUp(() {
    server = _Import()
      ..songs = [
        _song('Windowpane', ImportSongState.ready),
        _song('Burden', ImportSongState.ready),
        _song('Harvest', ImportSongState.waiting,
            videoId: 'sj27caXHKm4', official: true),
        _song('Ghost of Perdition', ImportSongState.missing,
            message: 'Nothing matching was found on YouTube.'),
        _song('Heir Apparent', ImportSongState.waiting),
        _song('Hessian Peel', ImportSongState.waiting),
      ];
    songs = _Songs();
  });

  Future<({AppDatabase db, FakePlaybackFacade facade, int serverId})> open(
      WidgetTester tester,
      {double height = 1600}) async {
    final service = InstantPlayService(
      backend: songs,
      matcher: null,
      loadSong: (id) async =>
          trackRow(id, title: id.substring(5), artist: 'Opeth'),
      pollEvery: Duration.zero,
      delay: (_) async {},
    );
    final app = await pumpApp(
      tester,
      size: Size(390, height),
      overrides: [
        playlistImportBackendProvider.overrideWithValue(server),
        instantAvailableProvider.overrideWithValue(true),
        instantPlayServiceProvider.overrideWith((ref) async => service),
      ],
    );
    final container =
        ProviderScope.containerOf(tester.element(find.byType(Scaffold).first));
    await tester
        .runAsync(() => container.read(instantPlayServiceProvider.future));
    final element = tester.element(find.byType(Scaffold).first);
    unawaited(GoRouter.of(element).push<void>('/home/import/aaaaaaaaaaaa'));
    await settle(tester);
    return app;
  }

  testWidgets(
      'every song of the playlist is on the page at once, the ones not '
      'fetched yet included', (tester) async {
    final app = await open(tester);

    expect(find.text('Evening drive'), findsWidgets);
    expect(find.text('6 songs - 2 in your library, fetching the other 3'),
        findsOneWidget);
    for (final title in [
      'Windowpane',
      'Burden',
      'Harvest',
      'Ghost of Perdition',
      'Heir Apparent',
      'Hessian Peel'
    ]) {
      expect(find.text(title), findsOneWidget, reason: title);
    }
    expect(find.textContaining('Tap any song to play it'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'a song that has not arrived yet plays when it is tapped, fetched by '
      'the video the playlist saved', (tester) async {
    final app = await open(tester);

    await tester.runAsync(() async {
      await tester.tap(find.text('Harvest'));
      await Future<void>.delayed(const Duration(milliseconds: 50));
    });
    await settle(tester);

    expect(songs.asked.first.title, 'Harvest');
    expect(songs.asked.first.videoId, 'sj27caXHKm4');
    expect(songs.asked.first.official, isTrue,
        reason: 'the service uses an official upload without searching');
    expect(app.facade.calls.first,
        'playTracks(1, start=0, source=Evening drive, shuffle=false)');
    await closeApp(tester, app.db);
  });

  testWidgets(
      'a song that could not be found is listed with why and is skipped by '
      'Play', (tester) async {
    final app = await open(tester);

    expect(find.text('Nothing matching was found on YouTube.'), findsOneWidget);
    await tester.runAsync(() async {
      await tester.tap(find.byType(PlayButton));
      await Future<void>.delayed(const Duration(milliseconds: 50));
    });
    await settle(tester);

    expect(songs.asked.map((r) => r.title).take(3),
        ['Windowpane', 'Burden', 'Harvest'].take(3).map((t) => t),
        reason:
            'play starts at the first song and never asks for the missing one');
    expect(
        songs.asked.map((r) => r.title), isNot(contains('Ghost of Perdition')));
    await closeApp(tester, app.db);
  });

  testWidgets(
      'the page keeps itself up to date while the import runs and stops when '
      'it is over', (tester) async {
    final app = await open(tester);
    final first = server.asked;

    server.songs = [
      for (final s in server.songs)
        s.state == ImportSongState.waiting
            ? _song(s.title, ImportSongState.ready)
            : s,
    ];
    await tester.pump(const Duration(seconds: 7));
    await tester.pump();
    expect(server.asked, greaterThan(first));
    expect(find.text('6 songs - 5 in your library, fetching the other 0'),
        findsNothing);

    server.state = ImportState.done;
    await tester.pump(const Duration(seconds: 7));
    await tester.pump();
    expect(find.text('6 songs - 1 song could not be found'), findsOneWidget);
    expect(find.text('Open in library'), findsOneWidget);

    final settled = server.asked;
    await tester.pump(const Duration(seconds: 30));
    expect(server.asked, settled,
        reason: 'a finished import is not asked about');
    await closeApp(tester, app.db);
  });

  testWidgets(
      'holding a song that has not been fetched offers to leave it out, and '
      'it is left out', (tester) async {
    final app = await open(tester);

    await tester.longPress(find.text('Heir Apparent'));
    await settle(tester);
    expect(find.text("Don't import this song"), findsOneWidget);
    await tester.tap(find.byKey(const Key('imported-skip')));
    await settle(tester);
    await tester.pump(const Duration(seconds: 1));
    await settle(tester);

    expect(server.skipped, [
      [4]
    ]);
    expect(find.text('You chose not to import this song.'), findsOneWidget);
    expect(find.textContaining('1 left out'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'holding a song that is in the library says how to take it off the '
      'playlist', (tester) async {
    final app = await open(tester);

    await tester.longPress(find.text('Windowpane'));
    await settle(tester);

    expect(find.text('To take it off the playlist'), findsOneWidget);
    expect(find.textContaining('Remove from this playlist'), findsOneWidget);
    expect(find.text('Open the playlist in your library'), findsOneWidget);
    expect(server.skipped, isEmpty);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'on a short phone the held-song sheet still shows and can tap its last '
      'row (it was clipped on a real emulator)', (tester) async {
    final app = await open(tester, height: 760);

    await tester.longPress(find.text('Windowpane'));
    await settle(tester);
    await tester.tap(find.text('Open the playlist in your library'));
    await settle(tester);

    expect(find.text('Open the playlist in your library'), findsNothing,
        reason: 'the tap reached the row: the sheet closed and went on');
    await closeApp(tester, app.db);
  });

  testWidgets('the library playlist can be opened while the import runs',
      (tester) async {
    final app = await open(tester);
    expect(find.text('Open in library'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets('a server that does not answer is said, with a way to try again',
      (tester) async {
    server.failure = const Err(NetworkFailure('no route'));
    final app = await open(tester);
    await tester.pump(const Duration(seconds: 13));
    await tester.pump();

    expect(find.text('The playlist could not be loaded.'), findsOneWidget);
    expect(find.text('Try again'), findsOneWidget);
    await closeApp(tester, app.db);
  });
}
