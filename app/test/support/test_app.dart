import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:drift/drift.dart';
import 'package:drift/native.dart';
import 'package:encore/app/app.dart';
import 'package:encore/app/playback_providers.dart';
import 'package:encore/app/providers.dart';
import 'package:encore/app/session.dart';
import 'package:encore/core/clock.dart';
import 'package:encore/data/auth/credential_store.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/features/downloads/download_providers.dart';
import 'package:encore/features/downloads/lyrics_for_downloads.dart';
import 'package:encore/features/player/lyrics_prefetch.dart';
import 'package:encore/features/player/playback_facade.dart';
import 'package:encore/features/providers.dart';
import 'package:encore/features/requests/request_providers.dart';
import 'package:encore/playback/equalizer_service.dart';
import 'package:encore/playback/queue_model.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';

import 'fake_catalogue.dart';

/// Controllable playback facade for UI tests.
class FakePlaybackFacade implements PlaybackFacade {
  FakePlaybackFacade([PlaybackSnapshot initial = PlaybackSnapshot.idle])
      : _snapshot = initial;

  PlaybackSnapshot _snapshot;
  final _controller = StreamController<PlaybackSnapshot>.broadcast();
  final _position = StreamController<Duration>.broadcast();
  final List<String> calls = [];

  /// Whether anything is still subscribed to the snapshots (leak checks).
  bool get hasSnapshotListeners => _controller.hasListener;

  /// What [sleepTimer] reports (the real engine can have one running).
  SleepTimerStatus sleep = SleepTimerStatus.off;

  void emit(PlaybackSnapshot s) {
    _snapshot = s;
    _controller.add(s);
  }

  void emitPosition(Duration d) => _position.add(d);

  @override
  PlaybackSnapshot get snapshot => _snapshot;
  @override
  Stream<PlaybackSnapshot> get snapshots => _controller.stream;
  @override
  Stream<Duration> get positionStream => _position.stream;

  /// When on, the play calls below also keep [queue] up to date (and
  /// announce it), the way the real engine does; [advance] moves to the next
  /// song. Off by default so screens that only care about calls stay simple.
  bool simulateQueue = false;
  int _uid = 0;

  void _simulate(List<QueueItem> Function(List<QueueItem> items) change,
      {int? current}) {
    if (!simulateQueue) return;
    emitQueue(QueueSnapshot(
      items: change([...queueState.items]),
      currentIndex: current ?? queueState.currentIndex,
    ));
  }

  /// The player moved on to the next song.
  void advance() => emitQueue(QueueSnapshot(
        items: queueState.items,
        currentIndex: queueState.currentIndex + 1,
      ));

  @override
  Future<void> playTracks(List<TrackRow> tracks,
      {int startIndex = 0,
      String? sourceName,
      String? sourceId,
      bool shuffle = false}) async {
    calls.add('playTracks(${tracks.length}, start=$startIndex, '
        'source=$sourceName, shuffle=$shuffle)');
    _simulate(
      (_) => [for (final t in tracks) QueueItem.fromTrack(t, uid: ++_uid)],
      current: startIndex,
    );
  }

  @override
  Future<void> togglePlayPause() async => calls.add('toggle');
  @override
  Future<void> play() async => calls.add('play');
  @override
  Future<void> pause() async => calls.add('pause');
  @override
  Future<void> seek(Duration position) async =>
      calls.add('seek(${position.inMilliseconds})');
  @override
  Future<void> skipNext() async => calls.add('next');
  @override
  Future<void> skipPrevious() async => calls.add('previous');
  @override
  void toggleShuffle() => calls.add('shuffle');
  @override
  void cycleRepeat() => calls.add('repeat');
  @override
  void setRepeat(RepeatKind kind) => calls.add('setRepeat(${kind.name})');
  @override
  Future<void> addToQueue(TrackRow track) async {
    calls.add('queue(${track.id})');
    _simulate((items) => [...items, QueueItem.fromTrack(track, uid: ++_uid)]);
  }

  @override
  Future<void> playNext(TrackRow track) async => calls.add('next(${track.id})');

