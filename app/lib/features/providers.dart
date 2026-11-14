import 'dart:async';

import 'package:drift/drift.dart' show BooleanExpressionOperators;
import 'package:encore_session/encore_session.dart' show Command, SessionState;
import 'package:flutter/foundation.dart' show listEquals;
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../app/playback_providers.dart';
import '../app/providers.dart';
import '../core/perf.dart';
import '../core/stream_utils.dart';
import '../data/api/lrclib_client.dart';
import '../data/db/app_database.dart';
import '../data/db/search_dao.dart';
import '../data/repos/library_repository.dart';
import '../data/repos/lyrics_repository.dart';
import '../data/sync/playlist_mutations.dart';
import '../domain/artist_typo.dart';
import '../domain/household.dart';
import '../domain/search_rank.dart' show searchKey;
import 'jam/jam_facade.dart';
import 'jam/jam_providers.dart'
    show JamSession, jamControllerProvider, jamLoadingProvider;
import 'player/deferred_playback_facade.dart';
import 'player/playback_facade.dart';
import 'settings/settings_controller.dart';

/// Whether the signed-in server is an Encore server (tests replace it). On one, songs are references the server plays itself, playing
/// does not save, and there is no helper service to find; screens word themselves accordingly.
final onEncoreServerProvider = FutureProvider<bool>((ref) async {
  final session = await ref.watch(sessionProvider.future);
  return session?.encoreMode ?? false;
});

/// Read-model providers consumed by screens. Each is a thin, autoDispose
/// adapter over a [LibraryRepository] stream, so a server-side change that the
/// sync engine writes shows up everywhere without any refresh code (R-04).

// ---------------------------------------------------------------- playback

/// The real player (the engine), once it is ready (commands issued earlier
/// wait for it). Only the Jam speaker, which makes the sound a Jam asks for,
/// and the [playbackFacadeProvider] below use it; everything else goes through
/// the latter. Tests override it with a fake.
final enginePlaybackFacadeProvider = Provider<PlaybackFacade>((ref) {
  final facade = DeferredPlaybackFacade(
    ref.watch(playbackEngineProvider.future).then<PlaybackFacade>(
          (engine) => engine ?? NoopPlaybackFacade(),
        ),
  );
  ref.onDispose(() => unawaited(facade.dispose()));
  return facade;
});

/// The UI's only handle on playback. Outside a Jam it is the real player; in a
/// Jam it is the Jam's (docs/39 F4): the same player and queue, showing the
/// shared queue and sending every button and every song played to the Jam.
/// Tests override it with a fake.
final playbackFacadeProvider = Provider<PlaybackFacade>((ref) {
  final changes = StreamController<void>.broadcast();
  ref.listen(jamControllerProvider, (_, __) => changes.add(null));
  ref.listen(jamLoadingProvider, (_, __) => changes.add(null));
  final facade = JamPlaybackFacade(
    engine: ref.watch(enginePlaybackFacadeProvider),
    link: _ControllerJamLink(ref, changes.stream),
  );
  ref.onDispose(() {
    unawaited(facade.dispose());
    unawaited(changes.close());
  });
  return facade;
});

/// The Jam, as the Jam-aware player sees it.
class _ControllerJamLink implements JamLink {
  _ControllerJamLink(this._ref, this.changes);

  final Ref _ref;

  @override
  final Stream<void> changes;

  JamSession get _session => _ref.read(jamControllerProvider);

  @override
  bool get inJam => _session.inJam;

  @override
  bool get iPlay => _session.iPlay;

  @override
  bool get loading => _ref.read(jamLoadingProvider);

  @override
  SessionState? get state => _session.state;

  @override
  int positionNowMs() =>
      _ref.read(jamControllerProvider.notifier).positionNowMs();

  @override
  Future<bool> send(Command command) =>
      _ref.read(jamControllerProvider.notifier).send(command);

  @override
  void say(String message) =>
      _ref.read(jamControllerProvider.notifier).say(message);
}

/// What the engine tells the person: a song that cannot be played, playback
/// that stopped after several failures. Shown by the app as a snackbar; nothing
/// listened to it before, so a failure looked like nothing happening (B9).
final playbackNoticesProvider = StreamProvider<PlaybackNotice>(
  (ref) => ref.watch(playbackFacadeProvider).notices,
);

