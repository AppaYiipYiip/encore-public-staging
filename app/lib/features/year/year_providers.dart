import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../core/result.dart';
import '../../data/db/app_database.dart';
import '../../domain/album_names.dart';
import '../../domain/year_in_music.dart';

/// The facts of a library song that the year is counted with.
SongFacts songFactsOf(TrackRow t) => SongFacts(
      id: t.id,
      title: t.title,
      artist: t.artist,
      album: realAlbumName(t.album),
      genre: t.genre,
      year: t.year,
      durationSec: t.durationSec,
      coverArt: t.coverArt,
      albumId: t.albumId,
      artistId: t.artistId,
    );

/// How long the history is kept after the screen closes (the screen asks
/// several times: month, year, all time).
final playHistoryKeepProvider =
    Provider<Duration>((ref) => const Duration(minutes: 2));

/// Every play of this person, read from their server when the screen opens
/// (it can be long) and kept for a couple of minutes, so that flipping between
/// month, year and all time is free but a song listened to in the meantime
/// shows the next time the screen is opened (found on the phone: it was read
/// once per session and never again). A server that keeps no history of its own
/// (not Navidrome, or an old one) falls back to what this phone saw itself.
final playHistoryProvider =
    FutureProvider.autoDispose<List<Listen>>((ref) async {
  final keep = ref.read(playHistoryKeepProvider);
  final link = ref.keepAlive();
  Timer? release;
  ref.onCancel(() => release = Timer(keep, link.close));
  ref.onResume(() => release?.cancel());
  ref.onDispose(() => release?.cancel());

  final session = await ref.watch(sessionProvider.future);
  if (session == null) return const [];
  final result = await session.playHistory.fetchAll();
  final listens = result.valueOrNull;
  if (listens != null) return listens;
  final failure = result.failureOrNull!;
  if (failure is ServerFailure && failure.statusCode != null) {
    final own = await session.library.ownPlays();
    return [
      for (final p in own)
        Listen(p.trackId, DateTime.fromMillisecondsSinceEpoch(p.playedAtMs)),
    ];
  }
  throw failure;
});

/// What the year (or month, or all time) says, counted on this phone.
final yearInMusicProvider =
    FutureProvider.autoDispose.family<YearInMusic, Period>((ref, period) async {
  final listens = await ref.watch(playHistoryProvider.future);
  final repo = ref.watch(libraryRepositoryProvider);
  final rows = repo == null
      ? const <String, TrackRow>{}
      : await repo.tracksByIds({for (final l in listens) l.trackId});
  return YearInMusic.compute(
    listens: listens,
    songs: {for (final e in rows.entries) e.key: songFactsOf(e.value)},
    period: period,
  );
});

enum YearPeriodKind { month, year, allTime }

/// Which of the three periods the screen shows.
class YearPeriodKindNotifier extends Notifier<YearPeriodKind> {
  @override
  YearPeriodKind build() => YearPeriodKind.year;

  void choose(YearPeriodKind kind) => state = kind;
}

final yearPeriodKindProvider =
    NotifierProvider<YearPeriodKindNotifier, YearPeriodKind>(
        YearPeriodKindNotifier.new);

/// The period for [kind], counted from now.
Period periodFor(YearPeriodKind kind, DateTime now) => switch (kind) {
      YearPeriodKind.month => Period.monthOf(now),
      YearPeriodKind.year => Period.yearOf(now),
      YearPeriodKind.allTime =>
        Period.allTime(DateTime(now.year, now.month, now.day)),
    };