  @override
  Future<void> playPreview({
    required String id,
    required String title,
    required Uri uri,
    String? artist,
    String? catalogueArtistId,
    String? album,
    String? imageUrl,
    Duration? duration,
  }) async =>
      calls.add('preview($id)');
  @override
  Future<void> playPreviews(
    List<PreviewTrack> tracks, {
    int startIndex = 0,
    String? sourceName,
    String? sourceId,
  }) async {
    calls.add('previews(${tracks.map((t) => t.id).join(',')}, '
        'start=$startIndex)');
    _simulate(
      (_) => [
        for (final t in tracks)
          QueueItem.preview(uid: ++_uid, id: t.id, title: t.title, uri: t.uri),
      ],
      current: startIndex,
    );
  }

  @override
  Future<void> addStreamToQueue(PreviewTrack track) async {
    calls.add('queueStream(${track.id})');
    _simulate((items) => [
          ...items,
          QueueItem.preview(
              uid: ++_uid, id: track.id, title: track.title, uri: track.uri),
        ]);
  }

  QueueSnapshot queueState = QueueSnapshot.empty;
  final _queues = StreamController<QueueSnapshot>.broadcast();
  void emitQueue(QueueSnapshot q) {
    queueState = q;
    _queues.add(q);
  }

  @override
  QueueSnapshot get queue => queueState;
  @override
  Stream<QueueSnapshot> get queueStream => _queues.stream;
  @override
  Future<void> jumpToQueueIndex(int index) async => calls.add('jump($index)');
  @override
  Future<void> removeFromQueue(int index) async => calls.add('remove($index)');
  @override
  Future<void> moveInQueue(int from, int to) async =>
      calls.add('move($from,$to)');
  @override
  Future<void> clearUpNext() async => calls.add('clearUpNext');
  @override
  Future<void> stopAndClear() async {
    calls.add('stopAndClear');
    queueState = QueueSnapshot.empty;
  }

  @override
  SleepTimerStatus get sleepTimer => sleep;
  @override
  Stream<SleepTimerStatus> get sleepTimerStream => const Stream.empty();
  @override
  Future<void> setSleepTimer(Duration? duration) async =>
      calls.add('sleep(${duration?.inMinutes})');
  @override
  Future<void> setSleepAtEndOfTrack(bool enabled) async =>
      calls.add('sleepEnd($enabled)');
  @override
  double get speed => 1;
  @override
  Future<void> setSpeed(double speed) async => calls.add('speed($speed)');
  @override
  Stream<PlaybackNotice> get notices => _notices.stream;

  final _notices = StreamController<PlaybackNotice>.broadcast();

  /// The engine told the person something (an error, a stop).
  void emitNotice(PlaybackNotice notice) => _notices.add(notice);
}

