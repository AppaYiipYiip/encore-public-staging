import 'dart:async';

import 'package:encore/app/audio_output.dart';
import 'package:encore/app/share_out.dart';
import 'package:encore/domain/lyrics.dart';
import 'package:encore/features/player/lyrics_screen.dart'
    show currentLyricsProvider;
import 'package:encore/features/player/playback_facade.dart';
import 'package:encore/features/player/scrubber.dart';
import 'package:encore/features/player/share_text.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import '../support/test_app.dart';

/// The owner's three asks for the full player (7 Nov 2026, D-63, D-66): the output row and its Devices sheet (P1-25), Share (P1-24), and a Lyrics
/// card that keeps its place and its size in every state so the screen never jumps (P1-23).
class _Share implements ShareOut {
  final List<String> sent = [];

  @override
  Future<bool> text(String text) async {
    sent.add(text);
    return true;
  }
}

class _Output implements AudioOutputService {
  _Output(this.first);

  AudioOutputInfo first;
  final StreamController<AudioOutputInfo> changes =
      StreamController<AudioOutputInfo>.broadcast();
  int switcherOpened = 0;

  Future<void> dispose() => changes.close();

  @override
  Stream<AudioOutputInfo> watch() async* {
    yield first;
    yield* changes.stream;
  }

  @override
  Future<bool> showSwitcher() async {
    switcherOpened++;
    return true;
  }
}

const _buds =
    AudioOutputInfo(name: 'Galaxy Buds2', kind: AudioOutputKind.bluetooth);

const _lyrics = TrackLyrics(
  lines: [
    LyricLine(startMs: 1000, text: 'Come into this night'),
    LyricLine(startMs: 5000, text: "Here we'll be gone"),
    LyricLine(startMs: 9000, text: 'So far away'),
  ],
  synced: true,
  source: 'lrclib',
);

PlaybackSnapshot _playing({String? videoId}) => PlaybackSnapshot(
      track: NowPlayingTrack(
        id: 'al3-t1',
        title: 'Benighted',
        artist: 'Opeth',
        album: 'Still Life',
        albumId: 'al3',
        artistId: 'ar2',
        duration: const Duration(minutes: 5),
        videoId: videoId,
      ),
      isPlaying: true,
      duration: const Duration(minutes: 5),
      queueIndex: 0,
      queueLength: 5,
      hasNext: true,
      sourceName: 'Still Life',
    );

