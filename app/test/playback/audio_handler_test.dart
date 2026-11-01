import 'dart:async';

import 'package:audio_service/audio_service.dart';
import 'package:drift/native.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/features/player/playback_facade.dart';
import 'package:encore/playback/encore_audio_handler.dart';
import 'package:encore/playback/library_browser.dart';
import 'package:encore/playback/queue_model.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/test_app.dart';

void main() {
  late AppDatabase db;
  late FakePlaybackFacade facade;
  late EncoreAudioHandler handler;
  late int serverId;

  setUp(() async {
    db = AppDatabase(NativeDatabase.memory());
    serverId = await Seed.library(db);
    facade = FakePlaybackFacade();
    handler = EncoreAudioHandler()
      ..attach(
        facade,
        browser: DbLibraryBrowser(db: db, serverId: serverId),
        coverArt: (id) async => Uri.parse('https://srv/cover/$id'),
      );
  });

  tearDown(() => db.close());

  test('starts idle', () {
    expect(
        handler.playbackState.value.processingState, AudioProcessingState.idle);
    expect(handler.mediaItem.value, isNull);
  });

  test('mirrors the playing track into the media session', () async {
    facade.emit(samplePlaying());
    await pumpEventQueue();

    final item = handler.mediaItem.value!;
    expect(item.title, 'Opening The');
    expect(item.artist, 'Periphery');
    expect(item.duration, const Duration(minutes: 3, seconds: 20));

    final state = handler.playbackState.value;
    expect(state.playing, isTrue);
    expect(state.controls.map((c) => c.action), [
      MediaAction.skipToPrevious,
      MediaAction.pause,
      MediaAction.skipToNext,
    ]);
    expect(state.queueIndex, 0);
  });

  test(
      'the next song\'s title reaches the lock screen and the notification at once, however long its cover takes (field test 2026-10-31)',
      () async {
    final never = Completer<Uri?>();
    final slow = EncoreAudioHandler()
      ..attach(facade, coverArt: (_) => never.future);

    facade.emit(samplePlaying());
    await pumpEventQueue();
    expect(slow.mediaItem.value?.title, 'Opening The');

    facade.emit(PlaybackSnapshot(
      track: const NowPlayingTrack(
        id: 'al3-t2',
        title: 'Next Song',
        artist: 'Periphery',
        album: 'The Walk',
        albumId: 'al3',
        artistId: 'ar2',
        suffix: 'flac',
        bitRate: 900,
        duration: Duration(minutes: 4),
        coverArt: 'al3',
      ),
      isPlaying: true,
      duration: const Duration(minutes: 4),
      queueIndex: 1,
      queueLength: 5,
      hasNext: true,
      sourceName: 'The Walk',
    ));
    await pumpEventQueue();

    expect(slow.mediaItem.value?.title, 'Next Song',
        reason: 'the title does not wait for the cover');
    expect(slow.mediaItem.value?.artUri, isNull,
        reason: 'and the previous song\'s cover is not kept under it');
  });

  test('shows a play button when paused', () async {
    facade.emit(samplePlaying(isPlaying: false));
    await pumpEventQueue();
    expect(handler.playbackState.value.playing, isFalse);
    expect(handler.playbackState.value.controls[1].action, MediaAction.play);
  });

  test('transport commands go to the engine', () async {
    await handler.play();
    await handler.pause();
    await handler.skipToNext();
    await handler.skipToPrevious();
    await handler.seek(const Duration(seconds: 30));
    expect(facade.calls, ['play', 'pause', 'next', 'previous', 'seek(30000)']);
  });

  test('Android Auto root lists the shelves', () async {
    final items = await handler.getChildren(AudioService.browsableRootId);
    expect(items.map((i) => i.title), contains('Playlists'));
    expect(items.map((i) => i.title), contains('Liked songs'));
  });

  test('an album shelf resolves artwork for every entry', () async {
    final items = await handler.getChildren(BrowseIds.albums);
    expect(items, isNotEmpty);
    expect(items.every((i) => i.artUri != null), isTrue);
  });

  test('choosing a song in the car queues the whole album', () async {
    await handler.playFromMediaId('track:al3-t2@album:al3');
    expect(
      facade.calls,
      contains('playTracks(5, start=1, source=The Walk, shuffle=false)'),
    );
  });

  test('voice search plays the best match', () async {
    await handler.playFromSearch('Periphery');
    expect(facade.calls.single, startsWith('playTracks('));
  });

  // docs/23, B12: when the car starts the app cold, the browse request arrives
  // before the database, the server id and the engine are ready. It used to be
  // answered with an empty list and never refreshed.
  group('a car that connects before the library is ready', () {
    late List<String> changed;
    late EncoreAudioHandler bare;

    setUp(() {
      changed = [];
      bare = EncoreAudioHandler(
        browseWait: const Duration(milliseconds: 80),
        onChildrenChanged: changed.add,
      );
    });

    test('is shown the top level at once, which needs no database', () async {
      final root = await bare.getChildren(AudioService.browsableRootId);

      expect(root.map((i) => i.title),
          containsAll(['Playlists', 'Albums', 'Artists', 'Liked songs']));
      expect(root.every((i) => i.playable == false), isTrue);
    });

    test('is answered a deeper level once the library arrives', () async {
      final pending = bare.getChildren(BrowseIds.albums);

      bare.setBrowser(DbLibraryBrowser(db: db, serverId: serverId));

      expect(await pending, isNotEmpty,
          reason: 'it waited for the library instead of answering "empty"');
    });

    test('is not kept waiting for ever: an empty list after the wait',
        () async {
      expect(await bare.getChildren(BrowseIds.albums), isEmpty);
    });

    test('is told the list changed when the library attaches', () async {
      expect(changed, isEmpty);

      bare.setBrowser(DbLibraryBrowser(db: db, serverId: serverId));

      expect(changed, [AudioService.browsableRootId]);
    });

    test('can choose a song straight away: it plays once the engine is ready',
        () async {
      final choosing = bare.playFromMediaId(BrowseIds.album('al1'));

      bare.attach(facade,
          browser: DbLibraryBrowser(db: db, serverId: serverId));
      await choosing;

      expect(facade.calls.any((c) => c.startsWith('playTracks(')), isTrue);
    });

    test('a choice made when nothing ever arrives does nothing, quietly',
        () async {
      await bare.playFromMediaId('track:x');
      await bare.playFromSearch('anything');
    });
  });

  group('the queue shown in the car (B16)', () {
    List<QueueItem> songs(int n) => [
          for (var i = 0; i < n; i++)
            QueueItem.preview(
                uid: i,
                id: 's$i',
                title: 'Song $i',
                uri: Uri.parse('https://x/$i')),
        ];

    PlaybackSnapshot playingAt(int index, int length) => PlaybackSnapshot(
          track: NowPlayingTrack(
            id: 's$index',
            title: 'Song $index',
            duration: const Duration(minutes: 3),
          ),
          isPlaying: true,
          duration: const Duration(minutes: 3),
          queueIndex: index,
          queueLength: length,
        );

    test(
        'the playing song is highlighted inside the window, not by its '
        'place in the whole queue', () async {
      facade.emitQueue(QueueSnapshot(items: songs(200), currentIndex: 120));
      facade.emit(playingAt(120, 200));
      await pumpEventQueue();

      final window = handler.queue.value;
      expect(window.first.id, 's120', reason: 'the window starts at the song');
      final shown = handler.playbackState.value.queueIndex;
      expect(shown, isNotNull);
      expect(window[shown!].id, 's120',
          reason: 'the car highlights the entry at this position');
    });

    test('moving on keeps the highlight on the playing song', () async {
      facade.emitQueue(QueueSnapshot(items: songs(200), currentIndex: 10));
      facade.emit(playingAt(10, 200));
      await pumpEventQueue();
      facade.emitQueue(QueueSnapshot(items: songs(200), currentIndex: 11));
      facade.emit(playingAt(11, 200));
      await pumpEventQueue();

      final window = handler.queue.value;
      expect(window[handler.playbackState.value.queueIndex!].id, 's11');
    });

    test('choosing an entry in the car jumps to that song', () async {
      facade.emitQueue(QueueSnapshot(items: songs(200), currentIndex: 120));
      await pumpEventQueue();
      await handler.skipToQueueItem(3);
      expect(facade.calls, contains('jump(123)'));
    });

    test('a repeat mode is set directly, without stepping through the others',
        () async {
      await handler.setRepeatMode(AudioServiceRepeatMode.one);
      facade.emit(const PlaybackSnapshot(repeat: RepeatKind.one));
      await handler.setRepeatMode(AudioServiceRepeatMode.one); // already so
      await handler.setRepeatMode(AudioServiceRepeatMode.all);
      facade.emit(const PlaybackSnapshot(repeat: RepeatKind.all));
      await handler.setRepeatMode(AudioServiceRepeatMode.none);
      expect(
        facade.calls.where((c) => c.startsWith('setRepeat') || c == 'repeat'),
        ['setRepeat(one)', 'setRepeat(all)', 'setRepeat(off)'],
      );
    });
  });

  test('detaching stops mirroring', () async {
    handler.detach();
    facade.emit(samplePlaying());
    await pumpEventQueue();
    expect(handler.mediaItem.value, isNull);
  });
}
