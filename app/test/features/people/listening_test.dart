import 'package:encore/features/people/listening.dart';
import 'package:encore/features/player/playback_facade.dart';
import 'package:flutter_test/flutter_test.dart';

/// What the player is doing, as a friend may be told about it (docs/35,
/// section 3): a real song, never a 30-second clip, never a library cover.
void main() {
  PlaybackSnapshot snapshot({
    String? imageUrl,
    bool playing = true,
    bool withTrack = true,
  }) =>
      PlaybackSnapshot(
        track: withTrack
            ? NowPlayingTrack(
                id: 'song-1',
                title: 'Dogs',
                artist: 'Pink Floyd',
                album: 'Animals',
                coverArt: 'cover-1',
                imageUrl: imageUrl,
              )
            : null,
        isPlaying: playing,
      );

  bool never(NowPlayingTrack _) => false;
  bool always(NowPlayingTrack _) => true;

  test('a library song is shared with its title, artist and album, no cover',
      () {
    final state = listeningFrom(snapshot(), isFetchedSong: never)!;

    expect(state.title, 'Dogs');
    expect(state.artist, 'Pink Floyd');
    expect(state.album, 'Animals');
    expect(state.playing, isTrue);
    expect(state.coverUrl, isNull,
        reason: 'a library cover needs the person\'s login');
  });

  test('paused is paused', () {
    expect(
        listeningFrom(snapshot(playing: false), isFetchedSong: never)!.playing,
        isFalse);
  });

  test('nothing playing is nothing to share', () {
    expect(listeningFrom(PlaybackSnapshot.idle, isFetchedSong: never), isNull);
    expect(listeningFrom(snapshot(withTrack: false), isFetchedSong: never),
        isNull);
  });

  test('a 30-second sample is not what the person is listening to', () {
    final sample = snapshot(imageUrl: 'https://cdn.example/s.jpg');

    expect(listeningFrom(sample, isFetchedSong: never), isNull);
  });

  test('a song fetched for the person shares its public picture', () {
    final fetched = snapshot(imageUrl: 'https://cdn.example/s.jpg');

    final state = listeningFrom(fetched, isFetchedSong: always)!;

    expect(state.coverUrl, 'https://cdn.example/s.jpg');
    expect(state.title, 'Dogs');
  });

  test('the song id only tells songs apart on this phone', () {
    expect(listeningFrom(snapshot(), isFetchedSong: never)!.id, 'song-1');
  });
}
