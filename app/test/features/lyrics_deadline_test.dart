import 'dart:async';

import 'package:drift/native.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/repos/lyrics_repository.dart';
import 'package:encore/domain/lyrics.dart';
import 'package:encore/features/player/lyrics_screen.dart';
import 'package:encore/features/providers.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/test_app.dart';

/// A lookup that never answers (the radio is on and there is no data, a server that hangs) left the lyrics page turning for ever
/// (owner, 2026-10-31: an instrumental song "keeps spinning"). It gives up and says there are no lyrics.
class _Hangs extends LyricsRepository {
  _Hangs(AppDatabase db) : super(db: db, serverId: 1);

  @override
  Future<TrackLyrics?> load({
    required String trackId,
    required String title,
    String? artist,
    String? album,
    int? durationSec,
    bool allowNetwork = true,
  }) =>
      Completer<TrackLyrics?>().future;
}

void main() {
  test('a lookup that never answers ends as "no lyrics", not as a spinner',
      () async {
    final db = AppDatabase(NativeDatabase.memory());
    addTearDown(db.close);
    final facade = FakePlaybackFacade(samplePlaying());
    final c = ProviderContainer(overrides: [
      playbackFacadeProvider.overrideWithValue(facade),
      lyricsRepositoryProvider.overrideWithValue(_Hangs(db)),
      lyricsDeadlineProvider
          .overrideWithValue(const Duration(milliseconds: 60)),
    ]);
    addTearDown(c.dispose);
    c.listen(playbackSnapshotProvider, (_, __) {});
    await pumpEventQueue();

    final lyrics = await c.read(currentLyricsProvider('al3-t1').future).timeout(
        const Duration(seconds: 2),
        onTimeout: () => fail('the lookup never ended'));

    expect(lyrics, isNull);
  });
}
