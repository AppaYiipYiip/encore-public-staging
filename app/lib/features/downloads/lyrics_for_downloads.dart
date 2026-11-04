import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../core/logger.dart';
import '../../domain/album_names.dart';
import '../providers.dart';
import '../settings/settings_controller.dart';

/// "Download the songs *and their lyrics*": once a song is on the phone its
/// lyrics are fetched too (server first, then LRCLIB) and cached, so the
/// lyrics screen works offline for everything that was downloaded - not only
/// for what happened to be played while online.
///
/// Gentle on purpose: one lookup at a time, a short pause between them, only
/// when there is a connection (and Wi-Fi when downloads are Wi-Fi only), and a
/// track that has no lyrics anywhere is remembered by the repository for a day.
final lyricsForDownloadsProvider = Provider<void>((ref) {
  final handled = <String>{};
  var running = false;
  var disposed = false;
  ref.onDispose(() => disposed = true);

  Future<void> drain() async {
    if (running) return;
    running = true;
    try {
      while (!disposed) {
        final network = ref.read(networkKindProvider).value;
        if (network == null || network == NetworkKind.none) return;
        if (network == NetworkKind.mobile &&
            ref.read(settingsProvider).wifiOnlyDownloads) {
          return;
        }
        final downloaded = ref.read(downloadedIdsProvider).value;
        final lyrics = ref.read(lyricsRepositoryProvider);
        final library = ref.read(libraryRepositoryProvider);
        if (downloaded == null || lyrics == null || library == null) return;

        String? next;
        for (final id in downloaded) {
          if (!handled.contains(id)) {
            next = id;
            break;
          }
        }
        if (next == null) return;
        handled.add(next);

        final track = await library.watchTrack(next).first;
        if (track == null || disposed) continue;
        try {
          await lyrics.load(
            trackId: track.id,
            title: track.title,
            artist: track.artist,
            album: realAlbumName(track.album),
            durationSec: track.durationSec,
          );
        } on Object catch (error) {
          Log.debug('lyrics', 'download lyrics failed for $next: $error');
        }
        // Do not hammer the lyrics service when hundreds of songs arrive.
        await Future<void>.delayed(const Duration(milliseconds: 400));
      }
    } finally {
      running = false;
    }
  }

  ref.listen(downloadedIdsProvider, (_, __) => unawaited(drain()));
  ref.listen(networkKindProvider, (_, __) => unawaited(drain()));
  unawaited(drain());
});
