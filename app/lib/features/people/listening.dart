import '../../data/people/activity_publisher.dart';
import '../player/playback_facade.dart';

/// What the player is doing, as a friend may be told about it (docs/35,
/// section 3), or `null` when there is nothing to tell:
///
/// * nothing is playing, or
/// * it is a 30-second sample from the catalogue (it has a picture address but
///   was not fetched for the person: [isFetchedSong] says whether it was).
///
/// A library song carries no picture address, so friends see it without a
/// cover: the library's cover needs the person's login and is never shared.
ListeningState? listeningFrom(
  PlaybackSnapshot snapshot, {
  required bool Function(NowPlayingTrack track) isFetchedSong,
}) {
  final track = snapshot.track;
  if (track == null) return null;
  final hasPicture = track.imageUrl != null;
  if (hasPicture && !isFetchedSong(track)) return null; // a sample
  return ListeningState(
    id: track.id,
    title: track.title,
    artist: track.artist,
    album: track.album,
    coverUrl: track.imageUrl,
    playing: snapshot.isPlaying,
  );
}
