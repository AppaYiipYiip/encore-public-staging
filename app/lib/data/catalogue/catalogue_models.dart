import 'package:flutter/foundation.dart';

import '../../domain/text_match.dart';

/// An artist in the public music catalogue (not necessarily in the library).
@immutable
class CatalogueArtist {
  const CatalogueArtist({
    required this.id,
    required this.name,
    this.imageUrl,
    this.fans,
    this.albumCount,
  });

  final String id;
  final String name;
  final String? imageUrl;
  final int? fans;
  final int? albumCount;
}

/// Several artists may have the name that was typed (the catalogue has five
/// called "Raid": one with 36,000 fans, four with a handful, listed in that
/// order of its choosing). The ones named exactly like the query come first,
/// the best known of them first, so the artist people mean is the first row;
/// the rest keep the catalogue's own order (a typo correction stays on top).
List<CatalogueArtist> rankNamesakes(
    String query, List<CatalogueArtist> artists) {
  final wanted = normalizeForMatch(query, dropEdition: false);
  bool named(CatalogueArtist a) =>
      normalizeForMatch(a.name, dropEdition: false) == wanted;
  final same = artists.where(named).toList()
    ..sort((a, b) => (b.fans ?? 0).compareTo(a.fans ?? 0));
  return [...same, ...artists.where((a) => !named(a))];
}

@immutable
class CatalogueAlbum {
  const CatalogueAlbum({
    required this.id,
    required this.title,
    required this.artistName,
    this.artistId,
    this.coverUrl,
    this.trackCount,
    this.year,
    this.recordType,
    this.releaseDate,
  });

  final String id;
  final String title;
  final String artistName;
  final String? artistId;
  final String? coverUrl;
  final int? trackCount;
  final int? year;

  /// Full release date as the catalogue gives it (`2026-10-09`), when known.
  final String? releaseDate;

  /// `album` | `ep` | `single` | `compile`.
  final String? recordType;
}

@immutable
class CatalogueTrack {
  const CatalogueTrack({
    required this.id,
    required this.title,
    required this.artistName,
    this.artistId,
    this.albumTitle,
    this.albumId,
    this.coverUrl,
    this.duration,
    this.isrc,
    this.trackNumber,
    this.discNumber,
    this.videoId,
    this.officialVideo = false,
  });

  final String id;
  final String title;
  final String artistName;
  final String? artistId;
  final String? albumTitle;
  final String? albumId;
  final String? coverUrl;
  final Duration? duration;
  final String? isrc;

  /// Position on its release (`track_position` / `disk_number`).
  final int? trackNumber;
  final int? discNumber;

  /// A song from an imported playlist knows the YouTube video the playlist
  /// saved ([officialVideo]: YouTube's own upload of it); fetching uses that
  /// instead of searching.
  final String? videoId;
  final bool officialVideo;
}

@immutable
class CatalogueResults {
  const CatalogueResults({
    this.artists = const [],
    this.albums = const [],
    this.tracks = const [],
    this.ownedArtists = const {},
  });

  static const CatalogueResults empty = CatalogueResults();

  final List<CatalogueArtist> artists;
  final List<CatalogueAlbum> albums;
  final List<CatalogueTrack> tracks;

  /// Catalogue artist id -> library artist id, for the artists the library
  /// has. Such an artist is *kept* in [artists] (its page shows what is
  /// missing); only one catalogue artist per name is marked, so a namesake
  /// the library does not have stays a separate, unowned artist.
  final Map<String, String> ownedArtists;

  bool get isEmpty => artists.isEmpty && albums.isEmpty && tracks.isEmpty;
}

/// What is on top in one genre: the songs, artists and albums people play.
@immutable
class CatalogueGenreChart {
  const CatalogueGenreChart({
    this.tracks = const [],
    this.artists = const [],
    this.albums = const [],
  });

  static const CatalogueGenreChart empty = CatalogueGenreChart();

  final List<CatalogueTrack> tracks;
  final List<CatalogueArtist> artists;
  final List<CatalogueAlbum> albums;

  bool get isEmpty => tracks.isEmpty && artists.isEmpty && albums.isEmpty;
}

/// The catalogue's genres (Deezer's ids), with English names: the catalogue
/// names them in the language of its caller's country.
const List<({int id, String name})> kCatalogueGenres = [
  (id: 132, name: 'Pop'),
  (id: 116, name: 'Rap / Hip Hop'),
  (id: 152, name: 'Rock'),
  (id: 113, name: 'Dance'),
  (id: 165, name: 'R&B'),
  (id: 85, name: 'Alternative'),
  (id: 106, name: 'Electro'),
  (id: 464, name: 'Metal'),
  (id: 129, name: 'Jazz'),
  (id: 98, name: 'Classical'),
  (id: 169, name: 'Soul & Funk'),
  (id: 153, name: 'Blues'),
  (id: 466, name: 'Folk'),
  (id: 144, name: 'Reggae'),
  (id: 197, name: 'Latin'),
  (id: 2, name: 'African music'),
  (id: 12, name: 'Arabic music'),
  (id: 16, name: 'Asian music'),
  (id: 75, name: 'Brazilian music'),
  (id: 81, name: 'Indian music'),
  (id: 52, name: 'French chanson'),
  (id: 173, name: 'Films & games'),
  (id: 95, name: 'Kids'),
];

/// Lookup of music that is *not* (necessarily) in the user's library.
abstract interface class CatalogueClient {
  Future<CatalogueResults> search(String query, {int limit = 8});

  /// Only the artists whose name matches [query] (the full [search] also asks for albums and songs).
  Future<List<CatalogueArtist>> searchArtists(String query, {int limit = 5});

  /// One artist / album by catalogue id (`null` when unknown or offline).
  Future<CatalogueArtist?> artist(String artistId);
  Future<CatalogueAlbum?> album(String albumId);

  Future<List<CatalogueTrack>> artistTopTracks(String artistId,
      {int limit = 10});

  /// Releases of an artist. The catalogue omits the artist on each release
  /// of this list, so [artistName] fills it in.
  Future<List<CatalogueAlbum>> artistAlbums(
    String artistId, {
    String? artistName,
    int limit = 200,
  });
  Future<List<CatalogueTrack>> albumTracks(String albumId);

  /// What is on top in a genre (empty when offline).
  Future<CatalogueGenreChart> genreChart(int genreId);
}
