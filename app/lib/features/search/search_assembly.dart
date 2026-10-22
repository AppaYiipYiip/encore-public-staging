import '../../data/catalogue/catalogue_models.dart';
import '../../data/db/app_database.dart';
import '../../domain/search_rank.dart';
import '../../domain/text_match.dart';
import '../providers.dart' show SearchResults;

/// One result of any kind, the library's or the catalogue's, with how well it answers what was typed.
sealed class SearchHit {
  const SearchHit(this.score);

  final double score;

  /// The library has it.
  bool get owned;
}

class SongHit extends SearchHit {
  const SongHit.local(TrackRow this.local, super.score) : catalogue = null;
  const SongHit.catalogue(CatalogueTrack this.catalogue, super.score)
      : local = null;

  final TrackRow? local;
  final CatalogueTrack? catalogue;

  @override
  bool get owned => local != null;

  String get title => local?.title ?? catalogue!.title;
  String? get artist => local != null ? local!.artist : catalogue!.artistName;
  String? get album => local != null ? local!.album : catalogue!.albumTitle;
}

class ArtistHit extends SearchHit {
  const ArtistHit.local(ArtistRow this.local, super.score)
      : catalogue = null,
        libraryId = null;

  /// A catalogue artist; [libraryId] is the library's artist when the person has this one (its page shows what is missing), and
  /// [local] that artist's row when the library's own search found it too (one hit, with the catalogue's fans and releases).
  const ArtistHit.catalogue(CatalogueArtist this.catalogue, super.score,
      {this.libraryId, this.local});

  final ArtistRow? local;
  final CatalogueArtist? catalogue;
  final String? libraryId;

  @override
  bool get owned => local != null || libraryId != null;

  String get name => local?.name ?? catalogue!.name;
}

class AlbumHit extends SearchHit {
  const AlbumHit.local(AlbumRow this.local, super.score) : catalogue = null;
  const AlbumHit.catalogue(CatalogueAlbum this.catalogue, super.score)
      : local = null;

  final AlbumRow? local;
  final CatalogueAlbum? catalogue;

  @override
  bool get owned => local != null;

  String get title => local?.name ?? catalogue!.title;
  String? get artist => local != null ? local!.artist : catalogue!.artistName;
}

/// What the search screen shows: the Top result, then songs, artists and albums, each list ranked, the library's and the
/// catalogue's mixed (P1-07).
class AssembledSearch {
  const AssembledSearch({
    this.top,
    this.songs = const [],
    this.artists = const [],
    this.albums = const [],
  });

  final SearchHit? top;
  final List<SongHit> songs;
  final List<ArtistHit> artists;
  final List<AlbumHit> albums;

  bool get isEmpty =>
      top == null && songs.isEmpty && artists.isEmpty && albums.isEmpty;
}

/// An artist this many fans or more is "well known": an exact name match with a song's exact title goes to the artist only then.
const wellKnownFans = 50000;

/// Most rows of each kind below the Top result.
const maxSongRows = 8;
const maxArtistRows = 3;
const maxAlbumRows = 5;

