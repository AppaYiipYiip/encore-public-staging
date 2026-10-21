import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../data/api/opensubsonic/models.dart';
import '../../data/db/app_database.dart';
import '../../data/repos/request_repository.dart';
import '../../domain/text_match.dart';

/// Finds the library copy of a song that arrived from the catalogue.
///
/// A song the instant-play service fetched is playable from the service's
/// stream at once, but it only *belongs to the library* - can be liked,
/// put in a playlist, kept offline - once the music server has listed it
/// (ADR-066). This is the lookup that tells the two apart.
abstract interface class LibraryResolver {
  /// The library row for "[artist] - [title]", bringing it into the local
  /// database when the server has it and the phone has not seen it yet;
  /// `null` while it is not listed.
  Future<TrackRow?> find({
    required String artist,
    required String title,
    String? album,
  });
}

class SessionLibraryResolver implements LibraryResolver {
  SessionLibraryResolver(this._ref);

  final Ref _ref;

  @override
  Future<TrackRow?> find({
    required String artist,
    required String title,
    String? album,
  }) async {
    final repo = _ref.read(libraryRepositoryProvider);
    final serverId = _ref.read(activeServerIdProvider).value;
    if (repo == null || serverId == null) return null;

    // 1. The phone's own copy of the library already has it.
    final local = await LibraryMatcher(_ref.read(databaseProvider), serverId)
        .findTrack(artist, title);
    if (local != null) return local;

    // 2. The server may have it and the phone not yet: ask, and bring it in.
    final session = await _ref.read(sessionProvider.future);
    if (session == null) return null;
    final page = await session.client.search3(query: title, songCount: 25);
    final wanted = matchKey(artist, title);
    for (final song in page.valueOrNull?.songs ?? const <SsSong>[]) {
      if (matchKey(song.artist, song.title) != wanted) continue;
      final album = song.albumId == null
          ? null
          : (await session.client.getAlbum(song.albumId!)).valueOrNull;
      await repo.ingest([song], album: album);
      return repo.trackOnce(song.id);
    }
    return null;
  }
}

final libraryResolverProvider = Provider<LibraryResolver?>(
  (ref) => ref.watch(sessionProvider).value == null
      ? null
      : SessionLibraryResolver(ref),
);
