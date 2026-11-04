import 'package:encore/data/db/app_database.dart';
import 'package:encore/design/theme.dart';
import 'package:encore/design/tokens.dart';
import 'package:encore/features/common/widgets.dart';
import 'package:encore/features/detail/album_gap.dart';
import 'package:encore/features/player/playback_facade.dart';
import 'package:encore/features/providers.dart';
import 'package:encore/features/requests/request_providers.dart';
import 'package:encore/playback/queue_model.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/factories.dart';
import '../support/fake_catalogue.dart';
import '../support/test_app.dart';

/// Songs the music server filed under its catch-all "[Unknown Album]" (a bucket, not a release; found by a friend's first Home screen,
/// 2026-11-03) show as songs without an album everywhere a SONG shows its album: the list row, its cover, the queue, the player and the
/// lock screen; and the bucket's own page never asks the catalogue what it is "missing".
void main() {
  setUpAll(loadAppFonts);

  const bucket = '[Unknown Album]';

  group('a song of the bucket', () {
    test('goes into the queue (and so the lock screen) with no album', () {
      final item = QueueItem.fromTrack(trackRow('t1', album: bucket), uid: 1);
      expect(item.album, isNull);
    });

    test('shows in the player with no album', () {
      expect(
          NowPlayingTrack.fromRow(trackRow('t1', album: bucket)).album, isNull);
    });

    test('a song with a real album keeps it', () {
      expect(QueueItem.fromTrack(trackRow('t1', album: 'Kodama'), uid: 1).album,
          'Kodama');
      expect(NowPlayingTrack.fromRow(trackRow('t1', album: 'Kodama')).album,
          'Kodama');
    });
  });

  group('the song row', () {
    Future<void> show(WidgetTester tester, TrackRow track) async {
      await tester.pumpWidget(ProviderScope(
        child: MaterialApp(
          theme: buildEncoreTheme(EncoreColors.dark(),
              brightness: Brightness.dark),
          home: Scaffold(body: TrackTile(track: track, showAlbum: true)),
        ),
      ));
    }

    testWidgets('names the artist only, not the bucket', (tester) async {
      await show(tester, trackRow('t1', artist: 'Alcest', album: bucket));
      expect(find.text('Alcest'), findsOneWidget);
      expect(find.textContaining('Unknown Album'), findsNothing);
    });

    testWidgets('a real album is still named after the artist', (tester) async {
      await show(tester, trackRow('t1', artist: 'Alcest', album: 'Kodama'));
      expect(find.text('Alcest • Kodama'), findsOneWidget);
    });
  });

  group('the bucket\'s own album page', () {
    AlbumRow album(String name) => AlbumRow(
          serverId: 1,
          id: 'al1',
          name: name,
          artist: 'Alcest',
          songCount: 2,
          durationSec: 400,
          isCompilation: false,
          fingerprint: '',
          syncRun: 0,
        );

    Future<(AlbumGap?, FakeCatalogue)> gapOf(String name) async {
      final catalogue = FakeCatalogue();
      final container = ProviderContainer(overrides: [
        catalogueClientProvider.overrideWithValue(catalogue),
        albumProvider('al1').overrideWith((ref) => Stream.value(album(name))),
        albumTracksProvider('al1').overrideWith((ref) =>
            Stream.value([trackRow('t1', album: name), trackRow('t2')])),
      ]);
      addTearDown(container.dispose);
      // Auto-disposing providers need a listener to stay alive while the lookup is awaited.
      container.listen(albumGapProvider('al1'), (_, __) {});
      final gap = await container.read(albumGapProvider('al1').future);
      return (gap, catalogue);
    }

    test('never asks the catalogue what it is missing', () async {
      final (gap, catalogue) = await gapOf(bucket);
      expect(gap, isNull);
      expect(catalogue.queries, isEmpty);
      expect(catalogue.lookups, isEmpty);
    });

    test('a real album still does ask', () async {
      final (_, catalogue) = await gapOf('Kodama');
      expect(
          catalogue.queries.length + catalogue.lookups.length, greaterThan(0));
    });
  });
}
