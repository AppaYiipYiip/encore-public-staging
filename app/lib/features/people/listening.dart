import '../../data/people/activity_publisher.dart';
import '../player/playback_facade.dart';

/// What the player is doing, as a friend may be told about it (docs/35,
/// section 3), or `null` when nothing is playing.
///
/// A library song carries no picture address, so friends see it without a
/// cover: the library's cover needs the person's login and is never shared.
ListeningState? listeningFrom(PlaybackSnapshot snapshot) {
  final track = snapshot.track;
  if (track == null) return null;
  return ListeningState(
    id: track.id,
    title: track.title,
    artist: track.artist,
    album: track.album,
    coverUrl: track.imageUrl,
    playing: snapshot.isPlaying,
  );
}