final playbackSnapshotProvider = StreamProvider<PlaybackSnapshot>((ref) async* {
  final facade = ref.watch(playbackFacadeProvider);
  yield facade.snapshot;
  yield* facade.snapshots;
});

final playbackPositionProvider =
    StreamProvider.autoDispose<Duration>((ref) async* {
  final facade = ref.watch(playbackFacadeProvider);
  // A song restored after the app was killed waits paused where it was; the
  // player reports a position only once it plays, so start from what the
  // engine already knows instead of 0:00 (J-11).
  yield facade.snapshot.position;
  yield* facade.positionStream;
});

// ----------------------------------------------------------------- library

LibraryRepository? _repo(Ref ref) => ref.watch(libraryRepositoryProvider);

Stream<T> _none<T>() => const Stream.empty();

final trackCountProvider = StreamProvider.autoDispose<int>(
  (ref) => _repo(ref)?.watchTrackCount() ?? _none(),
);

final recentlyAddedAlbumsProvider = StreamProvider.autoDispose<List<AlbumRow>>(
    (ref) =>
        _repo(ref)?.watchAlbums(sort: AlbumSort.recentlyAdded, limit: 20) ??
        _none());

final serverListProvider =
    StreamProvider.autoDispose.family<List<String>, String>(
  (ref, key) => _repo(ref)?.watchServerList(key) ?? _none(),
);

/// Albums from a server-provided id list (recently / most played).
final serverAlbumListProvider =
    StreamProvider.autoDispose.family<List<AlbumRow>, String>((ref, key) {
  final ids = ref.watch(serverListProvider(key)).value ?? const <String>[];
  return _repo(ref)?.watchAlbumsByIds(ids) ?? _none();
});

final albumsProvider = StreamProvider.autoDispose
    .family<List<AlbumRow>, AlbumSort>(
        (ref, sort) => _repo(ref)?.watchAlbums(sort: sort) ?? _none());

final artistsProvider = StreamProvider.autoDispose<List<ArtistRow>>(
  (ref) => _repo(ref)?.watchArtists() ?? _none(),
);

final playlistsProvider = StreamProvider.autoDispose<List<PlaylistRow>>(
  (ref) => _repo(ref)?.watchPlaylists() ?? _none(),
);

final trackProvider = StreamProvider.autoDispose.family<TrackRow?, String>(
  (ref, id) => _repo(ref)?.watchTrack(id) ?? _none(),
);

final likedTracksProvider = StreamProvider.autoDispose<List<TrackRow>>(
  (ref) => _repo(ref)?.watchLikedTracks() ?? _none(),
);

final downloadedIdsProvider = StreamProvider.autoDispose<Set<String>>(
  (ref) =>
      _repo(ref)
          ?.watchDownloadedTrackIds()
          .throttleLatest(const Duration(milliseconds: 500)) ??
      _none(),
);

/// The albums and playlists that have at least one song on the phone: the one source of "Not downloaded" and "Plays offline" (P1-15).
final onPhoneProvider = StreamProvider.autoDispose<OnPhone>(
  (ref) =>
      _repo(ref)
          ?.watchOnPhone()
          .throttleLatest(const Duration(milliseconds: 500)) ??
      _none(),
);

/// Whether any song is on the phone. The words about being offline promise that "downloaded songs still play" only when there are some.
final hasDownloadsProvider = Provider.autoDispose<bool>((ref) =>
    (ref.watch(downloadedIdsProvider).value ?? const <String>{}).isNotEmpty);

final albumProvider = StreamProvider.autoDispose.family<AlbumRow?, String>(
  (ref, id) => _repo(ref)?.watchAlbum(id) ?? _none(),
);

final albumTracksProvider =
    StreamProvider.autoDispose.family<List<TrackRow>, String>(
  (ref, id) => _repo(ref)?.watchAlbumTracks(id) ?? _none(),
);

/// The id a playlist page should use: a playlist created on this phone is
/// opened under its local id, and may have received its server id since.
final resolvedPlaylistIdProvider =
    StreamProvider.autoDispose.family<String, String>((ref, id) {
  final serverId = ref.watch(activeServerIdProvider).value;
  if (serverId == null || !PlaylistMutations.isLocalId(id)) {
    return Stream.value(id);
  }
  final db = ref.watch(databaseProvider);
  return (db.select(db.playlistAliases)
        ..where((a) => a.serverId.equals(serverId) & a.localId.equals(id)))
      .watchSingleOrNull()
      .map((alias) => alias?.serverPlaylistId ?? id);
});

