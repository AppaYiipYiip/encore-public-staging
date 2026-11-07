import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../data/db/app_database.dart';
import '../instant/instant_controller.dart';
import '../instant/library_resolver.dart';
import '../providers.dart';
import 'playback_facade.dart';

/// How long to wait between looks for a song the service just fetched: the
/// music server lists it within seconds, or a minute on a big library.
final libraryLookDelaysProvider = Provider<List<Duration>>((ref) => const [
      Duration(seconds: 2),
      Duration(seconds: 4),
      Duration(seconds: 6),
      Duration(seconds: 10),
      Duration(seconds: 15),
      Duration(seconds: 20),
      Duration(seconds: 30),
      Duration(seconds: 45),
      Duration(seconds: 60),
    ]);

/// Which library song a streamed song turned out to be, as learned by whoever
/// found out first (the player looking for it, or a like waiting for it). Said
/// once, known to everybody: the heart must not depend on which of them was
/// still looking when the music server listed the song.
class ResolvedLibraryIds extends Notifier<Map<String, String>> {
  @override
  Map<String, String> build() => const {};

  void learn(String trackId, String libraryId) {
    if (state[trackId] == libraryId) return;
    state = {...state, trackId: libraryId};
  }
}

final resolvedLibraryIdsProvider =
    NotifierProvider<ResolvedLibraryIds, Map<String, String>>(
        ResolvedLibraryIds.new);

/// Is the playing item a catalogue song that the instant-play service is
/// fetching (or has fetched)?
final isServiceSongProvider =
    Provider.autoDispose.family<bool, NowPlayingTrack>(
  (ref, track) =>
      track.imageUrl != null &&
      ref.watch(instantStatusProvider(track.id)) != null,
);

/// Which library song is playing, for the actions that need one (like, add to
/// playlist, go to the album...). Settles once; what is *in* that song (is it
/// liked?) is read live from the database by [playingLibraryRowProvider], so
/// it can never be a frozen copy (the heart did not turn on for a fetched
/// song for exactly that reason).
///
/// * A library song is its own id.
/// * A song the service fetched has none *yet*: this looks again every few
///   seconds until the music server lists it (then like, playlists and
///   downloads work), and gives up after a few minutes. A streamed song the
///   fetch state of which is gone (the app was restarted, or a Jam's song) is
///   looked up the same way, by name.
final playingLibraryIdProvider =
    StreamProvider.autoDispose.family<String?, NowPlayingTrack>(
  (ref, track) async* {
    final repo = ref.watch(libraryRepositoryProvider);
    if (repo == null) {
      yield null;
      return;
    }
    if (track.imageUrl == null) {
      yield track.id;
      return;
    }
    final status = ref.watch(instantStatusProvider(track.id));
    final known =
        ref.watch(resolvedLibraryIdsProvider.select((m) => m[track.id]));
    if (known != null) {
      yield known;
      return;
    }
    final fromStatus = status?.track;
    if (fromStatus != null) {
      yield fromStatus.id;
      return;
    }

    final resolver = ref.read(libraryResolverProvider);
    if (resolver == null) {
      yield null;
      return;
    }
    yield null;
    final delays = ref.watch(libraryLookDelaysProvider);
    var cancelled = false;
    ref.onDispose(() => cancelled = true);
    for (var attempt = 0; attempt <= delays.length; attempt++) {
      final found = await resolver
          .find(
            artist: track.artist ?? '',
            title: track.title,
            album: track.album,
          )
          .onError((_, __) => null);
      if (cancelled) return;
      if (found != null) {
        ref.read(resolvedLibraryIdsProvider.notifier).learn(track.id, found.id);
        yield found.id;
        return;
      }
      if (attempt == delays.length) return;
      await Future<void>.delayed(delays[attempt]);
      if (cancelled) return;
    }
  },
);

/// The library copy of what is playing, live: it changes the moment the song
/// is liked, so the heart answers on the next frame.
final playingLibraryRowProvider =
    Provider.autoDispose.family<AsyncValue<TrackRow?>, NowPlayingTrack>(
  (ref, track) {
    final id = ref.watch(playingLibraryIdProvider(track)).value;
    if (id == null) return const AsyncData(null);
    return ref.watch(trackProvider(id));
  },
);