void main() {
  setUpAll(loadAppFonts);

  Future<void> openPlayer(WidgetTester tester) async {
    final element = tester.element(find.byType(Scaffold).first);
    GoRouter.of(element).go('/player');
    await settle(tester);
  }

  group('what is shared', () {
    NowPlayingTrack track({String? artist = 'Opeth', String? videoId}) =>
        NowPlayingTrack(
            id: 'x', title: 'Benighted', artist: artist, videoId: videoId);

    test('a song of the library is shared by name only', () {
      expect(shareTextFor(track()), 'Benighted by Opeth');
    });

    test(
        'a streamed song whose video is known carries the public YouTube address',
        () {
      expect(shareTextFor(track(videoId: 'abc123XYZ_-')),
          'Benighted by Opeth\nhttps://music.youtube.com/watch?v=abc123XYZ_-');
    });

    test('a song with no artist is shared by its title', () {
      expect(shareTextFor(track(artist: null)), 'Benighted');
      expect(shareTextFor(track(artist: '  ')), 'Benighted');
    });

    test('never an address of the person\'s own server', () {
      final text = shareTextFor(track(videoId: 'abc'));
      expect(text, isNot(contains('192.168')));
      expect(text, isNot(contains('ts.net')));
      expect(text, isNot(contains('/encore/stream')));
    });

    test('the lyrics card shares the lines it shows, then the song', () {
      expect(
          shareLyricsTextFor(
              track(), ['Come into this night', '', "Here we'll be gone"]),
          "Come into this night\nHere we'll be gone\n\nBenighted by Opeth");
      expect(shareLyricsTextFor(track(), const []), 'Benighted by Opeth');
    });
  });

  group('the output', () {
    test('what Android sends is read, anything else is "This phone"', () {
      expect(
          AudioOutputInfo.fromMap(
              {'kind': 'bluetooth', 'name': 'Galaxy Buds2'}),
          _buds);
      expect(
          AudioOutputInfo.fromMap({'kind': 'wired', 'name': 'Headphones'}).kind,
          AudioOutputKind.wired);
      expect(AudioOutputInfo.fromMap({'kind': 'bluetooth', 'name': ''}).name,
          'Bluetooth');
      expect(AudioOutputInfo.fromMap({'kind': 'wired'}).name, 'Headphones');
      expect(AudioOutputInfo.fromMap({'kind': 'speaker', 'name': 'SM-A356B'}),
          AudioOutputInfo.thisPhone);
      expect(AudioOutputInfo.fromMap(null), AudioOutputInfo.thisPhone);
      expect(AudioOutputInfo.fromMap('nonsense'), AudioOutputInfo.thisPhone);
      expect(AudioOutputInfo.fromMap({'kind': 'something new'}),
          AudioOutputInfo.thisPhone);
    });
  });

  testWidgets(
      'the bottom row: where the sound goes on the left, Share and the queue on the right',
      (tester) async {
    final app = await pumpApp(tester, playing: _playing());
    await openPlayer(tester);

    expect(find.text('This phone'), findsOneWidget);
    expect(find.byTooltip('Share'), findsOneWidget);
    expect(find.byTooltip('Queue'), findsOneWidget);
    final chip = tester.getCenter(find.text('This phone'));
    final share = tester.getCenter(find.byTooltip('Share'));
    final queue = tester.getCenter(find.byTooltip('Queue'));
    expect(chip.dx, lessThan(share.dx));
    expect(share.dx, lessThan(queue.dx));
    expect((chip.dy - queue.dy).abs(), lessThan(8), reason: 'one row');
    await closeApp(tester, app.db);
  });

  testWidgets(
      'Share hands the song to the phone\'s share sheet, with its public link when the app knows it',
      (tester) async {
    final out = _Share();
    final app = await pumpApp(tester,
        playing: _playing(videoId: 'vid123'),
        overrides: [shareOutProvider.overrideWithValue(out)]);
    await openPlayer(tester);

    await tester.tap(find.byTooltip('Share'));
    await settle(tester);

    expect(out.sent,
        ['Benighted by Opeth\nhttps://music.youtube.com/watch?v=vid123']);
    await closeApp(tester, app.db);
  });

  testWidgets('a phone that cannot open sharing says so', (tester) async {
    final app = await pumpApp(tester,
        playing: _playing(),
        overrides: [shareOutProvider.overrideWithValue(_NoShare())]);
    await openPlayer(tester);

    await tester.tap(find.byTooltip('Share'));
    await settle(tester);

    expect(find.text('This phone could not open sharing.'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets('the row names a Bluetooth device and follows the changes',
      (tester) async {
    final output = _Output(_buds);
    addTearDown(output.dispose);
    final app = await pumpApp(tester,
        playing: _playing(),
        overrides: [audioOutputServiceProvider.overrideWithValue(output)]);
    await openPlayer(tester);

    expect(find.text('Galaxy Buds2'), findsOneWidget);

    output.changes.add(AudioOutputInfo.thisPhone);
    await tester.pump();
    await tester.pump();

    expect(find.text('Galaxy Buds2'), findsNothing);
    expect(find.text('This phone'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'the Devices sheet: this phone ticked, Android\'s own list one tap away, the other devices said to be not built yet',
      (tester) async {
    final output = _Output(_buds);
    addTearDown(output.dispose);
    final app = await pumpApp(tester,
        playing: _playing(),
        overrides: [audioOutputServiceProvider.overrideWithValue(output)]);
    await openPlayer(tester);

    await tester.tap(find.text('Galaxy Buds2'));
    await settle(tester);

    expect(find.text('Play on'), findsOneWidget);
    expect(find.text('THIS PHONE'), findsOneWidget);
    expect(find.byKey(const Key('devices-current')), findsOneWidget);
    expect(find.text('The sound is playing here'), findsOneWidget);
    expect(find.text('YOUR OTHER DEVICES'), findsOneWidget);
    expect(find.textContaining('not built yet'), findsOneWidget);

    await tester.tap(find.byKey(const Key('devices-switcher')));
    await settle(tester);

    expect(output.switcherOpened, 1);
    await closeApp(tester, app.db);
  });

  group('the Lyrics card is always there, always the same size', () {
    Future<({double card, double title, double scrubber, double queue})>
        measure(WidgetTester tester,
            {TrackLyrics? lyrics,
            Future<TrackLyrics?>? pending,
            Size size = const Size(390, 844)}) async {
      final app =
          await pumpApp(tester, size: size, playing: _playing(), overrides: [
        currentLyricsProvider('al3-t1').overrideWith(
            (ref) => pending ?? Future<TrackLyrics?>.value(lyrics)),
      ]);
      await openPlayer(tester);
      final result = (
        card: tester.getTopLeft(find.text('Lyrics')).dy,
        title: tester.getTopLeft(find.text('Benighted')).dy,
        scrubber: tester.getTopLeft(find.byType(Scrubber)).dy,
        queue: tester.getTopLeft(find.byTooltip('Queue')).dy,
      );
      await closeApp(tester, app.db);
      return result;
    }

    testWidgets('no lyrics: the card says so', (tester) async {
      final app = await pumpApp(tester, playing: _playing(), overrides: [
        currentLyricsProvider('al3-t1').overrideWith((ref) async => null),
      ]);
      await openPlayer(tester);

      expect(find.text('Lyrics'), findsOneWidget);
      expect(find.text('No lyrics for this song'), findsOneWidget);
      await closeApp(tester, app.db);
    });

    testWidgets('while they load: "Looking for lyrics..."', (tester) async {
      final never = Completer<TrackLyrics?>();
      final app = await pumpApp(tester, playing: _playing(), overrides: [
        currentLyricsProvider('al3-t1').overrideWith((ref) => never.future),
      ]);
      await openPlayer(tester);

      expect(find.text('Looking for lyrics...'), findsOneWidget);
      await closeApp(tester, app.db);
    });

    testWidgets(
        'with lyrics: the lines, a share button, and a tap that opens the full screen',
        (tester) async {
      final out = _Share();
      final app = await pumpApp(tester, playing: _playing(), overrides: [
        shareOutProvider.overrideWithValue(out),
        currentLyricsProvider('al3-t1').overrideWith((ref) async => _lyrics),
      ]);
      await openPlayer(tester);

      expect(find.text('Come into this night'), findsOneWidget);
      expect(find.text('No lyrics for this song'), findsNothing);
      await tester.tap(find.bySemanticsLabel('Share these lyrics'));
      await settle(tester);
      expect(out.sent.single, contains('Come into this night'));
      expect(out.sent.single, endsWith('Benighted by Opeth'));
      await closeApp(tester, app.db);
    });

    testWidgets(
        'plain lyrics say they are not synced, so a missing tap is explained',
        (tester) async {
      final app = await pumpApp(tester, playing: _playing(), overrides: [
        currentLyricsProvider('al3-t1')
            .overrideWith((ref) async => const TrackLyrics(
                  lines: [
                    LyricLine(startMs: null, text: 'Come into this night')
                  ],
                  synced: false,
                )),
      ]);
      await openPlayer(tester);

      expect(find.text('Lyrics (not synced)'), findsOneWidget);
      await closeApp(tester, app.db);
    });

    for (final size in const [Size(390, 844), Size(411, 914), Size(360, 640)]) {
      testWidgets(
          'the cover, title, scrubber, controls and card sit at the same place with and without lyrics (${size.width.toInt()}x${size.height.toInt()})',
          (tester) async {
        final without = await measure(tester, lyrics: null, size: size);
        final withLyrics = await measure(tester, lyrics: _lyrics, size: size);
        final loading = await measure(tester,
            pending: Completer<TrackLyrics?>().future, size: size);

        for (final other in [withLyrics, loading]) {
          expect(other.title, closeTo(without.title, 0.5),
              reason: 'the title does not move');
          expect(other.scrubber, closeTo(without.scrubber, 0.5),
              reason: 'the scrubber does not move');
          expect(other.queue, closeTo(without.queue, 0.5),
              reason: 'the bottom row does not move');
          expect(other.card, closeTo(without.card, 0.5),
              reason: 'the card does not move');
        }
      });
    }
  });
}

class _NoShare implements ShareOut {
  @override
  Future<bool> text(String text) async => false;
}