/// A realistic little library, deterministic.
class Seed {
  static Future<int> library(AppDatabase db) async {
    final serverId = await db.into(db.servers).insert(ServersCompanion.insert(
          name: 'Home server',
          username: 'marwa',
          endpointsJson: jsonEncode([
            {'label': 'Home', 'url': 'http://192.168.1.10:4533'}
          ]),
          createdAtMs: 0,
        ));

    const artists = [
      ('ar1', 'Alcest'),
      ('ar2', 'Periphery'),
      ('ar3', 'Opeth'),
      ('ar4', 'Katatonia'),
    ];
    for (final (id, name) in artists) {
      await db.into(db.artists).insert(ArtistsCompanion.insert(
          serverId: serverId, id: id, name: name, albumCount: const Value(2)));
    }

    const albums = [
      ('al1', 'Kodama', 'ar1', 'Alcest', 2016, 'Blackgaze'),
      ('al2', 'Les Voyages de l’âme', 'ar1', 'Alcest', 2012, 'Blackgaze'),
      ('al3', 'The Walk', 'ar2', 'Periphery', 2023, 'Progressive Metal'),
      ('al4', 'Ghost Reveries', 'ar3', 'Opeth', 2005, 'Progressive Metal'),
      ('al5', 'Sky Void of Stars', 'ar4', 'Katatonia', 2023, 'Gothic Metal'),
      ('al6', 'Blackwater Park', 'ar3', 'Opeth', 2001, 'Progressive Metal'),
    ];
    for (var i = 0; i < albums.length; i++) {
      final (id, name, artistId, artist, year, genre) = albums[i];
      await db.into(db.albums).insert(AlbumsCompanion.insert(
            serverId: serverId,
            id: id,
            name: name,
            artistId: Value(artistId),
            artist: Value(artist),
            year: Value(year),
            genre: Value(genre),
            coverArt: Value('al-$id'),
            songCount: const Value(5),
            durationSec: const Value(1500),
            createdAtMs: Value(1700000000000 + i * 86400000),
          ));
      for (var t = 1; t <= 5; t++) {
        await db.into(db.tracks).insert(TracksCompanion.insert(
              serverId: serverId,
              id: '$id-t$t',
              title: '${[
                'Opening',
                'Echoes',
                'Hollow',
                'Tides',
                'Closing'
              ][t - 1]} '
                  '${name.split(' ').first}',
              albumId: Value(id),
              artistId: Value(artistId),
              album: Value(name),
              artist: Value(artist),
              trackNo: Value(t),
              durationSec: Value(180 + t * 20),
              suffix: Value(t.isEven ? 'flac' : 'mp3'),
              bitRate: Value(t.isEven ? 900 : 320),
            ));
      }
    }

    // Playlists: two user playlists (one without cover => mosaic) + 2 smart.
    Future<void> playlist(String id, String name,
        {bool smart = false,
        List<String> tracks = const [],
        String? comment}) async {
      await db.into(db.playlists).insert(PlaylistsCompanion.insert(
            serverId: serverId,
            id: id,
            name: name,
            comment: Value(comment),
            readonly: Value(smart),
            owner: const Value('marwa'),
            songCount: Value(tracks.length),
            changedAtMs: const Value(1700000000000),
            entriesFetchedAtMs: const Value(1700000000000),
          ));
      for (var i = 0; i < tracks.length; i++) {
        await db
            .into(db.playlistEntries)
            .insert(PlaylistEntriesCompanion.insert(
              serverId: serverId,
              playlistId: id,
              position: i,
              trackId: tracks[i],
            ));
      }
    }

    await playlist('pl1', 'Prog Snob',
        tracks: ['al3-t1', 'al3-t2', 'al4-t1', 'al5-t3', 'al6-t2', 'al1-t4']);
    await playlist('pl2', 'Late night', tracks: ['al1-t1', 'al2-t3', 'al2-t4']);
    await playlist('pl3', 'Phone Offline',
        smart: true,
        comment: 'The set to keep on the phone.',
        tracks: ['al3-t3', 'al4-t5', 'al5-t1']);
    await playlist('pl4', 'Rediscover',
        smart: true, comment: 'Songs you loved before.', tracks: ['al6-t1']);

    // Server "recently played" list.
    await db.into(db.recommendationsCache).insert(
          RecommendationsCacheCompanion.insert(
            serverId: serverId,
            key: 'server.recent',
            payloadJson: jsonEncode(['al3', 'al1', 'al4']),
            computedAtMs: 0,
          ),
        );
    await db.into(db.recommendationsCache).insert(
          RecommendationsCacheCompanion.insert(
            serverId: serverId,
            key: 'server.frequent',
            payloadJson: jsonEncode(['al6', 'al2']),
            computedAtMs: 0,
          ),
        );

    // One liked song.
    await (db.update(db.tracks)..where((t) => t.id.equals('al3-t1')))
        .write(const TracksCompanion(starredAtMs: Value(1700000000000)));
    return serverId;
  }
}

/// Loads the bundled font so goldens show real glyphs, not boxes.
Future<void> loadAppFonts() async {
  final loader = FontLoader('Figtree');
  for (final w in const [
    'Regular',
    'Medium',
    'SemiBold',
    'Bold',
    'ExtraBold',
  ]) {
    loader.addFont(rootBundle.load('assets/fonts/Figtree-$w.ttf'));
  }
  await loader.load();

  // Material icons are not registered in the headless test engine; without
  // them every icon renders as a box and goldens are misleading.
  final flutterRoot = Platform.environment['FLUTTER_ROOT'];
  if (flutterRoot != null) {
    final icons = File(
      '$flutterRoot/bin/cache/artifacts/material_fonts/MaterialIcons-Regular.otf',
    );
    if (icons.existsSync()) {
      final bytes = icons.readAsBytesSync();
      final iconLoader = FontLoader('MaterialIcons')
        ..addFont(
            Future.value(ByteData.sublistView(Uint8List.fromList(bytes))));
      await iconLoader.load();
    }
  }
}

/// The harness defaults minus any provider the test overrides itself.
/// Riverpod refuses two overrides of the same provider in one scope
/// ("Tried to override a provider twice"), so a test's own override must
/// replace the default rather than sit next to it.
List<Override> _withDefaults(List<Override> defaults, List<Override> mine) {
  // `origin` is public API meant for tests.
  // ignore: invalid_use_of_visible_for_testing_member
  final replaced = {for (final o in mine) o.origin};
  return [
    for (final d in defaults)
      // ignore: invalid_use_of_visible_for_testing_member
      if (!replaced.contains(d.origin)) d,
    ...mine,
  ];
}