/// Merges the library's results ([local]) with the catalogue's ([catalogue], `null` while it is still being asked or when there
/// is no network) for what was typed ([query]).
AssembledSearch assembleSearch(
  String query, {
  required SearchResults local,
  CatalogueResults? catalogue,
}) {
  // ---- songs: the library's first, then the catalogue's that the library does not have (the same song twice is one row)
  final songs = <Ranked<SongHit>>[];
  final ownedSongs = <String>{};
  for (final t in local.tracks) {
    ownedSongs.add(matchKey(t.artist, t.title));
    // The library's own search found it; a weak word match still belongs in the list, below the strong ones.
    final score = _atLeast(songMatch(query, artist: t.artist, title: t.title));
    songs.add(Ranked(SongHit.local(t, score), score, owned: true));
  }
  for (final t in catalogue?.tracks ?? const <CatalogueTrack>[]) {
    if (ownedSongs.contains(matchKey(t.artistName, t.title))) continue;
    final score = songMatch(query, artist: t.artistName, title: t.title);
    songs.add(Ranked(SongHit.catalogue(t, score), score, owned: false));
  }
  final rankedSongs = rankHits(songs);

  // ---- artists: the catalogue's first, so that an artist the library has shows the catalogue's fans and releases too
  final artists = <Ranked<ArtistHit>>[];
  final localById = {for (final a in local.artists) a.id: a};
  final merged = <String>{};
  for (final a in catalogue?.artists ?? const <CatalogueArtist>[]) {
    final libraryId = catalogue!.ownedArtists[a.id];
    final row = libraryId == null ? null : localById[libraryId];
    if (row != null) merged.add(row.id);
    // The catalogue lists collaborations and tribute acts with no releases next to the real artist: they come after it.
    final score = artistMatch(query, row?.name ?? a.name) *
        ((a.albumCount ?? 1) <= 0 ? 0.9 : 1);
    artists.add(Ranked(
        ArtistHit.catalogue(a, score, libraryId: libraryId, local: row), score,
        owned: libraryId != null));
  }
  for (final a in local.artists) {
    if (merged.contains(a.id)) continue;
    final score = _atLeast(artistMatch(query, a.name));
    artists.add(Ranked(ArtistHit.local(a, score), score, owned: true));
  }
  final rankedArtists = rankHits(artists);

  // ---- albums
  final albums = <Ranked<AlbumHit>>[];
  final ownedAlbums = <String>{};
  for (final a in local.albums) {
    ownedAlbums.add(matchKey(a.artist, a.name));
    final score = _atLeast(albumMatch(query, title: a.name, artist: a.artist));
    albums.add(Ranked(AlbumHit.local(a, score), score, owned: true));
  }
  for (final a in catalogue?.albums ?? const <CatalogueAlbum>[]) {
    if (ownedAlbums.contains(matchKey(a.artistName, a.title))) continue;
    final score = albumMatch(query, title: a.title, artist: a.artistName);
    albums.add(Ranked(AlbumHit.catalogue(a, score), score, owned: false));
  }
  final rankedAlbums = rankHits(albums);

  // ---- the best of the three is the Top result
  final bestSong = rankedSongs.isEmpty ? null : rankedSongs.first;
  final bestArtist = rankedArtists.isEmpty ? null : rankedArtists.first;
  final bestAlbum = rankedAlbums.isEmpty ? null : rankedAlbums.first;
  final pick = pickTop(
    song: bestSong?.score,
    artist: bestArtist?.score,
    album: bestAlbum?.score,
    artistWellKnown: bestArtist != null &&
        (bestArtist.owned ||
            (bestArtist.value.catalogue?.fans ?? 0) >= wellKnownFans),
  );
  final SearchHit? top = switch (pick?.kind) {
    HitKind.song => bestSong!.value,
    HitKind.artist => bestArtist!.value,
    HitKind.album => bestAlbum!.value,
    null => null,
  };

  return AssembledSearch(
    top: top,
    // The Top result is not listed again below it, and the same song on a compilation is not listed twice.
    songs: _withoutRepeats(
      [for (final h in rankedSongs) h.value],
      top: top,
    ).take(maxSongRows).toList(),
    artists: [
      for (final h in rankedArtists)
        if (!identical(h.value, top)) h.value,
    ].take(maxArtistRows).toList(),
    albums: [
      for (final h in rankedAlbums)
        if (!identical(h.value, top)) h.value,
    ].take(maxAlbumRows).toList(),
  );
}

/// What the library's own search found is never ranked as "nothing": it sits below every real match but above nothing.
double _atLeast(double score) => score < 0.15 ? 0.15 : score;

/// [songs] without the Top result and without a catalogue song that repeats an earlier one (the same artist and title on a
/// compilation, a soundtrack or a "best of"): the library's songs are never dropped.
List<SongHit> _withoutRepeats(List<SongHit> songs, {SearchHit? top}) {
  final seen = <String>{
    if (top is SongHit) matchKey(top.artist, top.title),
  };
  final kept = <SongHit>[];
  for (final s in songs) {
    if (identical(s, top)) continue;
    final key = matchKey(s.artist, s.title);
    if (!s.owned && !seen.add(key)) continue;
    seen.add(key);
    kept.add(s);
  }
  return kept;
}
