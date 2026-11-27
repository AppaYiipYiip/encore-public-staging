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
String audioKeyOf(SsSong s) => legacyAudioKey(
      size: s.size,
      suffix: s.suffix,
      bitRate: s.bitRate,
      durationSec: s.durationSec,
      samplingRate: s.samplingRate,
      bitDepth: s.bitDepth,
    );

/// The key of a file made from the properties of the file as the music server describes it. **It contains the file's SIZE, so a rewrite of the tags changes it**:
/// it is what a downloaded copy is compared with when the server serves no key of the audio (an older server, a file it has no key of, a plain music server),
/// and what an upgrade of a stored key is checked against (N-38, [downloadAudioKeyVerdict]). One definition, so the number a phone stored yesterday and the
/// number it computes today from the same columns are the same string.
String legacyAudioKey({
  required int? size,
  required String? suffix,
  required int? bitRate,
  required int? durationSec,
  required int? samplingRate,
  required int? bitDepth,
}) =>
    _hash([size, suffix, bitRate, durationSec, samplingRate, bitDepth]);

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

/// A key the SERVER made of a file's audio (`a1:` and 32 hex digits, docs/17): the prefix says which way made it. Anything else is a key this app made itself
/// ([legacyAudioKey]).
bool isServerAudioKey(String key) => _serverKey.hasMatch(key);
final _serverKey = RegExp(r'^a\d+:');

/// Only the audio of the server's file: a replaced or re-encoded file changes it, **a tag edit does not** (N-38).
///
/// When the server serves the key of the audio stream (`file.audioKey`) that is the key, as it is. Otherwise the key is made here from the file's properties, which
/// include its size ([legacyAudioKey]): so a tag rewrite on a server without keys is still seen as a changed file, as it always was.
String refAudioKey(EncoreRef r) {
  final file = r.file;
  if (file == null) return '';
  final served = file.audioKey;
  if (served != null && isServerAudioKey(served)) return served;
  return refLegacyAudioKey(r);
}

/// The key of [r]'s file as the app made it before the server served keys. Needed for the upgrade of a stored key: the copy a phone downloaded yesterday carries this kind.
String refLegacyAudioKey(EncoreRef r) {
  final file = r.file;
  if (file == null) return '';
  return legacyAudioKey(
    size: file.size,
    suffix: file.suffix,
    bitRate: file.bitrateKbps,
    durationSec: r.durationSec,
    samplingRate: file.samplingRate,
    bitDepth: file.bitDepth,
  );
}

/// What to do with a downloaded copy, from the key stored when it was downloaded ([stored]), the key the track has now ([live]) and what the old-formula key of the
/// track is now ([liveLegacy]; the size in it is the file's size as the server reports it). The migration of N-38: **a copy made before the server served keys must not
/// be downloaded again just because the formula changed.**
enum AudioKeyVerdict {
  /// The copy is the same sound (or nothing can be said): leave it.
  same,

  /// The sound changed (or the file was replaced or re-encoded): download it again.
  changed,

  /// The copy is the same file as when it was downloaded (its old-formula key still matches), and the server now serves a key of it: keep the copy and store the
  /// new key in its row, so that a later tag rewrite, which changes the size and not the key, is invisible.
  adopt,
}

AudioKeyVerdict downloadAudioKeyVerdict({
  required String stored,
  required String live,
  required String liveLegacy,
}) {
  if (live.isEmpty || stored.isEmpty || stored == live) {
    return AudioKeyVerdict.same; // nothing to compare, or the same
  }
  final storedIsServer = isServerAudioKey(stored);
  final liveIsServer = isServerAudioKey(live);
  if (storedIsServer && liveIsServer) {
    // Two server keys: equal means the same sound. Two different WAYS of making a key (a1 and a2) are never compared (a new way brings its own migration here):
    // they say nothing about each other, and the copy stays.
    return _wayOf(stored) == _wayOf(live)
        ? AudioKeyVerdict.changed
        : AudioKeyVerdict.same;
  }
  if (storedIsServer) {
    // The server stopped serving keys for this file (a server downgrade, a file it cannot read now): a key from a way that cannot be computed here says nothing.
    return AudioKeyVerdict.same;
  }
  if (liveIsServer) {
    // The copy carries an old-formula key, the server now serves a key of the audio: the copy is current if the file is as it was.
    return stored == liveLegacy
        ? AudioKeyVerdict.adopt
        : AudioKeyVerdict.changed;
  }
  return AudioKeyVerdict.changed; // two old-formula keys that differ: as before
}

String _wayOf(String serverKey) =>
    serverKey.substring(0, serverKey.indexOf(':'));
