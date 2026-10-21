import 'package:flutter/foundation.dart';

import '../data/db/app_database.dart';
import '../data/db/search_dao.dart';
import '../data/repos/downloads_repository.dart';
import '../data/repos/library_repository.dart';

/// One entry of the browse tree shown by Android Auto / media browsers.
@immutable
class BrowseNode {
  const BrowseNode({
    required this.id,
    required this.title,
    this.subtitle,
    this.coverArtId,
    this.playable = false,
    this.browsable = false,
  });

  final String id;
  final String title;
  final String? subtitle;
  final String? coverArtId;
  final bool playable;
  final bool browsable;
}

/// "Play these tracks, starting here".
@immutable
class PlayRequest {
  const PlayRequest({
    required this.tracks,
    required this.sourceName,
    required this.sourceId,
    this.startIndex = 0,
  });

  final List<TrackRow> tracks;
  final int startIndex;
  final String sourceName;
  final String sourceId;
}

/// Read access to the catalogue for media browsers (Android Auto, Bluetooth
/// head units, Google Assistant). Backed by the local database, so the car
/// UI works with no network and answers in milliseconds.
abstract interface class LibraryBrowser {
  Future<List<BrowseNode>> children(String parentId);
  Future<PlayRequest?> resolvePlay(String mediaId);
  Future<PlayRequest?> search(String query);
}

/// Media ids. Tracks carry the collection they are played from so that
/// choosing one song queues the whole album/playlist from there.
abstract final class BrowseIds {
  static const root = 'root';
  static const recent = 'recent';
  static const playlists = 'playlists';
  static const albums = 'albums';
  static const artists = 'artists';
  static const liked = 'liked';
  static const downloads = 'downloads';

  static String playlist(String id) => 'playlist:$id';
  static String album(String id) => 'album:$id';
  static String artist(String id) => 'artist:$id';
  static String track(String id, String collection) => 'track:$id@$collection';
}

/// The top level of the browse tree. Fixed, so a car that connects before the
/// database is ready can still be shown it (docs/23, B12).
const List<BrowseNode> kBrowseRoot = [
  BrowseNode(id: BrowseIds.recent, title: 'Recently played', browsable: true),
  BrowseNode(id: BrowseIds.playlists, title: 'Playlists', browsable: true),
  BrowseNode(id: BrowseIds.albums, title: 'Albums', browsable: true),
  BrowseNode(id: BrowseIds.artists, title: 'Artists', browsable: true),
  BrowseNode(id: BrowseIds.liked, title: 'Liked songs', browsable: true),
  BrowseNode(id: BrowseIds.downloads, title: 'Downloaded', browsable: true),
];

class DbLibraryBrowser implements LibraryBrowser {
  DbLibraryBrowser({
    required AppDatabase db,
    required int serverId,
    this.pageSize = 200,
  })  : _db = db,
        _serverId = serverId,
        _library = LibraryRepository(db, serverId),
        _downloads = DownloadsRepository(db, serverId);

  final AppDatabase _db;
  final int _serverId;
  final LibraryRepository _library;
  final DownloadsRepository _downloads;

  /// Android Auto renders long lists poorly (and the binder limits payloads),
  /// so every level is capped.
  final int pageSize;

  @override
  Future<List<BrowseNode>> children(String parentId) async {
    switch (parentId) {
      case BrowseIds.root:
        return kBrowseRoot;
      case BrowseIds.recent:
        final ids = await _library.watchServerList('recent').first;
        final albums = await _library.watchAlbumsByIds(ids).first;
        return [for (final a in albums.take(pageSize)) _albumNode(a)];
      case BrowseIds.playlists:
        final playlists = await _library.watchPlaylists().first;
        return [
          for (final p in playlists.take(pageSize))
            BrowseNode(
              id: BrowseIds.playlist(p.id),
              title: p.name,
              subtitle: '${p.songCount} ${p.songCount == 1 ? 'song' : 'songs'}',
              coverArtId: p.coverArt,
              browsable: true,
            ),
        ];
      case BrowseIds.albums:
        final albums =
            await _library.watchAlbums(sort: AlbumSort.recentlyAdded).first;
        return [for (final a in albums.take(pageSize)) _albumNode(a)];
      case BrowseIds.artists:
        final artists = await _library.watchArtists().first;
        return [
          for (final a in artists.take(pageSize))
            BrowseNode(
              id: BrowseIds.artist(a.id),
              title: a.name,
              subtitle: '${a.albumCount} albums',
              coverArtId: a.coverArt,
              browsable: true,
            ),
        ];
      case BrowseIds.liked:
        final tracks = await _library.watchLikedTracks().first;
        return _trackNodes(tracks, BrowseIds.liked);
      case BrowseIds.downloads:
        final tracks = await _downloads.watchDownloadedTracks().first;
        return _trackNodes(tracks, BrowseIds.downloads);
    }

    if (parentId.startsWith('playlist:')) {
      final id = parentId.substring('playlist:'.length);
      final tracks = await _library.watchPlaylistTracks(id).first;
      return _trackNodes(tracks, parentId);
    }
    if (parentId.startsWith('album:')) {
      final id = parentId.substring('album:'.length);
      final tracks = await _library.watchAlbumTracks(id).first;
      return _trackNodes(tracks, parentId);
    }
    if (parentId.startsWith('artist:')) {
      final id = parentId.substring('artist:'.length);
      final albums = await _library.watchArtistAlbums(id).first;
      return [for (final a in albums.take(pageSize)) _albumNode(a)];
    }
    return const [];
  }

