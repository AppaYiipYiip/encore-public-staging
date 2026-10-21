import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/logger.dart';
import '../providers.dart';

/// Fetches lyrics for the playing track and the one after it in the
/// background, so opening the lyrics screen shows text instantly instead of a
/// spinner (FB-005). Results are cached by the repository (works offline
/// afterwards); a track without lyrics is remembered for a day.
final lyricsPrefetchProvider = Provider<void>((ref) {
  final requested = <String>{};

  Future<void> fetch({
    required String id,
    required String title,
    String? artist,
    String? album,
    Duration? duration,
  }) async {
    if (!requested.add(id)) return;
    final repo = ref.read(lyricsRepositoryProvider);
    if (repo == null) return;
    try {
      await repo.load(
        trackId: id,
        title: title,
        artist: artist,
        album: album,
        durationSec: duration?.inSeconds,
      );
    } on Object catch (error) {
      Log.debug('lyrics', 'prefetch failed for $id: $error');
    }
  }

  ref.listen(playbackSnapshotProvider, (previous, next) {
    final track = next.value?.track;
    if (track == null) return;
    // Library tracks only: a catalogue preview has no server id.
    if (track.id.isEmpty || track.coverArt == null && track.imageUrl != null) {
      return;
    }
    unawaited(fetch(
      id: track.id,
      title: track.title,
      artist: track.artist,
      album: track.album,
      duration: track.duration,
    ));

    final upNext = ref.read(playbackFacadeProvider).queue.upNext;
    if (upNext.isNotEmpty) {
      final n = upNext.first;
      unawaited(fetch(
        id: n.id,
        title: n.title,
        artist: n.artist,
        album: n.album,
        duration: n.duration,
      ));
    }
  });
});
