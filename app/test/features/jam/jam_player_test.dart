import 'dart:async';

import 'package:encore/core/result.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/domain/lyrics.dart';
import 'package:encore/features/common/widgets.dart' show PlayButton;
import 'package:encore/features/jam/jam_providers.dart';
import 'package:encore/features/jam/jam_speaker.dart';
import 'package:encore/features/jam/jam_wiring.dart';
import 'package:encore/features/player/lyrics_screen.dart'
    show currentLyricsProvider;
import 'package:encore/features/player/now_playing_screen.dart';
import 'package:encore/features/providers.dart';
import 'package:encore_session/encore_session.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import '../../support/factories.dart';
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

/// The owner and a friend, on real phones (docs/39 F4, F5): "I expected a normal
/// player screen, a normal queue like when I listen alone". In a Jam the app's
/// own player, mini-player and queue are the Jam's.
void main() {
  setUpAll(loadAppFonts);

  late FakeJamApi api;
  late ProviderContainer container;

  const owner = Member(id: 'owner', name: 'owner', role: Role.host);
  const mia = Member(id: 'mia', name: 'mia');

  const sommaire = QueueEntry(
      uid: 1, trackId: 'a', addedBy: 'mia', title: 'Sommaire', artist: 'Raid');
  const kodama = QueueEntry(
      uid: 2,
      trackId: 'b',
      addedBy: 'owner',
      title: 'Opening Kodama',
      artist: 'Alcest');
  const hollow = QueueEntry(
      uid: 3,
      trackId: 'c',
      addedBy: 'mia',
      title: 'Hollow Ghost',
      artist: 'Opeth');

  SessionState session({
    List<QueueEntry> queue = const [sommaire, kodama, hollow],
    int index = 0,
    bool playing = true,
    int rev = 5,
    String? player,
  }) =>
      SessionState(
          rev: rev,
          members: const [owner, mia],
          queue: queue,
          index: index,
          playing: playing,
          playerDeviceId: player);

  Future<({AppDatabase db, FakePlaybackFacade engine})> open(
    WidgetTester tester, {
    List<Override> overrides = const [],
  }) async {
    api = FakeJamApi();
    final app = await pumpApp(tester,
        size: const Size(390, 1800),
        jamAware: true,
        overrides: [
          jamApiProvider.overrideWith((ref) async => api),
          jamBackoffProvider
              .overrideWithValue(const [Duration(milliseconds: 1)]),
          jamClockEveryProvider.overrideWithValue(const Duration(days: 1)),
          jamSongPlayerProvider.overrideWithValue(_AlwaysPlays()),
          ...overrides,
        ]);
    final element = tester.element(find.byType(Scaffold).first);
    container = ProviderScope.containerOf(element);
    unawaited(GoRouter.of(element).push<void>('/home/jam'));
    await settle(tester);
    await tester.tap(find.text('Start a Jam'));
    await settle(tester);
    api.pushState(session());
    await settle(tester);
    return (db: app.db, engine: app.facade);
  }

  testWidgets('the mini-player shows the Jam\'s song, with the usual buttons',
      (tester) async {
    final app = await open(tester);

    expect(find.text('Sommaire'), findsWidgets);
    final button = tester.widget<PlayButton>(find.byType(PlayButton).first);
    expect(button.isPlaying, isTrue,
        reason: 'the Jam is playing: it offers to pause');
    await closeApp(tester, app.db);
  });

  testWidgets(
      'its pause button pauses the Jam for everybody, not just this phone',
      (tester) async {
    final app = await open(tester);
    api.commandAnswer = Result.ok(session(playing: false, rev: 6));

    await tester.tap(find.byType(PlayButton).first);
    await settle(tester);

    expect(api.commands.last.$2, isA<Pause>(),
        reason: 'the button speaks to the Jam; the phone that plays then '
            'pauses because the Jam says so');
    await closeApp(tester, app.db);
  });

  testWidgets('the full player is the ordinary one, with the Jam\'s song',
      (tester) async {
    final app = await open(tester);

    await tester.tap(find.text('Sommaire').last);
    await settle(tester);

    expect(find.byType(NowPlayingScreen), findsOneWidget);
    expect(find.text('Raid'), findsWidgets);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'the queue is the Jam\'s, and a song can be removed from it by '
      'swiping, as when listening alone', (tester) async {
    final app = await open(tester);
    await tester.tap(find.text('Sommaire').last);
    await settle(tester);
    await tester.tap(find.byTooltip('Queue'));
    await settle(tester);

    expect(find.text('Opening Kodama'), findsOneWidget);
    expect(find.text('Hollow Ghost'), findsOneWidget);
    api.commandAnswer =
        Result.ok(session(queue: const [sommaire, hollow], rev: 6));
    await tester.drag(find.text('Opening Kodama'), const Offset(-500, 0));
    await settle(tester);

    expect((api.commands.last.$2 as Remove).uid, 2);
    await closeApp(tester, app.db);
  });

  testWidgets('a song played from the library while in a Jam plays in the Jam',
      (tester) async {
    final app = await open(tester);
    api.commandAnswer = Result.ok(session(rev: 6));

    // What a tap on a song of an album does: it asks the person's player.
    await container.read(playbackFacadeProvider).playTracks([
      trackRow('al1-t1', title: 'Opening Kodama', artist: 'Alcest'),
    ]);
    await settle(tester);

    final add = api.commands.last.$2 as Add;
    expect(add.at, AddAt.now);
    expect(add.title, 'Opening Kodama');
    expect(app.engine.calls.where((c) => c.startsWith('playTracks')), isEmpty,
        reason: 'no second, private player');
    await closeApp(tester, app.db);
  });

  testWidgets(
      'on a phone that only listens along, the Jam\'s song has its lyrics '
      'card, as on the phone that plays', (tester) async {
    // Seen on two real phones (2026-10-17): the friend's player had no Lyrics
    // and no lyrics under the controls, because a song with a cover
    // from the catalogue was taken for a 30-second clip.
    final app = await open(tester, overrides: [
      currentLyricsProvider('jam:cat:9')
          .overrideWith((ref) async => const TrackLyrics(synced: false, lines: [
                LyricLine(startMs: null, text: 'Spiral out, keep going'),
              ])),
    ]);
    api.pushState(session(
        player: 'mia',
        queue: const [
          QueueEntry(
              uid: 1,
              trackId: 'cat:9',
              addedBy: 'mia',
              title: 'Schism',
              artist: 'Tool',
              imageUrl: 'https://cdn/lateralus.jpg',
              durationSec: 403),
        ],
        rev: 6));
    await settle(tester);
    await tester.tap(find.text('Schism').last);
    await settle(tester);

    expect(find.byType(NowPlayingScreen), findsOneWidget);
    expect(find.textContaining('Lyrics'), findsOneWidget);
    expect(find.text('Spiral out, keep going'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets('after leaving, the player is the person\'s own again',
      (tester) async {
    final app = await open(tester);
    app.engine.emit(samplePlaying());

    await container.read(jamControllerProvider.notifier).leave();
    await settle(tester);

    expect(container.read(playbackFacadeProvider).snapshot.track?.title,
        'Opening The');
    await closeApp(tester, app.db);
  });
}
