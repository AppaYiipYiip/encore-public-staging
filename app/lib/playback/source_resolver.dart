import 'dart:io';

import '../domain/audio_quality.dart';
import 'audio_backend.dart';
import 'queue_model.dart';

/// Decides *what* to play for a queue entry: the downloaded file when it is
/// there and current, otherwise a stream URL at the quality the user set
/// for the current network (ADR-036).
abstract interface class SourceResolver {
  Future<AudioSourceSpec> resolve(QueueItem item);

  /// Whether the song is a file on this phone, answered from the phone alone: no address is made and the server is not asked. [resolve] cannot
  /// say this cheaply: for a song that is not a file it may wait for the session, look at the server's addresses and ask the server to sign one,
  /// which is real work (N-20: the player must be able to ask "is it a file?" before it looks at the server, for every song it considers).
  Future<bool> isOnPhone(QueueItem item);
}

/// The address of a song could not be made because the music server does not answer (no address of it has proved itself). The song is not
/// broken: the player waits for the server instead of trying the next song (docs/33 G-1).
class ServerNotAnswering implements Exception {
  const ServerNotAnswering();

  @override
  String toString() => 'ServerNotAnswering';
}

typedef LocalPathLookup = Future<String?> Function(String trackId);

/// Which of the coming songs the server should make ready before Next is pressed (P1-04): the ones that will be streamed, that is, not downloaded and
/// not played from a plain address. A downloaded song plays from the phone and needs nothing from the server.
Future<List<String>> idsToPrepare(
  List<QueueItem> upcoming,
  LocalPathLookup localPath, {
  bool Function(String path)? fileExists,
}) async {
  final exists = fileExists ?? ((p) => File(p).existsSync());
  final ids = <String>[];
  for (final item in upcoming) {
    if (item.directUri != null) continue;
    final local = await localPath(item.id);
    if (local != null && exists(local)) continue;
    ids.add(item.id);
  }
  return ids;
}

typedef StreamUrlBuilder = Future<Uri> Function(
  String trackId, {
  int? maxBitRate,
  String? format,
});

class DefaultSourceResolver implements SourceResolver {
  DefaultSourceResolver({
    required LocalPathLookup localPath,
    required StreamUrlBuilder streamUrl,
    required AudioQuality Function() streamQuality,
    bool Function(String path)? fileExists,
  })  : _localPath = localPath,
        _streamUrl = streamUrl,
        _streamQuality = streamQuality,
        _fileExists = fileExists ?? ((p) => File(p).existsSync());

  final LocalPathLookup _localPath;
  final StreamUrlBuilder _streamUrl;
  final AudioQuality Function() _streamQuality;
  final bool Function(String path) _fileExists;

  /// Containers that are already lossy; re-encoding them to a *higher or
  /// equal* bit rate only adds generation loss and server CPU.
  static const _lossy = {'mp3', 'opus', 'ogg', 'aac', 'm4a'};

  /// The downloaded file of the song, when it is there; `null` for a song that is played from an address or not downloaded.
  Future<String?> _downloadedFile(QueueItem item) async {
    if (item.directUri != null) return null;
    final local = await _localPath(item.id);
    return local != null && _fileExists(local) ? local : null;
  }

  @override
  Future<bool> isOnPhone(QueueItem item) async =>
      await _downloadedFile(item) != null;

  @override
  Future<AudioSourceSpec> resolve(QueueItem item) async {
    final direct = item.directUri;
    if (direct != null) return AudioSourceSpec(uid: item.uid, uri: direct);
    final local = await _downloadedFile(item);
    if (local != null) {
      return AudioSourceSpec(
          uid: item.uid, uri: Uri.file(local), isLocal: true);
    }
    final quality = _streamQuality();
    return AudioSourceSpec(
      uid: item.uid,
      uri: await _streamUri(item, quality),
    );
  }

  Future<Uri> _streamUri(QueueItem item, AudioQuality quality) {
    if (quality.isOriginal) return _streamUrl(item.id);
    final cap = quality.bitRate!;
    final lossy = _lossy.contains(item.suffix?.toLowerCase());
    final already = item.bitRate != null && item.bitRate! <= cap;
    if (lossy && already) return _streamUrl(item.id);
    return _streamUrl(item.id, maxBitRate: cap, format: quality.format);
  }
}
