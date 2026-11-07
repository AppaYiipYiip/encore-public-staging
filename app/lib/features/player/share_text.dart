import 'playback_facade.dart';

/// What the Share button of the full player sends (P1-24, D-66): the song's name and artist and, when the app knows the YouTube video the
/// song is (an imported playlist's songs), the public address of that video.
///
/// **Never an address of the person's own server, a signed stream address or anything private:** a library song, a song with no known video
/// and a Jam's song are shared by name only.
String shareTextFor(NowPlayingTrack track) {
  final artist = (track.artist ?? '').trim();
  final name = artist.isEmpty ? track.title : '${track.title} by $artist';
  final video = (track.videoId ?? '').trim();
  return video.isEmpty
      ? name
      : '$name\nhttps://music.youtube.com/watch?v=$video';
}

/// What the Lyrics card's share button sends: the lines the card shows, then the song's own name.
String shareLyricsTextFor(NowPlayingTrack track, List<String> lines) {
  final shown = lines.where((l) => l.trim().isNotEmpty).join('\n');
  final artist = (track.artist ?? '').trim();
  final name = artist.isEmpty ? track.title : '${track.title} by $artist';
  return shown.isEmpty ? name : '$shown\n\n$name';
}
