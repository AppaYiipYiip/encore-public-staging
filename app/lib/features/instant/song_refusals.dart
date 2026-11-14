import 'package:flutter_riverpod/flutter_riverpod.dart';

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
