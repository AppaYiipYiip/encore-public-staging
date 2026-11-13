import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../data/catalogue/catalogue_models.dart';
import '../../data/db/app_database.dart' show AlbumRow;
import '../../data/repos/request_repository.dart';
import '../../domain/album_names.dart';
import '../../domain/text_match.dart';
import '../providers.dart';
import '../requests/request_providers.dart';

/// Matches catalogue items against the library; `null` before a server is
/// configured.
final libraryMatcherProvider = Provider<LibraryMatcher?>((ref) {
  final id = ref.watch(activeServerIdProvider).value;
  if (id == null) return null;
  return LibraryMatcher(ref.watch(databaseProvider), id);
});

/// One catalogue album by id (the page normally receives it from the search
/// result; this is the fallback when it was opened without one).
final catalogueAlbumProvider = FutureProvider.autoDispose
    .family<CatalogueAlbum?, String>(
        (ref, id) => ref.watch(catalogueClientProvider).album(id));

final catalogueAlbumTracksProvider = FutureProvider.autoDispose
    .family<List<CatalogueTrack>, String>(
        (ref, id) => ref.watch(catalogueClientProvider).albumTracks(id));

final catalogueArtistProvider = FutureProvider.autoDispose
    .family<CatalogueArtist?, String>(
        (ref, id) => ref.watch(catalogueClientProvider).artist(id));

/// What is on top in a genre of the catalogue (the Browse grid's pages).
final catalogueGenreChartProvider = FutureProvider.autoDispose
    .family<CatalogueGenreChart, int>(
        (ref, id) => ref.watch(catalogueClientProvider).genreChart(id));

final catalogueArtistTopProvider = FutureProvider.autoDispose
    .family<List<CatalogueTrack>, String>((ref, id) =>
        ref.watch(catalogueClientProvider).artistTopTracks(id, limit: 10));

/// One release of an artist, with the library album when the user owns it.
@immutable
class ArtistRelease {
  const ArtistRelease(this.album, {this.libraryAlbumId, this.libraryCoverArt});

  final CatalogueAlbum album;

  /// Id of the matching album in the library, `null` when not owned.
  final String? libraryAlbumId;

  /// The library's own cover of that album (kept on the phone, so it also shows offline).
  final String? libraryCoverArt;

  bool get owned => libraryAlbumId != null;
}

/// [releases] (newest first) with the library's own albums that the catalogue did not match added as albums: a rip, a local release, a
/// title spelt differently. A person's own album never disappears from their artist page because the catalogue does not list it.
List<ArtistRelease> withLibraryAlbums(
    List<ArtistRelease> releases, List<AlbumRow> library) {
  final shown = {
    for (final r in releases)
      if (r.libraryAlbumId != null) r.libraryAlbumId,
  };
  final extra = [
    for (final a in library)
      if (!shown.contains(a.id))
        ArtistRelease(
          CatalogueAlbum(
            id: 'library:${a.id}',
            title: albumDisplayName(a.name),
            artistName: a.artist ?? '',
            year: a.year,
            recordType: 'album',
          ),
          libraryAlbumId: a.id,
          libraryCoverArt: a.coverArt,
        ),
  ];
  if (extra.isEmpty) return releases;
  // Newest first, and the catalogue's own order kept for equal years.
  final all = [...releases, ...extra];
  final order = {for (var i = 0; i < all.length; i++) all[i]: i};
  all.sort((a, b) {
    final byYear = (b.album.year ?? 0).compareTo(a.album.year ?? 0);
    return byYear != 0 ? byYear : order[a]!.compareTo(order[b]!);
  });
  return all;
}

/// An artist's releases split the way streaming apps do.
@immutable
class ReleaseGroups {
  const ReleaseGroups({
    this.albums = const [],
    this.singles = const [],
    this.compilations = const [],
  });

  final List<ArtistRelease> albums;

  /// Singles and EPs.
  final List<ArtistRelease> singles;
  final List<ArtistRelease> compilations;

  bool get isEmpty => albums.isEmpty && singles.isEmpty && compilations.isEmpty;
}

