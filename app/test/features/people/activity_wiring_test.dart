import 'package:encore/features/people/people_providers.dart';
import 'package:encore/features/player/playback_facade.dart';
import 'package:encore/features/providers.dart';
import 'package:encore/features/settings/settings_controller.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../support/fake_people_api.dart';
import '../../support/test_app.dart';

/// From the player to the friends (docs/35): what is playing reaches the
/// service only when the person chose to share it and has not switched
/// "private listening" on.
void main() {
  const song = PlaybackSnapshot(
    track: NowPlayingTrack(
      id: 'song-1',
      title: 'Dogs',
      artist: 'Pink Floyd',
      album: 'Animals',
      coverArt: 'cover-1',
    ),
    isPlaying: true,
  );

  late FakePlaybackFacade facade;
  late FakePeopleApi api;
  late ProviderContainer container;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    facade = FakePlaybackFacade(song);
    api = FakePeopleApi();
    container = ProviderContainer(overrides: [
      playbackFacadeProvider.overrideWithValue(facade),
      peopleApiProvider.overrideWith((ref) async => api),
    ]);
  });

  /// Starts the wiring the way the app widget does, and lets the service's
  /// answer about me arrive.
  Future<void> start(WidgetTester tester) async {
    container.listen(activityPublisherProvider, (_, __) {});
    container.listen(settingsProvider, (_, __) {});
    await container.read(peopleProvider.future);
    await tester.pump(const Duration(milliseconds: 100));
  }

  Future<void> settle(WidgetTester tester) => tester
      .pump(const Duration(seconds: 3)); // longer than the 2 s a song must stay

  testWidgets('a person who has not chosen to share tells nobody',
      (tester) async {
    await start(tester);

    facade.emit(song);
    await settle(tester);

    expect(api.reports, isEmpty);
    container.dispose();
  });

  testWidgets('switching sharing on tells the friends what is playing',
      (tester) async {
    await start(tester);

    await container.read(peopleProvider.notifier).setSharing(true);
    await settle(tester);

    expect(api.reports.single.title, 'Dogs');
    expect(api.reports.single.artist, 'Pink Floyd');
    expect(api.reports.single.playing, isTrue);
    expect(api.reports.single.coverUrl, isNull);
    container.dispose();
  });

  testWidgets('the next song is told once the person settles on it',
      (tester) async {
    await start(tester);
    await container.read(peopleProvider.notifier).setSharing(true);
    await settle(tester);

    facade.emit(PlaybackSnapshot(
      track: const NowPlayingTrack(id: 'song-2', title: 'Sheep'),
      isPlaying: true,
    ));
    await settle(tester);

    expect(api.reports.map((r) => r.title), ['Dogs', 'Sheep']);
    container.dispose();
  });

  testWidgets('private listening wins: it forgets the song and stays quiet',
      (tester) async {
    await start(tester);
    await container.read(peopleProvider.notifier).setSharing(true);
    await settle(tester);
    expect(api.reports, hasLength(1));

    container.read(settingsProvider.notifier).setPrivateListening(true);
    await tester.pump(const Duration(milliseconds: 100));

    expect(api.clears, 1, reason: 'what was shown is taken down');

    facade.emit(PlaybackSnapshot(
      track: const NowPlayingTrack(id: 'song-3', title: 'Pigs'),
      isPlaying: true,
    ));
    await settle(tester);
    expect(api.reports, hasLength(1), reason: 'nothing more while private');
    container.dispose();
  });

  testWidgets('there is no publisher on a server without the service',
      (tester) async {
    final bare = ProviderContainer(overrides: [
      playbackFacadeProvider.overrideWithValue(facade),
      peopleApiProvider.overrideWith((ref) async => null),
    ]);
    addTearDown(bare.dispose);

    await bare.read(peopleApiProvider.future);

    expect(bare.read(activityPublisherProvider), isNull);
  });
}
