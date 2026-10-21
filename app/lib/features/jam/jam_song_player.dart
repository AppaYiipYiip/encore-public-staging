import 'package:encore_session/encore_session.dart';
import 'package:flutter_riverpod/misc.dart' show ProviderListenable;

import '../../app/providers.dart';
import '../../core/logger.dart';
import '../../data/catalogue/catalogue_models.dart';
import '../../data/db/app_database.dart';
import '../instant/instant_controller.dart';
import '../instant/library_resolver.dart';
import '../providers.dart';
import 'jam_facade.dart' show jamTrackId;
import 'jam_speaker.dart';

/// Something that reads a provider (a `Ref`'s or a container's `read`).
typedef Reader = T Function<T>(ProviderListenable<T> provider);

/// Starts a Jam entry on this phone. Each person on a server has their own
/// library, so the id a song was added with usually means nothing here: the song
/// is found by what it is (title and artist) in this person's library, then by
/// the id it came with (the same library), and last the server fetches it for
/// this person the way "play any song" does.
class SessionJamSongPlayer implements JamSongPlayer {
  SessionJamSongPlayer(this._read);

  final Reader _read;

  @override
  bool alreadyPlaying(QueueEntry entry) {
    final track = _read(enginePlaybackFacadeProvider).snapshot.track;
    if (track == null) return false;
    String key(String? s) => (s ?? '').trim().toLowerCase();
    return key(track.title) == key(entry.title) &&
        key(track.artist) == key(entry.artist);
  }

  /// A song this phone does not have is fetched while the one before it plays
  /// (the same fetch "play any song" makes, at the lowest priority: nobody is
  /// waiting for it yet). A song that is already in the library is left alone.
  /// When its turn comes, [play] finds it in the library at once.
  @override
  Future<void> preload(QueueEntry entry) async {
    final artist = entry.artist;
    final title = entry.title;
    if (artist == null || title == null) return;
    try {
      final row = await _read(libraryResolverProvider)
              ?.find(artist: artist, title: title, album: entry.album)
              .onError((_, __) => null) ??
          await _read(libraryRepositoryProvider)?.trackOnce(entry.trackId);
      if (row != null) return;
      await _read(instantControllerProvider.notifier).fetch(
        CatalogueTrack(
          id: jamTrackId(entry),
          title: title,
          artistName: artist,
          albumTitle: entry.album,
        ),
        bulk: true,
      );
    } on Object catch (error) {
      // A nicety ahead of time: the song is fetched when its turn comes.
      Log.debug('jam', 'getting "$title" ahead of its turn failed: $error');
    }
  }

  @override
  Future<bool> play(QueueEntry entry) async {
    final facade = _read(enginePlaybackFacadeProvider);
    final artist = entry.artist;
    final title = entry.title;

    TrackRow? row;
    if (artist != null && title != null) {
      row = await _read(libraryResolverProvider)
          ?.find(artist: artist, title: title, album: entry.album)
          .onError((_, __) => null);
    }
    row ??= await _read(libraryRepositoryProvider)?.trackOnce(entry.trackId);
    if (row != null) {
      await facade.playTracks([row], sourceName: 'Jam', sourceId: 'jam');
      return true;
    }

    if (artist == null || title == null) return false;
    final id = jamTrackId(entry);
    await _read(instantControllerProvider.notifier).play(
      CatalogueTrack(
        id: id,
        title: title,
        artistName: artist,
        albumTitle: entry.album,
      ),
      sourceName: 'Jam',
      sourceId: 'jam',
      onThisPhone: true,
    );
    return _read(instantStatusProvider(id))?.isReady ?? false;
  }
}
