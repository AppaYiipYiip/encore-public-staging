import 'dart:convert';

import 'package:crypto/crypto.dart';

import '../api/opensubsonic/models.dart';
import '../encore/encore_models.dart';

/// Stable content hashes used for change detection (docs/02-architecture.md
/// section 5.3). MD5 is used for speed/portability, not for security.

const _sep = '\u0001';

String _hash(Iterable<Object?> parts) =>
    md5.convert(utf8.encode(parts.map((p) => p ?? '').join(_sep))).toString();

/// Everything that is *displayed* about a track. A change means "the song
/// changed on the server" and the UI row is rewritten.
String trackFingerprint(SsSong s) => _hash([
      s.title,
      s.album,
      s.artist,
      s.albumId,
      s.artistId,
      s.trackNo,
      s.discNo,
      s.year,
      s.genre,
      s.coverArt,
      s.durationSec,
      s.size,
      s.suffix,
      s.bitRate,
      s.path,
      s.musicBrainzId,
      s.isrc,
      s.rgTrackGain,
      s.rgAlbumGain,
    ]);

/// Only the properties of the *audio file*. Tag-only edits keep this stable, so
/// a downloaded copy is not re-fetched for a typo fix; a re-encode or replaced
/// file changes it and marks the copy stale.
String audioKeyOf(SsSong s) => _hash(
    [s.size, s.suffix, s.bitRate, s.durationSec, s.samplingRate, s.bitDepth]);

String albumFingerprint(SsAlbum a) => _hash([
      a.name,
      a.artist,
      a.artistId,
      a.year,
      a.genre,
      a.coverArt,
      a.songCount,
      a.durationSec,
      a.musicBrainzId,
      a.recordLabel,
      a.isCompilation,
    ]);

String artistFingerprint(SsArtist a) => _hash([
      a.name,
      a.sortName,
      a.coverArt,
      a.albumCount,
      a.musicBrainzId,
      a.imageUrl,
    ]);

/// Order-insensitive hash of a set of ids (shuffled smart playlists, ADR-025).
String memberSetHashOf(Iterable<String> ids) {
  final sorted = ids.toList()..sort();
  return _hash(sorted);
}

/// Everything displayed about a ref (title, artists, album, what the server's file says): a change rewrites the row.
String refFingerprint(EncoreRef r) => _hash([
      r.title,
      r.artists.join(''),
      r.album,
      r.albumArtist,
      r.trackNo,
      r.discNo,
      r.year,
      r.durationMs,
      r.isrc,
      r.mbid,
      r.videoId,
      r.coverUrl,
      r.explicit,
      r.file?.navidromeSongId,
      r.file?.albumId,
      r.file?.artistId,
      r.file?.coverArt,
      r.file?.genre,
    ]);

/// Only the audio of the server's file (like [audioKeyOf]): a replaced or re-encoded file changes it, a tag edit does not.
String refAudioKey(EncoreRef r) => r.file == null
    ? ''
    : _hash([
        r.file!.size,
        r.file!.suffix,
        r.file!.bitrateKbps,
        r.durationSec,
        r.file!.samplingRate,
        r.file!.bitDepth,
      ]);
