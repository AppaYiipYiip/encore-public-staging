import 'package:encore/core/result.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/fetch/fetch_client.dart';
import 'package:encore/features/instant/instant_controller.dart';
import 'package:encore/features/instant/instant_play.dart';
import 'package:encore/features/instant/library_resolver.dart';
import 'package:encore/features/jam/jam_song_player.dart';
import 'package:encore/features/providers.dart';
import 'package:encore_session/encore_session.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/factories.dart';
import '../../support/test_app.dart';

/// A song in a Jam is found on the phone that plays by what it IS (title and
/// artist), because the ids of one person's library mean nothing in another's.
class _Resolver implements LibraryResolver {
  _Resolver(this.rows);
  final Map<String, TrackRow> rows;
  final List<String> asked = [];

  @override
  Future<TrackRow?> find(
      {required String artist, required String title, String? album}) async {
    asked.add('$artist|$title');
    return rows[title];
  }
}

/// A fetch service that only remembers what it was asked for.
class _Service implements InstantPlayBackend {
  final List<FetchRequest> started = [];

  @override
  Future<void> prepare(FetchRequest request) async {}

  @override
  Future<Result<FetchJob>> start(FetchRequest request) async {
    started.add(request);
    return const Ok(FetchJob(id: 'job', state: FetchState.queued));
  }

  @override
  Future<Result<FetchJob>> status(String id) async =>
      const Ok(FetchJob(id: 'job', state: FetchState.failed));

  @override
  Uri? streamUrlFor(FetchRequest request) => null;

  @override
  Uri? streamUri(FetchJob job) => null;
}

void main() {
  late FakePlaybackFacade facade;

  ProviderContainer open(LibraryResolver? resolver) {
    facade = FakePlaybackFacade();
    final container = ProviderContainer(overrides: [
      enginePlaybackFacadeProvider.overrideWithValue(facade),
      libraryResolverProvider.overrideWithValue(resolver),
      // This server has no "play any song".
      instantPlayServiceProvider.overrideWith((ref) async => null),
    ]);
    addTearDown(container.dispose);
    return container;
  }

  test('a song in this person\'s library, found by title and artist, is played',
      () async {
    final row = trackRow('mine-9', title: 'Sommaire', artist: 'Raid');
    final container = open(_Resolver({'Sommaire': row}));

    final played = await SessionJamSongPlayer(container.read).play(
      const QueueEntry(
          uid: 3,
          trackId: 'ids-of-somebody-elses-library',
          addedBy: 'mia',
          title: 'Sommaire',
          artist: 'Raid'),
    );

    expect(played, isTrue);
    expect(facade.calls.single, startsWith('playTracks(1'));
    expect(facade.calls.single, contains('source=Jam'));
  });

  test('without a title and artist it asks nobody and says it cannot',
      () async {
    final resolver = _Resolver(const {});
    final container = open(resolver);

    final played = await SessionJamSongPlayer(container.read).play(
      const QueueEntry(uid: 3, trackId: 'x', addedBy: 'mia'),
    );

    expect(played, isFalse);
    expect(facade.calls, isEmpty);
    expect(resolver.asked, isEmpty);
  });

  test('a library that has no such song and no way to fetch it says it cannot',
      () async {
    final resolver = _Resolver(const {});
    final container = open(resolver);

    final played = await SessionJamSongPlayer(container.read).play(
      const QueueEntry(
          uid: 3,
          trackId: 'x',
          addedBy: 'mia',
          title: 'Nowhere',
          artist: 'Nobody'),
    );

    expect(played, isFalse, reason: 'no server to fetch from in this test');
    expect(resolver.asked, ['Nobody|Nowhere']);
  });

  group('getting a song ahead of its turn', () {
    ProviderContainer openWithService(LibraryResolver? resolver, _Service svc) {
      facade = FakePlaybackFacade();
      final container = ProviderContainer(overrides: [
        enginePlaybackFacadeProvider.overrideWithValue(facade),
        libraryResolverProvider.overrideWithValue(resolver),
        instantPlayServiceProvider
            .overrideWith((ref) async => InstantPlayService(
                  backend: svc,
                  matcher: null,
                  loadSong: (id) async => null,
                  pollEvery: Duration.zero,
                  timeout: const Duration(milliseconds: 50),
                  delay: (_) async {},
                )),
      ]);
      addTearDown(container.dispose);
      return container;
    }

    const entry = QueueEntry(
        uid: 4,
        trackId: 'cat:55',
        addedBy: 'mia',
        title: 'Schism',
        artist: 'Tool',
        album: 'Lateralus');

    test('a song this phone does not have is fetched, ahead of its turn',
        () async {
      final service = _Service();
      final container = openWithService(_Resolver(const {}), service);

      await SessionJamSongPlayer(container.read).preload(entry);

      expect(service.started.single.title, 'Schism');
      expect(service.started.single.artist, 'Tool');
      expect(facade.calls, isEmpty, reason: 'nothing is played');
    });

    test('a song already in the library is left alone', () async {
      final service = _Service();
      final row = trackRow('mine-1', title: 'Schism', artist: 'Tool');
      final container = openWithService(_Resolver({'Schism': row}), service);

      await SessionJamSongPlayer(container.read).preload(entry);

      expect(service.started, isEmpty);
    });

    test('a song with no title and artist is not looked for', () async {
      final service = _Service();
      final container = openWithService(_Resolver(const {}), service);

      await SessionJamSongPlayer(container.read)
          .preload(const QueueEntry(uid: 5, trackId: 'x', addedBy: 'mia'));

      expect(service.started, isEmpty);
    });
  });
}
