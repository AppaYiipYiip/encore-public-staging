import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/logger.dart';
import '../../data/catalogue/catalogue_models.dart';
import '../../domain/album_names.dart';
import '../../domain/text_match.dart';
import '../providers.dart';
import '../requests/request_providers.dart' show catalogueClientProvider;

/// A song the library holds, as far as telling what an album still lacks goes.
@immutable
class OwnedTrack {
  const OwnedTrack({required this.title, this.number});

  final String title;

  /// Position on the album, when the library knows it.
  final int? number;
}

/// What an album the library holds only part of is missing (B39: "Animals by
/// Pink Floyd has 5 songs, not 2"), taken from the catalogue.
@immutable
class AlbumGap {
  const AlbumGap({
    required this.total,
    required this.ownedCount,
    required this.missing,
  });

  /// Songs on the album.
  final int total;

  /// Songs of it the library holds.
  final int ownedCount;

  /// The rest, in album order.
  final List<CatalogueTrack> missing;
}

/// The songs [owned] does not cover, or `null` when there is nothing to say:
/// the library holds the album whole, the catalogue has no album that is
/// certainly the same one, or the catalogue cannot be reached. It never
/// throws and never guesses:
///
/// * the catalogue album must have the same artist and title (accents, case,
///   "The" and edition suffixes such as "(2018 Remastered)" ignored), so
///   "Animals" is never "Animals as Leaders" or "Animals Live";
/// * it must hold at least as many songs as the library does (an EP of the
///   same name is not the album);
/// * of several editions it takes the one closest to what is owned;
/// * if the library's song names do not line up with the catalogue's, it says
///   nothing instead of listing songs that are already here.
Future<AlbumGap?> findAlbumGap({
  required CatalogueClient catalogue,
  required String artist,
  required String album,
  required List<OwnedTrack> owned,
}) async {
  try {
    final found = await catalogue.search('$artist $album', limit: 10);
    final want = matchKey(artist, album);
    final candidates = [
      for (final a in found.albums)
        if (matchKey(a.artistName, a.title) == want &&
            (a.trackCount ?? 0) >= owned.length)
          a,
    ]..sort((a, b) => a.trackCount!.compareTo(b.trackCount!));
    if (candidates.isEmpty) return null;

    final tracks = await catalogue.albumTracks(candidates.first.id);
    if (tracks.length < owned.length) return null;
    final missing = [
      for (final t in tracks)
        if (!owned.any((o) => _sameSong(o, t))) t,
    ];
    // More owned plus missing than the album has: some of the library's songs
    // are named so differently that they matched nothing, so "missing" may
    // hold songs that are here. Say nothing rather than list a song twice.
    if (missing.isEmpty || owned.length + missing.length > tracks.length) {
      return null;
    }
    return AlbumGap(
      total: tracks.length,
      ownedCount: owned.length,
      missing: missing,
    );
  } on Exception catch (error) {
    Log.debug('album', 'no album completion: ${error.runtimeType}');
    return null;
  }
}

/// The same title, or - at the same position on the album - titles that open
/// with the same words: the library's "Pigs On The Wing (Part One)" is the
/// catalogue's "Pigs on the Wing 1", and "Another Brick in the Wall, Pt. 2" is
/// "(Part 2)". The position keeps "(Part 1)" and "(Part 2)" apart.
bool _sameSong(OwnedTrack owned, CatalogueTrack track) {
  final a = normalizeForMatch(owned.title);
  final b = normalizeForMatch(track.title);
  if (a == b) return true;
  if (owned.number == null || owned.number != track.trackNumber) return false;
  final wa = a.split(' ').where((w) => w.isNotEmpty).toList();
  final wb = b.split(' ').where((w) => w.isNotEmpty).toList();
  if (wa.isEmpty || wb.isEmpty) return false;
  var shared = 0;
  while (shared < wa.length && shared < wb.length && wa[shared] == wb[shared]) {
    shared++;
  }
  final shorter = wa.length < wb.length ? wa.length : wb.length;
  return shared >= (shorter < 3 ? shorter : 3);
}

/// What the album page [albumId] is missing; `null` while it is looked up, when
/// the catalogue is out of reach, and when nothing is missing - the page never
/// waits for it.
final albumGapProvider =
    FutureProvider.autoDispose.family<AlbumGap?, String>((ref, albumId) async {
  final album = await ref.watch(albumProvider(albumId).future);
  final tracks = await ref.watch(albumTracksProvider(albumId).future);
  final artist = album?.artist;
  if (album == null || artist == null || tracks.isEmpty) return null;
  // The server's catch-all for songs with no album is not a release: the catalogue has nothing to compare it with.
  if (isCatchAllAlbum(album.name)) return null;
  return findAlbumGap(
    catalogue: ref.watch(catalogueClientProvider),
    artist: artist,
    album: album.name,
    owned: [
      for (final t in tracks) OwnedTrack(title: t.title, number: t.trackNo),
    ],
  );
});