final playlistProvider =
    StreamProvider.autoDispose.family<PlaylistRow?, String>(
  (ref, id) => _repo(ref)?.watchPlaylist(id) ?? _none(),
);

/// Makes sure a playlist's entries are on this phone. Background sync skips
/// very large server-generated playlists (it would download megabytes nobody
/// asked for); opening one - or pinning it - fetches it on demand.
final ensurePlaylistProvider =
    FutureProvider.autoDispose.family<void, String>((ref, id) async {
  final session = await ref.watch(sessionProvider.future);
  if (session == null) return;
  final db = ref.watch(databaseProvider);
  final serverId = ref.watch(activeServerIdProvider).value;
  if (serverId == null) return;
  final row = await (db.select(db.playlists)
        ..where((p) => p.serverId.equals(serverId) & p.id.equals(id)))
      .getSingleOrNull();
  if (row == null || row.entriesFetchedAtMs != null) return;
  PerfMonitor.instance.begin('playlist.fetch-entries');
  final result = await session.sync.refreshPlaylist(id);
  PerfMonitor.instance
      .end('playlist.fetch-entries', detail: '${row.songCount} songs');
  final failure = result.failureOrNull;
  if (failure != null) throw failure;
});

final playlistTracksProvider =
    StreamProvider.autoDispose.family<List<TrackRow>, String>(
  (ref, id) => _repo(ref)?.watchPlaylistTracks(id) ?? _none(),
);

/// Like [playlistTracksProvider] but with each entry's position, which
/// editing needs.
final playlistEntriesProvider = StreamProvider.autoDispose
    .family<List<({int position, TrackRow track})>, String>(
  (ref, id) => _repo(ref)?.watchPlaylistEntries(id) ?? _none(),
);

final playlistCoverIdsProvider =
    StreamProvider.autoDispose.family<List<String>, String>(
  (ref, id) => _repo(ref)?.watchPlaylistCoverIds(id) ?? _none(),
);

final artistProvider = StreamProvider.autoDispose.family<ArtistRow?, String>(
  (ref, id) => _repo(ref)?.watchArtist(id) ?? _none(),
);

final artistAlbumsProvider =
    StreamProvider.autoDispose.family<List<AlbumRow>, String>(
  (ref, id) => _repo(ref)?.watchArtistAlbums(id) ?? _none(),
);

/// Every song the library holds of an artist (what the artist page's Play and Shuffle play).
final artistTracksProvider =
    StreamProvider.autoDispose.family<List<TrackRow>, String>(
  (ref, id) => _repo(ref)?.watchArtistTracks(id) ?? _none(),
);

final genresProvider =
    StreamProvider.autoDispose<List<({String name, int albums})>>(
  (ref) => _repo(ref)?.watchGenres() ?? _none(),
);

final genreAlbumsProvider =
    StreamProvider.autoDispose.family<List<AlbumRow>, String>(
  (ref, genre) => _repo(ref)?.watchGenreAlbums(genre) ?? _none(),
);

// --------------------------------------------------------------- household

/// What Your Library lists on a shared server (ADR-049): the person's own music unless they ask for the whole server.
final libraryScopeProvider = Provider<LibraryScope>(
  (ref) => ref.watch(settingsProvider.select((s) => s.libraryScope)),
);

/// The signed-in account's name; decides what is "mine".
final accountNameProvider = Provider<String?>(
  (ref) => ref.watch(activeServerProvider.select((s) => s.value?.username)),
);

/// This account's own slice of the shared catalogue.
final myMusicProvider = StreamProvider.autoDispose<MyMusic>(
  (ref) => _repo(ref)?.watchMyMusic(ref.watch(accountNameProvider)) ?? _none(),
);

/// Playlists split by who they belong to.
class PlaylistGroups {
  const PlaylistGroups({
    this.mine = const [],
    this.madeForMe = const [],
    this.shared = const [],
  });

  /// Created by this account (editable).
  final List<PlaylistRow> mine;

