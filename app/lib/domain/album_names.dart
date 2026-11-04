/// The catch-all "album" a music server makes for songs that have no album.
///
/// Navidrome files every song without an album tag under one invented "album" per artist, named `[Unknown Album]`. It is a bucket, not a
/// release: on a new person's Home it showed as an album card with a grey "UA" cover and told them nothing (found by a friend's first
/// Home screen, 2026-11-03). So the app names the bucket in plain words and keeps it out of the shelves of releases.
///
/// Why the songs have no album is a separate matter and fixed at its source (the Spotify import reads no album at all; the catalogue
/// work fills it in). This rule stays right after that: some songs genuinely have no album (live cuts, uploads), and they must still show
/// as songs, not as a release called "[Unknown Album]".
library;

/// What the bucket is called to a person.
const String kNoAlbumLabel = 'Songs without an album';

/// The literal the music server uses (compared without case and stray spaces).
const String _serverBucketName = '[unknown album]';

/// True for the music server's catch-all "album" for untagged songs. A real album that merely has "unknown" in its name is not one.
bool isCatchAllAlbum(String? name) =>
    (name ?? '').trim().toLowerCase() == _serverBucketName;

/// The album to print or paint for a SONG: nothing when it has none or only the server's catch-all. A song of that bucket shows as a song
/// with no album (no "Artist • [Unknown Album]" line, no grey "UA" cover, no "Playing from [Unknown Album]"), like any song the app
/// already shows without an album.
String? realAlbumName(String? name) => isCatchAllAlbum(name) ? null : name;

/// What to print for an album's name: the plain-words name for the bucket, anything else untouched.
String albumDisplayName(String name) =>
    isCatchAllAlbum(name) ? kNoAlbumLabel : name;

/// The releases in [albums]: the catch-all bucket is dropped, the order kept. For the shelves that show releases (Home).
List<T> withoutCatchAllAlbums<T>(
  Iterable<T> albums,
  String Function(T album) nameOf,
) =>
    [
      for (final a in albums)
        if (!isCatchAllAlbum(nameOf(a))) a,
    ];
