import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../data/catalogue/catalogue_models.dart';
import '../../data/repos/request_repository.dart';
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
  const ArtistRelease(this.album, {this.libraryAlbumId});

  final CatalogueAlbum album;

  /// Id of the matching album in the library, `null` when not owned.
  final String? libraryAlbumId;

  bool get owned => libraryAlbumId != null;
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

  final found = await client.search(artist.name, limit: 8);
  final want = normalizeForMatch(artist.name);
  final same = [
    for (final a in found.artists)
      if (normalizeForMatch(a.name) == want && (a.albumCount ?? 1) > 0) a,
  ];
  if (same.isEmpty) return null;
  if (same.length == 1) return same.first;

  same.sort((a, b) => (b.fans ?? 0).compareTo(a.fans ?? 0));
  final mine = {for (final a in albums) normalizeForMatch(a.name)};
  CatalogueArtist? best;
  var bestOverlap = -1;
  for (final candidate in same.take(3)) {
    final theirs = await client.artistAlbums(candidate.id,
        artistName: candidate.name, limit: 50);
    final overlap =
        theirs.where((t) => mine.contains(normalizeForMatch(t.title))).length;
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
  final out = <ArtistRelease>[];
  for (final album in foldReleases(raw)) {
    final owned = await matcher?.findAlbum(album.artistName, album.title);
    out.add(ArtistRelease(album, libraryAlbumId: owned?.id));
  }
  return out;
});