  /// Generated for this account by the server (read-only).
  final List<PlaylistRow> madeForMe;

  /// Other people's public playlists.
  final List<PlaylistRow> shared;

  /// Everything that belongs to this account.
  List<PlaylistRow> get own => [...mine, ...madeForMe];
}

final playlistGroupsProvider = Provider.autoDispose<PlaylistGroups>((ref) {
  final rows = ref.watch(playlistsProvider).value ?? const <PlaylistRow>[];
  final me = ref.watch(accountNameProvider);
  final mine = <PlaylistRow>[];
  final madeForMe = <PlaylistRow>[];
  final shared = <PlaylistRow>[];
  for (final p in rows) {
    switch (playlistOwnership(owner: p.owner, readonly: p.readonly, me: me)) {
      case PlaylistOwnership.mine:
        mine.add(p);
      case PlaylistOwnership.madeForMe:
        madeForMe.add(p);
      case PlaylistOwnership.shared:
        shared.add(p);
    }
  }
  return PlaylistGroups(mine: mine, madeForMe: madeForMe, shared: shared);
});

/// Newest albums, a bigger pool than Home shows, so the ones from artists the
/// user plays can be picked out of what everybody added.
final newAlbumPoolProvider = StreamProvider.autoDispose<List<AlbumRow>>(
  (ref) =>
      _repo(ref)?.watchAlbums(sort: AlbumSort.recentlyAdded, limit: 150) ??
      _none(),
);

/// Library albums for the current scope.
final scopedAlbumsProvider =
    Provider.autoDispose.family<List<AlbumRow>?, AlbumSort>((ref, sort) {
  final all = ref.watch(albumsProvider(sort)).value ?? const <AlbumRow>[];
  if (ref.watch(libraryScopeProvider) == LibraryScope.everything) return all;
  final mine = ref.watch(myMusicProvider).value;
  if (mine == null) return null; // still working it out
  return [
    for (final a in all)
      if (mine.hasAlbum(a.id)) a,
  ];
});

/// Library artists for the current scope.
/// The picture to show for an artist that has none of its own (the cover of one of its songs), asked once for the Artists list and again when
/// the number of artists changes: not at every change of the library (a keep or a sync pass writes the songs again and again).
final artistCoverFallbacksProvider =
    FutureProvider.autoDispose<Map<String, String>>((ref) async {
  ref.watch(artistsProvider.select((a) => a.value?.length));
  return await _repo(ref)?.artistCoverFallbacks() ?? const <String, String>{};
});

/// The artists of a song, each on its own (empty when the phone knows only the one string a song shows): what the player makes tappable.
final songArtistsProvider = FutureProvider.autoDispose
    .family<List<String>, String>((ref, trackId) async =>
        await _repo(ref)?.songArtists(trackId) ?? const <String>[]);

final scopedArtistsProvider = Provider.autoDispose<List<ArtistRow>?>((ref) {
  final all = ref.watch(artistsProvider).value ?? const <ArtistRow>[];
  if (ref.watch(libraryScopeProvider) == LibraryScope.everything) return all;
  final mine = ref.watch(myMusicProvider).value;
  if (mine == null) return null;
  return [
    for (final a in all)
      if (mine.hasArtist(a.id)) a,
  ];
});

// ------------------------------------------------------------------ search

class SearchResults {
  const SearchResults({
    this.tracks = const [],
    this.albums = const [],
    this.artists = const [],
  });

  final List<TrackRow> tracks;
  final List<AlbumRow> albums;
  final List<ArtistRow> artists;

  bool get isEmpty => tracks.isEmpty && albums.isEmpty && artists.isEmpty;
}

/// The last [ArtistTypoIndex], so that a list of artists that arrives again with the same names takes over its folded names. (The
/// database tells the list again whenever any song is written, so during a sync with the search open it arrives often; folding 5,000
/// names takes about 100 ms in a debug build.) Holds nothing until the first search.
class _TypoIndexMemory {
  ArtistTypoIndex<ArtistRow>? last;
}

final _typoIndexMemoryProvider =
    Provider<_TypoIndexMemory>((ref) => _TypoIndexMemory());

