import 'dart:io';

import '../domain/audio_quality.dart';
import 'audio_backend.dart';
import 'queue_model.dart';

/// Decides *what* to play for a queue entry: the downloaded file when it is
/// there and current, otherwise a stream URL at the quality the user set
/// for the current network (ADR-036).
abstract interface class SourceResolver {
  Future<AudioSourceSpec> resolve(QueueItem item);
}

/// The address of a song could not be made because the music server does not answer (no address of it has proved itself). The song is not
/// broken: the player waits for the server instead of trying the next song (docs/33 G-1).
class ServerNotAnswering implements Exception {
  const ServerNotAnswering();

  @override
  String toString() => 'ServerNotAnswering';
}

typedef LocalPathLookup = Future<String?> Function(String trackId);
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

  @override
  Future<AudioSourceSpec> resolve(QueueItem item) async {
    final direct = item.directUri;
    if (direct != null) return AudioSourceSpec(uid: item.uid, uri: direct);
    final local = await _localPath(item.id);
    if (local != null && _fileExists(local)) {
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
