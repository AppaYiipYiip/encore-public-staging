import 'package:encore/features/people/listening.dart';
import 'package:encore/features/player/playback_facade.dart';
import 'package:flutter_test/flutter_test.dart';

/// What the player is doing, as a friend may be told about it (docs/35,
/// section 3): the song that is playing, never a library cover. There is no 30-second clip any more (D-64).
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

  test('a library song is shared with its title, artist and album, no cover',
      () {
    final state = listeningFrom(snapshot())!;

    expect(state.title, 'Dogs');
    expect(state.artist, 'Pink Floyd');
    expect(state.album, 'Animals');
    expect(state.playing, isTrue);
    expect(state.coverUrl, isNull,
        reason: 'a library cover needs the person\'s login');
  });

  test('paused is paused', () {
    expect(listeningFrom(snapshot(playing: false))!.playing, isFalse);
  });

  test('nothing playing is nothing to share', () {
    expect(listeningFrom(PlaybackSnapshot.idle), isNull);
    expect(listeningFrom(snapshot(withTrack: false)), isNull);
  });

  test(
      'a streamed song is what the person is listening to, with its public picture',
      () {
    final streamed = snapshot(imageUrl: 'https://cdn.example/s.jpg');

    final state = listeningFrom(streamed)!;

    expect(state.coverUrl, 'https://cdn.example/s.jpg');
    expect(state.title, 'Dogs');
  });

  test('the song id only tells songs apart on this phone', () {
    expect(listeningFrom(snapshot())!.id, 'song-1');
  });
}
