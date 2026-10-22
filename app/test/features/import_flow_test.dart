import 'dart:async';

import 'package:encore/app/file_intake.dart';
import 'package:encore/app/notifications.dart';
import 'package:encore/app/providers.dart';
import 'package:encore/core/result.dart';
import 'package:encore/data/alerts/alerts_service.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/fetch/fetch_client.dart';
import 'package:encore/data/fetch/import_models.dart';
import 'package:encore/features/import/import_providers.dart';
import 'package:encore/features/instant/instant_controller.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../support/test_app.dart';

/// A server that can take an import, and what it would answer.
class _Server implements PlaylistImportBackend {
  Result<ImportedPlaylist> playlist = const Ok(_evening);
  final List<String> read = [];
  final List<({String name, String source, bool liked, int songs})> started =
      [];
  List<ImportJob> jobs = [];
  final List<String> stopped = [];
  Completer<void>? holdReading;

  /// The songs of the import that was started last (the page of its playlist
  /// lists them all at once).
  List<ImportedTrack> startedTracks = const [];

  @override
  Future<Result<ImportedPlaylist>> readPlaylist(String url) async {
    read.add(url);
    await holdReading?.future;
    return playlist;
  }

  @override
  Future<Result<ImportJob>> startImport({
    required String name,
    required String source,
    required List<ImportedTrack> tracks,
    bool liked = false,
  }) async {
    started
        .add((name: name, source: source, liked: liked, songs: tracks.length));
    startedTracks = tracks;
    final job = running(name: name, total: tracks.length, liked: liked);
    jobs = [job, ...jobs];
    return Ok(job);
  }

  @override
  Future<Result<ImportJob>> importStatus(String id,
      {bool songs = false}) async {
    final job = jobs.firstWhere((j) => j.id == id);
    if (!songs) return Ok(job);
    return Ok(ImportJob(
      id: job.id,
      name: job.name,
      kind: job.kind,
      state: job.state,
      total: job.total,
      done: job.done,
      added: job.added,
      missing: job.missing,
      songs: [
        for (final t in startedTracks)
          ImportSong(
              title: t.title, artist: t.artist, state: ImportSongState.waiting),
      ],
    ));
  }

  @override
  Future<Result<List<ImportJob>>> imports() async => Ok(jobs);

  @override
  Future<Result<ImportJob>> skipSongs(String id, List<int> indexes) async =>
      Ok(jobs.firstWhere((j) => j.id == id));

  @override
  Future<Result<ImportJob>> cancelImport(String id) async {
    stopped.add(id);
    final old = jobs.firstWhere((j) => j.id == id);
    final job = ImportJob(
      id: old.id,
      name: old.name,
      kind: old.kind,
      state: ImportState.cancelled,
      total: old.total,
      done: old.done,
      added: old.added,
      missing: old.missing,
    );
    jobs = [for (final j in jobs) j.id == id ? job : j];
    return Ok(job);
  }
}

const _evening = ImportedPlaylist(
  name: 'Evening drive',
  source: 'spotify',
  kind: 'playlist',
  tracks: [
    ImportedTrack(title: 'Windowpane', artist: 'Opeth'),
    ImportedTrack(title: 'Burden', artist: 'Opeth'),
    ImportedTrack(title: 'Harvest', artist: 'Opeth'),
  ],
);

ImportJob running({
  String name = 'Evening drive',
  int total = 3,
  int done = 0,
  bool liked = false,
  String? paused,
}) =>
    ImportJob(
      id: 'aaaaaaaaaaaa',
      name: name,
      kind: liked ? 'liked' : 'playlist',
      state: ImportState.running,
      total: total,
      done: done,
      added: done,
      missing: 0,
      etaSec: 120,
      paused: paused,
      pausedMessage: paused == null
          ? null
          : 'YouTube is refusing the server for a while. Resting, then '
              'carrying on by itself.',
    );