/// The library's artists, folded once for the typo scan of a search (N-23a). A new one when the list of artists changes; its names are
/// folded on the first scan that needs them, not here, and not again while the names stay the same.
final artistTypoIndexProvider =
    Provider.autoDispose<ArtistTypoIndex<ArtistRow>?>((ref) {
  final artists = ref.watch(artistsProvider).value;
  if (artists == null) return null;
  final memory = ref.read(_typoIndexMemoryProvider);
  return memory.last = ArtistTypoIndex<ArtistRow>(artists,
      nameOf: (a) => a.name, fold: searchKey, reusing: memory.last);
});

/// The library's own full-text search of [query]: the one answer that must come at once (< 30 ms budget, offline).
///
/// **It watches nothing that a write can change**: only the id of the server (which emits when the id changes, not when the server's row is
/// updated) and the database. A search that watched the list of artists, or the server's row, started over every time a sync or a download
/// wrote a song; on a phone that is busy a run takes longer than the pause between two writes, so the first answer of a new query was
/// abandoned again and again and the page stayed empty until the writing stopped (14 Nov 2026, `search_local_first_test.dart`: 30 starts in
/// 3 s, 30 abandoned). What the list of artists adds is added after this answer, by [searchResultsProvider].
final _ftsSearchProvider = FutureProvider.autoDispose
    .family<SearchResults, String>((ref, query) async {
  final serverId = ref.watch(activeServerIdProvider).value;
  if (serverId == null || query.trim().isEmpty) return const SearchResults();
  final dao = SearchDao(ref.watch(databaseProvider));
  final tracks = await dao.tracks(serverId, query, limit: 30).get();
  final albums = await dao.albums(serverId, query, limit: 12).get();
  final artists = await dao.artists(serverId, query, limit: 8).get();
  return SearchResults(tracks: tracks, albums: albums, artists: artists);
});

/// Instant, offline search of the library: [_ftsSearchProvider]'s answer, as soon as it is there, plus the typo guess of an artist.
///
/// The library's artists are found by the start of a word, so a name typed with a letter wrong is not found by it (N-23a: "landmarks"
/// for "Landmvrks"). Only when **no artist begins with the typed words** the artists' names are scanned for one that is a letter or
/// two off ([ArtistTypoIndex], the rule in `domain/artist_typo.dart`): a name that is an answer is never pushed down by a guess. The
/// guesses are scored by `artistMatch` with the rest, below every exact answer. The catalogue's part of a search is Deezer's own
/// matching, not this.
///
/// The list of artists is watched only when a guess is needed, and only here: it arriving (late, or again with every write) works the guess
/// out again over the same answer, and never starts the search over or holds it back.
final searchResultsProvider = Provider.autoDispose
    .family<AsyncValue<SearchResults>, String>((ref, query) {
  final answer = ref.watch(_ftsSearchProvider(query));
  final found = answer.value;
  if (found == null || found.artists.isNotEmpty || query.trim().isEmpty) {
    return answer;
  }
  final guessed =
      ref.watch(artistTypoIndexProvider)?.find(query, limit: 8) ?? const [];
  if (guessed.isEmpty) return answer;
  return AsyncData(SearchResults(
      tracks: found.tracks, albums: found.albums, artists: guessed));
});

/// "Find in playlist" (N-25): the positions of a playlist's entries whose song matches [query], from the phone's own search index (Search's
/// matching, restricted to this playlist: one matcher, ADR-R42), in playlist order. Watched, so an edit or a sync while the page is open
/// keeps the list right.
final playlistFindProvider = StreamProvider.autoDispose
    .family<List<int>, ({String playlistId, String query})>((ref, key) {
  final server = ref.watch(activeServerProvider).value;
  if (server == null || key.query.trim().isEmpty) {
    return Stream.value(const <int>[]);
  }
  return SearchDao(ref.watch(databaseProvider))
      .playlistEntryPositions(server.id, key.playlistId, key.query)
      .watch()
      .distinct(listEquals);
});

// ------------------------------------------------------------------ lyrics

final lyricsRepositoryProvider = Provider<LyricsRepository?>((ref) {
  final server = ref.watch(activeServerProvider).value;
  if (server == null) return null;
  final session = ref.watch(sessionProvider).value;
  return LyricsRepository(
    db: ref.watch(databaseProvider),
    serverId: server.id,
    server: session?.client,
    lrclib: LrcLibClient(),
    clock: ref.watch(clockProvider),
  );
});