/// Pumps the real app (router, shell, theme) over a seeded in-memory DB.
Future<({AppDatabase db, FakePlaybackFacade facade, int serverId})> pumpApp(
  WidgetTester tester, {
  bool seeded = true,
  PlaybackSnapshot? playing,
  List<Override> overrides = const [],
  Size size = const Size(390, 844),

  /// Builds the network session; the default is "no session" (offline UI).
  Future<ServerSession?> Function(Ref ref)? session,

  /// Leaves the UI's player to the app (the Jam-aware one over the fake
  /// player) instead of replacing it with the fake: for tests of a Jam.
  bool jamAware = false,
}) async {
  tester.view.physicalSize = size * 3;
  tester.view.devicePixelRatio = 3;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  final db = AppDatabase(NativeDatabase.memory());
  final serverId = seeded ? await Seed.library(db) : 0;
  final facade = FakePlaybackFacade(playing ?? PlaybackSnapshot.idle);

  await tester.pumpWidget(
    ProviderScope(
      retry: (_, __) => null,
      overrides: _withDefaults([
        databaseProvider.overrideWithValue(db),
        // A fixed evening: the greeting and "synced 5 min ago" labels must
        // not make goldens depend on when the suite runs.
        clockProvider.overrideWithValue(FakeClock(DateTime(2026, 10, 15, 21))),
        credentialStoreProvider.overrideWithValue(InMemoryCredentialStore()),
        enginePlaybackFacadeProvider.overrideWithValue(facade),
        if (!jamAware) playbackFacadeProvider.overrideWithValue(facade),
        // No session in UI tests: artwork falls back to gradients/mosaics.
        sessionProvider.overrideWith(
          (ref) => session == null ? Future.value(null) : session(ref),
        ),
        // Deterministic visuals: gradients/mosaics instead of network images.
        coverArtResolverProvider.overrideWithValue(null),
        connectivityProvider.overrideWith((ref) => Stream.value(true)),
        // Background workers that need real platform channels / network.
        downloadManagerProvider.overrideWith((ref) async => null),
        lyricsPrefetchProvider.overrideWith((ref) {}),
        lyricsForDownloadsProvider.overrideWith((ref) {}),
        // Never reach the public catalogue or the connectivity plugin from UI
        // tests: they used to stay deterministic only because flutter_test
        // answers every HTTP request with 400 and the plugin is absent. A test
        // that needs results passes its own FakeCatalogue in [overrides].
        coverFallbackRepositoryProvider.overrideWithValue(null),
        catalogueClientProvider.overrideWithValue(FakeCatalogue()),
        // The real equaliser needs the platform audio backend (only bootstrap()
        // provides it); a test of the start-up wiring replaces this spy-free default.
        equalizerServiceProvider.overrideWith((ref) => EqualizerService(null)),
        networkKindProvider
            .overrideWith((ref) => Stream.value(NetworkKind.wifi)),
      ], overrides),
      child: const EncoreApp(),
    ),
  );
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 100));
  return (db: db, facade: facade, serverId: serverId);
}

/// Settles streams and animations without waiting on endless indicators.
Future<void> settle(WidgetTester tester) async {
  for (var i = 0; i < 6; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

PlaybackSnapshot samplePlaying({bool isPlaying = true}) => PlaybackSnapshot(
      track: const NowPlayingTrack(
        id: 'al3-t1',
        title: 'Opening The',
        artist: 'Periphery',
        album: 'The Walk',
        albumId: 'al3',
        artistId: 'ar2',
        suffix: 'flac',
        bitRate: 900,
        duration: Duration(minutes: 3, seconds: 20),
      ),
      isPlaying: isPlaying,
      duration: const Duration(minutes: 3, seconds: 20),
      queueIndex: 0,
      queueLength: 5,
      hasNext: true,
      sourceName: 'The Walk',
    );

/// Unmounts the app and lets Drift's stream-cleanup timers fire so the test
/// framework's "no pending timers" invariant holds.
Future<void> closeApp(WidgetTester tester, AppDatabase db) async {
  await tester.pumpWidget(const SizedBox.shrink());
  await tester.pump(const Duration(milliseconds: 50));
  await db.close();
  await tester.pump(const Duration(milliseconds: 50));
}