  BrowseNode _albumNode(AlbumRow a) => BrowseNode(
        id: BrowseIds.album(a.id),
        title: a.name,
        subtitle: a.artist,
        coverArtId: a.coverArt,
        browsable: true,
      );

  List<BrowseNode> _trackNodes(List<TrackRow> tracks, String collection) => [
        for (final t in tracks.take(pageSize))
          BrowseNode(
            id: BrowseIds.track(t.id, collection),
            title: t.title,
            subtitle: t.artist,
            coverArtId: t.coverArt,
            playable: true,
          ),
      ];

  @override
  Future<PlayRequest?> resolvePlay(String mediaId) async {
    // track:<id>@<collection>
    if (mediaId.startsWith('track:')) {
      final rest = mediaId.substring('track:'.length);
      final at = rest.indexOf('@');
      final trackId = at < 0 ? rest : rest.substring(0, at);
      final collection = at < 0 ? '' : rest.substring(at + 1);

      final tracks = await _tracksOf(collection);
      final name = await _nameOf(collection);
      if (tracks.isEmpty) {
        final single = await _library.watchTrack(trackId).first;
        if (single == null) return null;
        return PlayRequest(
            tracks: [single],
            sourceName: single.title,
            sourceId: 'track:${single.id}');
      }
      final index = tracks.indexWhere((t) => t.id == trackId);
      return PlayRequest(
        tracks: tracks,
        startIndex: index < 0 ? 0 : index,
        sourceName: name,
        sourceId: collection,
      );
    }
    // A browsable node chosen directly: play it from the top.
    final tracks = await _tracksOf(mediaId);
    if (tracks.isEmpty) return null;
    return PlayRequest(
      tracks: tracks,
      sourceName: await _nameOf(mediaId),
      sourceId: mediaId,
    );
  }

  Future<List<TrackRow>> _tracksOf(String collection) async {
    if (collection == BrowseIds.liked) {
      return _library.watchLikedTracks().first;
    }
    if (collection == BrowseIds.downloads) {
      return _downloads.watchDownloadedTracks().first;
    }
    if (collection.startsWith('playlist:')) {
      return _library
          .watchPlaylistTracks(collection.substring('playlist:'.length))
          .first;
    }
    if (collection.startsWith('album:')) {
      return _library
          .watchAlbumTracks(collection.substring('album:'.length))
          .first;
    }
    if (collection.startsWith('artist:')) {
      return _library.artistTracks(collection.substring('artist:'.length));
    }
    return const [];
  }

  Future<String> _nameOf(String collection) async {
    if (collection == BrowseIds.liked) return 'Liked Songs';
    if (collection == BrowseIds.downloads) return 'Downloaded';
    if (collection.startsWith('playlist:')) {
      final p = await _library
          .watchPlaylist(collection.substring('playlist:'.length))
          .first;
      return p?.name ?? 'Playlist';
    }
    if (collection.startsWith('album:')) {
      final a = await _library
          .watchAlbum(collection.substring('album:'.length))
          .first;
      return a?.name ?? 'Album';
    }
    if (collection.startsWith('artist:')) {
      final a = await _library
          .watchArtist(collection.substring('artist:'.length))
          .first;
      return a?.name ?? 'Artist';
    }
    return 'Music';
  }

  @override
  Future<PlayRequest?> search(String query) async {
    final q = query.trim();
    if (q.isEmpty) return null;
    final dao = SearchDao(_db);
    final tracks = await dao.tracks(_serverId, q, limit: 30).get();
    if (tracks.isNotEmpty) {
      // "Play <song>" -> the best match; "Play <artist>" -> that artist's
      // songs, so check artists first when the query names one exactly.
      final artists = await dao.artists(_serverId, q, limit: 1).get();
      if (artists.isNotEmpty &&
          artists.first.name.toLowerCase() == q.toLowerCase()) {
        final all = await _library.artistTracks(artists.first.id);
        if (all.isNotEmpty) {
          return PlayRequest(
              tracks: all,
              sourceName: artists.first.name,
              sourceId: BrowseIds.artist(artists.first.id));
        }
      }
      return PlayRequest(
          tracks: tracks, sourceName: 'Search: $q', sourceId: 'search:$q');
    }
    final albums = await dao.albums(_serverId, q, limit: 1).get();
    if (albums.isNotEmpty) {
      return resolvePlay(BrowseIds.album(albums.first.id));
    }
    final artists = await dao.artists(_serverId, q, limit: 1).get();
    if (artists.isNotEmpty) {
      final all = await _library.artistTracks(artists.first.id);
      if (all.isNotEmpty) {
        return PlayRequest(
            tracks: all,
            sourceName: artists.first.name,
            sourceId: BrowseIds.artist(artists.first.id));
      }
    }
    return null;
  }
}
