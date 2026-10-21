import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers.dart';
import 'jam_providers.dart';
import 'jam_song_player.dart';
import 'jam_speaker.dart';

/// How this phone starts a Jam song (tests replace it).
final jamSongPlayerProvider =
    Provider<JamSongPlayer>((ref) => SessionJamSongPlayer(ref.read));

/// The phone's side of a Jam: when this phone is the speaker it plays what the
/// Jam says and tells the Jam what really happens. Watched once by the app
/// widget; it does nothing while there is no Jam.
final jamSpeakerProvider = Provider<JamSpeaker>((ref) {
  final controller = ref.read(jamControllerProvider.notifier);
  final speaker = JamSpeaker(
    // The real player: the speaker makes the sound the Jam asks for.
    facade: ref.watch(enginePlaybackFacadeProvider),
    songs: ref.watch(jamSongPlayerProvider),
    send: controller.send,
    positionNowMs: controller.positionNowMs,
    notify: controller.say,
    onLoading: (loading) => ref.read(jamLoadingProvider.notifier).set(loading),
  )..attach();
  ref.onDispose(speaker.dispose);
  ref.listen(
    jamControllerProvider,
    (_, next) => unawaited(speaker.onSession(next)),
  );
  return speaker;
});