/// Splits [releases] (already newest first) by record type. Unknown types
/// are treated as albums so nothing disappears.
ReleaseGroups groupReleases(List<ArtistRelease> releases) {
  final albums = <ArtistRelease>[];
  final singles = <ArtistRelease>[];
  final compilations = <ArtistRelease>[];
  for (final r in releases) {
    switch (r.album.recordType) {
      case 'single' || 'ep':
        singles.add(r);
      case 'compile':
        compilations.add(r);
      default:
        albums.add(r);
    }
  }
  return ReleaseGroups(
    albums: albums,
    singles: singles,
    compilations: compilations,
  );
}

/// Releases newest first with clean/explicit/deluxe duplicates folded into
/// one row (compared by normalised title).
List<CatalogueAlbum> foldReleases(List<CatalogueAlbum> albums) {
  final sorted = [...albums]..sort((a, b) {
      final ay = a.year ?? 0;
      final by = b.year ?? 0;
      return by.compareTo(ay);
    });
  final seen = <String>{};
  return [
    for (final a in sorted)
      if (seen.add(normalizeForMatch(a.title))) a,
  ];
}

/// The catalogue artist that *is* the library artist [artistId] (so an artist
/// page can list what the library lacks), or `null` offline / when the
/// catalogue does not know the name.
///
/// Several artists may share a name. The one whose releases overlap the
/// library's albums is taken; with no overlap, the best known one (most fans).
final libraryArtistCatalogueProvider = FutureProvider.autoDispose
    .family<CatalogueArtist?, String>((ref, artistId) async {
  final network = ref.watch(networkKindProvider).value;
  if (network == NetworkKind.none) return null;
  final artist = await ref.watch(artistProvider(artistId).future);
  if (artist == null) return null;
  final albums = await ref.watch(artistAlbumsProvider(artistId).future);
  final client = ref.watch(catalogueClientProvider);

  // Only the artists are wanted: the full search also asks for albums and songs (three requests where one is enough).
  final found = await client.searchArtists(artist.name, limit: 8);
  final want = normalizeForMatch(artist.name);
  final same = [
    for (final a in found)
      if (normalizeForMatch(a.name) == want && (a.albumCount ?? 1) > 0) a,
  ];
  if (same.isEmpty) return null;
  if (same.length == 1) return same.first;

  same.sort((a, b) => (b.fans ?? 0).compareTo(a.fans ?? 0));
  final mine = {for (final a in albums) normalizeForMatch(a.name)};
  CatalogueArtist? best;
  var bestOverlap = -1;
  final candidates = same.take(3).toList();
  // The namesakes' releases are asked together, not one after the other.
  final releases = await Future.wait([
    for (final c in candidates)
      client.artistAlbums(c.id, artistName: c.name, limit: 50),
  ]);
  for (var i = 0; i < candidates.length; i++) {
    final candidate = candidates[i];
    final overlap = releases[i]
        .where((t) => mine.contains(normalizeForMatch(t.title)))
        .length;
    if (overlap > bestOverlap) {
      best = candidate;
      bestOverlap = overlap;
    }
  }
  return best ?? same.first;
});

/// Key: `(artistId, artistName)`.
final catalogueArtistReleasesProvider = FutureProvider.autoDispose
    .family<List<ArtistRelease>, (String, String)>((ref, key) async {
  final raw = await ref
      .watch(catalogueClientProvider)
      .artistAlbums(key.$1, artistName: key.$2);
  final matcher = ref.watch(libraryMatcherProvider);
  final albums = foldReleases(raw);
  // One look-up per release, asked together (an artist with 150 releases made 150 round trips to the database one after the other).
  final owned = await Future.wait([
    for (final album in albums)
      matcher?.findAlbum(album.artistName, album.title) ??
          Future<AlbumRow?>.value(),
  ]);
  return [
    for (var i = 0; i < albums.length; i++)
      ArtistRelease(albums[i],
          libraryAlbumId: owned[i]?.id, libraryCoverArt: owned[i]?.coverArt),
  ];
});
