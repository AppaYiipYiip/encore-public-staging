import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/encore/encore_api.dart' show EncoreApi;

/// How many songs the server has refused **for good** during this session: a stream answered `song_unavailable` (the player asks the server why a
/// stream failed), or a tap found that the server already knew it could not get the song (N-13, B-128).
///
/// A refusal is evidence that the server's memory of what it cannot get has changed since the phone last asked. The marks (`song_marks.dart`) read this
/// number: when it moves, every "no problem" answer is stale and the lists on screen ask again at once. The phone does not copy what the server knows
/// (its reason, its sentence, how long it believes it): it asks. This is a file of its own so that the player's wiring and the instant-play controller
/// can say it without importing the marks, which import them.
final songRefusalsProvider =
    NotifierProvider<SongRefusals, int>(SongRefusals.new);

class SongRefusals extends Notifier<int> {
  @override
  int build() => 0;

  /// The server refused a song for good.
  void refused() => state = state + 1;
}

/// Asks the server why a stream failed (`null` for a server that is not an Encore server) and, when it refuses the song **for good**, says so through
/// [onRefusedForGood] (the marks ask the server again, B-128). Answers the player what it needs: the server's sentence and whether to give up on the song.
/// A failure that may pass (YouTube resting, a timeout) is not reported: the song may well be playable in a minute.
Future<({String message, bool permanent})?> askSongRefusal(
  EncoreApi? encore,
  Uri address, {
  required void Function() onRefusedForGood,
}) async {
  if (encore == null) return null;
  final why = await encore.streamRefusal(address);
  if (why == null) return null;
  if (why.permanent) onRefusedForGood();
  return (message: why.message, permanent: why.permanent);
}