ImportJob finished({int missing = 1}) => ImportJob(
      id: 'bbbbbbbbbbbb',
      name: 'Road trip',
      kind: 'playlist',
      state: ImportState.done,
      total: 4,
      done: 4,
      added: 4 - missing,
      missing: missing,
      playlistId: 'pl-9',
      playlistReady: true,
      message: '${4 - missing} songs in the playlist, $missing could not be '
          'added.',
      updatedAt: DateTime.now().millisecondsSinceEpoch / 1000,
      missingSongs: [
        for (var i = 0; i < missing; i++)
          const MissingSong(
            title: 'Burden',
            artist: 'Opeth',
            reason: 'not_found',
            message: 'Nothing matching was found on YouTube.',
          ),
      ],
    );

ProviderContainer makeContainer({required List<Override> overrides}) =>
    ProviderContainer(overrides: [
      sessionProvider.overrideWith((ref) async => null),
      ...overrides,
    ]);

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUpAll(loadAppFonts);

  late _Server server;
  late _Picker picker;

  setUp(() {
    server = _Server();
    picker = _Picker();
    SharedPreferences.setMockInitialValues({});
  });

  Future<({AppDatabase db, int serverId})> open(
    WidgetTester tester, {
    String? shared,
    bool seeded = true,
    bool route = true,
  }) async {
    final app = await pumpApp(
      tester,
      size: const Size(390, 1600),
      seeded: seeded,
      overrides: [
        playlistImportBackendProvider.overrideWithValue(server),
        songFilePickerProvider.overrideWithValue(picker),
        fetchInfoProvider.overrideWith((ref) async => const FetchServiceInfo(
            features: ['play-now', 'playlist', 'import'])),
      ],
    );
    if (route) {
      final element = tester.element(find.byType(Scaffold).first);
      unawaited(
          GoRouter.of(element).push<void>('/settings/import', extra: shared));
    }
    await settle(tester);
    return (db: app.db, serverId: app.serverId);
  }

  const spotifyLink =
      'https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=abc';

  testWidgets(
      'pasting a Spotify link shows the playlist before anything is '
      'added', (tester) async {
    final app = await open(tester);

    await tester.enterText(find.byKey(const Key('import-link')), spotifyLink);
    await settle(tester);
    expect(find.text('Spotify playlist'), findsOneWidget);
    await tester.tap(find.byKey(const Key('import-read')));
    await settle(tester);

    expect(server.read,
        ['https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M'],
        reason: 'the tracking part of the link is not sent');
    expect(find.text('3 songs from Spotify'), findsOneWidget);
    expect(find.text('Windowpane - Opeth'), findsOneWidget);
    expect(find.textContaining('as soon as you tap Import'), findsOneWidget);
    expect(find.text('Import 3 songs'), findsOneWidget);
    expect(
        tester
            .widget<TextField>(find.byKey(const Key('import-name')))
            .controller!
            .text,
        'Evening drive');
    expect(server.started, isEmpty, reason: 'nothing is added until agreed');
    await closeApp(tester, app.db);
  });

  testWidgets('a link that was shared to the app is read at once',
      (tester) async {
    final app =
        await open(tester, shared: 'Listen to this on Spotify $spotifyLink');

    expect(server.read, hasLength(1));
    expect(find.byKey(const Key('import-review')), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets('a private playlist says it is private and adds nothing',
      (tester) async {
    server.playlist = const Err(ServerFailure(
      'That playlist is private or does not exist. It must be public (or '
      'unlisted) to be read.',
      statusCode: 404,
      code: 'not_found',
    ));
    final app = await open(tester);

    await tester.enterText(find.byKey(const Key('import-link')), spotifyLink);
    await settle(tester);
    await tester.tap(find.byKey(const Key('import-read')));
    await settle(tester);

    expect(find.textContaining('private or does not exist'), findsOneWidget);
    expect(find.byKey(const Key('import-review')), findsNothing);
    expect(server.started, isEmpty);
    await closeApp(tester, app.db);
  });

  testWidgets('a link that is not a playlist is explained, not sent',
      (tester) async {
    final app = await open(tester);

    await tester.enterText(find.byKey(const Key('import-link')),
        'https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC');
    await settle(tester);

    expect(find.textContaining('That is one song'), findsOneWidget);
    expect(
        tester
            .widget<FilledButton>(find.byKey(const Key('import-read')))
            .onPressed,
        isNull);
    await tester.enterText(find.byKey(const Key('import-link')),
        'https://open.spotify.com/artist/0OdUWJ0sBjDrqHygGUXeCF');
    await settle(tester);
    expect(find.textContaining('That is an artist'), findsOneWidget);
    expect(server.read, isEmpty);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'a playlist that may be longer than what could be read says so '
      'before it is imported', (tester) async {
    server.playlist = const Ok(ImportedPlaylist(
      name: 'Death metal',
      source: 'spotify',
      kind: 'playlist',
      truncated: true,
      tracks: [ImportedTrack(title: 'A', artist: 'B')],
    ));
    final app = await open(tester, shared: spotifyLink);

    expect(find.byKey(const Key('import-truncated')), findsOneWidget);
    expect(find.textContaining('only the first 100 songs'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'agreeing hands the whole list over, leaves the page free and '
      'shows how far it is', (tester) async {
    final app = await open(tester, shared: spotifyLink);
    await tester.enterText(
        find.byKey(const Key('import-name')), 'Evening drive 2');

    await tester.ensureVisible(find.byKey(const Key('import-start')));
    await tester.tap(find.byKey(const Key('import-start')));
    await settle(tester);

    expect(server.started,
        [(name: 'Evening drive 2', source: 'spotify', liked: false, songs: 3)]);
    // Straight to the playlist: every song is on it at once (ADR-102).
    expect(find.byKey(const Key('imported-song-0')), findsOneWidget);
    expect(find.byKey(const Key('imported-song-2')), findsOneWidget);
    expect(find.text('Windowpane'), findsOneWidget);
    expect(find.text('3 songs - 0 in your library, fetching the other 3'),
        findsOneWidget);

    // The import page, opened again, shows how far it is.
    unawaited(GoRouter.of(tester.element(find.byType(Scaffold).first))
        .push<void>('/settings/import'));
    await settle(tester);
    expect(find.text('0 of 3 songs - about 2 minutes left'), findsOneWidget);

    server.jobs = [running(name: 'Evening drive 2', done: 2)];
    await tester.pump(const Duration(seconds: 5));
    await tester.pump();
    expect(find.textContaining('2 of 3 songs'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'choosing to like every song sends them as likes, not as a '
      'playlist', (tester) async {
    final app = await open(tester, shared: spotifyLink);

    await tester.tap(find.text('Like every song'));
    await settle(tester);
    expect(find.text('Like 3 songs'), findsOneWidget);
    await tester.ensureVisible(find.byKey(const Key('import-start')));
    await tester.tap(find.byKey(const Key('import-start')));
    await settle(tester);

    expect(server.started.single.liked, isTrue);
    expect(find.text('Your liked songs'), findsWidgets,
        reason: 'straight to the page of the songs being liked');
    await closeApp(tester, app.db);
  });

  testWidgets('a server that is resting says why, in words', (tester) async {
    server.jobs = [running(done: 1, paused: 'cooling_off')];
    final app = await open(tester);

    expect(
        find.textContaining('YouTube is refusing the server'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'a finished import offers the playlist and lists the songs '
      'that were not found', (tester) async {
    server.jobs = [finished()];
    final app = await open(tester);

    expect(find.text('3 songs in the playlist, 1 could not be added.'),
        findsOneWidget);
    expect(find.text('Open playlist'), findsOneWidget);
    await tester.tap(find.text('1 song not found'));
    await settle(tester);

    expect(find.text('Songs that could not be added'), findsOneWidget);
    expect(find.text('Burden'), findsOneWidget);
    expect(find.textContaining('Nothing matching was found on YouTube'),
        findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets('stopping asks first, then stops and keeps what arrived',
      (tester) async {
    server.jobs = [running(done: 2)];
    final app = await open(tester);

    await tester.ensureVisible(find.text('Stop'));
    await tester.tap(find.text('Stop'));
    await settle(tester);
    expect(find.text('Stop this import?'), findsOneWidget);
    expect(server.stopped, isEmpty);
    await tester.tap(find.text('Keep going'));
    await settle(tester);
    expect(server.stopped, isEmpty);

    await tester.tap(find.text('Stop'));
    await settle(tester);
    await tester.tap(find.descendant(
        of: find.byType(AlertDialog), matching: find.text('Stop')));
    await settle(tester);

    expect(server.stopped, ['aaaaaaaaaaaa']);
    expect(find.text('Stopped. 2 songs added.'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'Home shows an import that is running even before the library '
      'has a song', (tester) async {
    server.jobs = [running(done: 1)];
    final app = await open(tester, route: false);
    await app.db.delete(app.db.tracks).go();
    await settle(tester);

    expect(find.text('Your library will show up here'), findsOneWidget,
        reason: 'the library is empty, as for somebody who just joined');
    expect(find.text('Evening drive'), findsOneWidget);
    expect(find.text('1 of 3 songs - about 2 minutes left'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets('Home announces a finished import once and lets it be closed',
      (tester) async {
    server.jobs = [finished(missing: 0)];
    final app = await open(tester, route: false);

    expect(find.text('Road trip'), findsOneWidget);
    await tester.tap(find.byTooltip('Got it'));
    await settle(tester);
    expect(find.text('Road trip'), findsNothing);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'where songs can be played on request, the download service '
      'sheet is never offered', (tester) async {
    SharedPreferences.setMockInitialValues({});
    final app = await pumpApp(
      tester,
      size: const Size(390, 1600),
      overrides: [
        playlistImportBackendProvider.overrideWithValue(null),
        fetchInfoProvider.overrideWith((ref) async =>
            const FetchServiceInfo(features: ['play-now', 'prepare'])),
        fetchServiceProvider
            .overrideWith((ref) async => Uri.parse('https://x.example/fetch')),
        instantAvailableProvider.overrideWithValue(true),
      ],
    );
    final element = tester.element(find.byType(Scaffold).first);
    unawaited(GoRouter.of(element).push<void>('/settings/import'));
    await settle(tester);

    expect(find.textContaining('needs an update'), findsOneWidget);
    expect(find.textContaining('Connect'), findsNothing);
    expect(find.textContaining('download service'), findsNothing);
    await closeApp(tester, app.db);
  });

  group('a file instead of a link', () {
    const spotifyPlaylists = '''
{"playlists": [
  {"name": "Evening drive", "items": [
    {"track": {"trackName": "Burden", "artistName": "Opeth", "albumName": "W"}},
    {"track": {"trackName": "Harvest", "artistName": "Opeth", "albumName": "S"}}]},
  {"name": "Gym", "items": [
    {"track": {"trackName": "Chopped in Half", "artistName": "Obituary"}}]}]}''';
    const spotifyLibrary =
        '{"tracks": [{"artist": "Opeth", "album": "D", "track": "Windowpane"}]}';

    testWidgets(
        'a Spotify download with several lists lets the person tick what '
        'to bring, and each becomes its own import in order', (tester) async {
      picker.files = const [
        PickedFile(name: 'Playlist1.json', text: spotifyPlaylists),
        PickedFile(name: 'YourLibrary.json', text: spotifyLibrary),
      ];
      final app = await open(tester);

      await tester.ensureVisible(find.byKey(const Key('import-file')));
      await tester.tap(find.byKey(const Key('import-file')));
      await settle(tester);

      expect(find.text('3 lists in your file'), findsOneWidget);
      expect(find.text('Liked songs'), findsOneWidget);
      expect(find.text('1 song - liked, no playlist'), findsOneWidget);
      expect(find.text('Import 3 lists (4 songs)'), findsOneWidget);
      expect(server.started, isEmpty);

      await tester.tap(find.byKey(const Key('import-entry-2')));
      await settle(tester);
      expect(find.text('Import 2 lists (3 songs)'), findsOneWidget);
      await tester.tap(find.byKey(const Key('import-start-chosen')));
      await settle(tester);

      expect(server.started, [
        (name: 'Liked songs', source: 'file', liked: true, songs: 1),
        (name: 'Evening drive', source: 'file', liked: false, songs: 2),
      ]);
      // The first of them opens at once, every song on it; the other is next.
      expect(find.byKey(const Key('imported-song-0')), findsOneWidget);
      await closeApp(tester, app.db);
    });

    testWidgets('one list goes to the same review as a link', (tester) async {
      picker.files = const [
        PickedFile(
          name: 'Death_Metal.csv',
          text: 'Track Name,Artist Name(s),Duration (ms)\n'
              'Chopped in Half,Obituary,225000\n',
        ),
      ];
      final app = await open(tester);

      await tester.ensureVisible(find.byKey(const Key('import-file')));
      await tester.tap(find.byKey(const Key('import-file')));
      await settle(tester);

      expect(find.text('1 song from your file'), findsOneWidget);
      expect(
          tester
              .widget<TextField>(find.byKey(const Key('import-name')))
              .controller!
              .text,
          'Death Metal');
      await closeApp(tester, app.db);
    });

    testWidgets('a file that is not a list of songs says so and adds nothing',
        (tester) async {
      picker.files = const [PickedFile(name: 'photo.txt', text: 'hello')];
      final app = await open(tester);

      await tester.ensureVisible(find.byKey(const Key('import-file')));
      await tester.tap(find.byKey(const Key('import-file')));
      await settle(tester);

      expect(find.textContaining('does not look like a list of songs'),
          findsOneWidget);
      expect(server.started, isEmpty);
      await closeApp(tester, app.db);
    });

    testWidgets('backing out of the file chooser changes nothing',
        (tester) async {
      picker.files = null;
      final app = await open(tester);

      await tester.ensureVisible(find.byKey(const Key('import-file')));
      await tester.tap(find.byKey(const Key('import-file')));
      await settle(tester);

      expect(find.byKey(const Key('import-error')), findsNothing);
      expect(find.byKey(const Key('import-review')), findsNothing);
      await closeApp(tester, app.db);
    });

    testWidgets('a file that cannot be read says why', (tester) async {
      picker.problem =
          const FilePickProblem('That file is too big to be a list of songs.');
      final app = await open(tester);

      await tester.ensureVisible(find.byKey(const Key('import-file')));
      await tester.tap(find.byKey(const Key('import-file')));
      await settle(tester);

      expect(find.text('That file is too big to be a list of songs.'),
          findsOneWidget);
      await closeApp(tester, app.db);
    });
  });

  group('the end of an import, in the shade', () {
    test('a finished import is announced once, and only if it was running',
        () async {
      final shown = <AlertNotification>[];
      final notifications = _Notifications(shown);
      final container = makeContainer(overrides: [
        playlistImportBackendProvider.overrideWithValue(server),
        localNotificationsProvider.overrideWithValue(notifications),
      ]);
      addTearDown(container.dispose);
      server.jobs = [running(done: 2)];
      final controller = container.read(importsProvider.notifier);
      await controller.refresh();
      expect(shown, isEmpty);

      server.jobs = [finished(missing: 0)]
          .map((j) => ImportJob(
                id: 'aaaaaaaaaaaa',
                name: j.name,
                kind: j.kind,
                state: j.state,
                total: j.total,
                done: j.done,
                added: j.added,
                missing: j.missing,
                message: j.message,
              ))
          .toList();
      await controller.refresh();
      await controller.refresh();

      expect(shown, hasLength(1));
      expect(shown.single.title, '"Road trip" is ready');
      expect(shown.single.route, '/settings/import');
    });

    test('imports found finished at start-up are not announced again',
        () async {
      final shown = <AlertNotification>[];
      final container = makeContainer(overrides: [
        playlistImportBackendProvider.overrideWithValue(server),
        localNotificationsProvider.overrideWithValue(_Notifications(shown)),
      ]);
      addTearDown(container.dispose);
      server.jobs = [finished()];
      await container.read(importsProvider.notifier).refresh();
      expect(shown, isEmpty);
      expect(container.read(importsProvider).jobs, hasLength(1));
    });
  });
}

class _Picker implements SongFilePicker {
  List<PickedFile>? files;
  FilePickProblem? problem;

  @override
  Future<List<PickedFile>?> pick() async {
    final problem = this.problem;
    if (problem != null) throw problem;
    return files;
  }
}

class _Notifications extends LocalNotifications {
  _Notifications(this.shown);

  final List<AlertNotification> shown;

  @override
  Future<void> show(AlertNotification notification) async =>
      shown.add(notification);
}
