import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../data/catalogue/catalogue_models.dart';
import '../../data/db/app_database.dart' show TrackRow;
import '../providers.dart' show playbackFacadeProvider;
import 'instant_controller.dart';
import 'song_marks.dart';

/// What a tap on a catalogue song does (D-24, AUDIT F33; D-64, 7 Nov 2026). A tap means the FULL song, always: there is no 30-second preview
/// anywhere in the app (the owner: "just take the hit and run and load the full song").
///
/// When the instant-play backend is not ready yet (the first minutes of a fresh sign-in, or still loading) the tap **waits** for it. A server that
/// really cannot get the song says so in words, and so does a server that is not known yet (no address answered, too slow); a server KNOWN to
/// be a plain music server (no Encore on it) says that it only plays what it already has.
enum TapPlan { full, cannot, plainServer }

/// What to say when an Encore server cannot play a song that is not on it yet.
const String kCannotPlayLine =
    "Your server can't get this song right now. Songs it already has still play. Try again in a moment.";

/// What to say on a music server that has no Encore on it: it can only play what is already in its library.
const String kPlainServerLine =
    "This music server only plays songs it already has. Songs that are not in your library need an Encore server.";

/// The decision, with the world injected so it can be tested: waits (polling) while the backend [mayStillCome], up to [timeout].
Future<TapPlan> planTap({
  required bool Function() instant,
  required bool Function() mayStillCome,
  required bool Function() knownPlain,
  Future<void> Function(Duration) delay = _realDelay,
  Duration poll = const Duration(milliseconds: 100),
  Duration timeout = const Duration(seconds: 12),
}) async {
  var waited = Duration.zero;
  while (true) {
    if (instant()) return TapPlan.full;
    if (!mayStillCome() || waited >= timeout) break;
    await delay(poll);
    waited += poll;
  }
  return knownPlain() ? TapPlan.plainServer : TapPlan.cannot;
}

Future<void> _realDelay(Duration d) => Future<void>.delayed(d);

Future<TapPlan> _planFor(
  ProviderContainer container,
  ScaffoldMessengerState? messenger,
) async {
  bool instant() => container.read(instantAvailableProvider);
  if (instant()) return TapPlan.full;
  messenger
    ?..hideCurrentSnackBar()
    ..showSnackBar(const SnackBar(
        content: Text('Getting ready…'), duration: Duration(seconds: 12)));
  final plan = await planTap(
    instant: instant,
    mayStillCome: () {
      if (container.read(instantBackendProvider).isLoading) return true;
      final session = container.read(sessionProvider);
      if (session.isLoading) return true;
      return session.value?.detecting.value ?? false;
    },
    // Known to be plain: no server at all (nothing can play a full song), or a session that has found out the server is not an Encore
    // server. A session still loading, still finding out, or failed to build is NOT known.
    knownPlain: () {
      final async = container.read(sessionProvider);
      if (async.isLoading || async.hasError) return false;
      final session = async.value;
      return session == null ||
          (!session.encoreMode && !session.detecting.value);
    },
  );
  messenger?.hideCurrentSnackBar();
  return plan;
}

/// A tap on row [startIndex] of [items]: the full song, with the rest of the list behind it. With [shuffle] (a page's Shuffle button) the
/// list is played in random order from its first song instead.
///
/// **Songs the server already knows it cannot get (N-13) are never tried.** A tap on one says why at once (the server's own sentence), nothing spins and
/// the server is not asked; a whole-list Play or Shuffle leaves them out of the queue, with no failed try and no notice (a list of only such songs says
/// the first one's sentence).
Future<void> tapPlayRun(
  WidgetRef ref,
  List<CatalogueTrack> items, {
  required int startIndex,
  required String sourceName,
  required String sourceId,
  bool shuffle = false,
}) async {
  final container = ProviderScope.containerOf(ref.context);
  final messenger = ScaffoldMessenger.maybeOf(ref.context);
  if (items.isNotEmpty) {
    final marks = {
      for (final t in items) t.id: container.read(songMarkProvider(t.id)),
    };
    final tapped = !shuffle && startIndex >= 0 && startIndex < items.length
        ? items[startIndex]
        : null;
    if (tapped != null && marks[tapped.id] != null) {
      _say(messenger, marks[tapped.id]!.sentence);
      return;
    }
    final playable = [
      for (final t in items)
        if (marks[t.id] == null) t,
    ];
    if (playable.isEmpty) {
      _say(messenger, marks[items.first.id]!.sentence);
      return;
    }
    if (playable.length != items.length) {
      return tapPlayRun(ref, playable,
          startIndex: tapped == null
              ? 0
              : playable.indexWhere((t) => t.id == tapped.id),
          sourceName: sourceName,
          sourceId: sourceId,
          shuffle: shuffle);
    }
  }
  switch (await _planFor(container, messenger)) {
    case TapPlan.full:
      await container.read(instantControllerProvider.notifier).playRun(items,
          startIndex: startIndex,
          sourceName: sourceName,
          sourceId: sourceId,
          shuffle: shuffle);
    case TapPlan.cannot:
      _say(messenger, kCannotPlayLine);
    case TapPlan.plainServer:
      _say(messenger, kPlainServerLine);
  }
}

void _say(ScaffoldMessengerState? messenger, String line) => messenger
  ?..hideCurrentSnackBar()
  ..showSnackBar(SnackBar(content: Text(line)));

/// A tap (or a Play, a Shuffle) on rows of the phone's **own library**: the one place they are played from, so that **a song the server already knows it
/// cannot get is never tried** (N-13, B-128; drawn in S-12, S-15, S-17). The rule is the one [tapPlayRun] keeps for catalogue songs: a tap on a marked row
/// says why in the server's own sentence and asks the player for nothing; a whole-list play leaves marked songs out, with no failed try and no notice (a
/// list of only such songs says the first one's sentence). Everything else goes to the player as it always did.
///
/// The mark is read the way every row reads it ([libraryMarkProvider]): a song with a file, a downloaded song and a song while the server is away are
/// never marked, so this never takes a playable song out of a list.
Future<void> playLibraryTracks(
  WidgetRef ref,
  List<TrackRow> tracks, {
  int startIndex = 0,
  String? sourceName,
  String? sourceId,
  bool shuffle = false,
  bool skipUnavailable = false,
}) async {
  final facade = ref.read(playbackFacadeProvider);
  Future<void> play(List<TrackRow> list, int start) => facade.playTracks(list,
      startIndex: start,
      sourceName: sourceName,
      sourceId: sourceId,
      shuffle: shuffle,
      skipUnavailable: skipUnavailable);
  if (tracks.isEmpty) return play(tracks, startIndex);
  final container = ProviderScope.containerOf(ref.context);
  final messenger = ScaffoldMessenger.maybeOf(ref.context);
  final marks = {
    for (final t in tracks)
      t.id: t.mayBeUnavailable
          ? container.read(libraryMarkProvider(t.markKey))
          : null,
  };
  final tapped = !shuffle && startIndex >= 0 && startIndex < tracks.length
      ? tracks[startIndex]
      : null;
  if (tapped != null && marks[tapped.id] != null) {
    _say(messenger, marks[tapped.id]!.sentence);
    return;
  }
  final playable = [
    for (final t in tracks)
      if (marks[t.id] == null) t,
  ];
  if (playable.isEmpty) {
    _say(messenger, marks[tracks.first.id]!.sentence);
    return;
  }
  if (playable.length == tracks.length) return play(tracks, startIndex);
  return play(playable,
      tapped == null ? 0 : playable.indexWhere((t) => t.id == tapped.id));
}

/// A tap on one song of a search (no list behind it).
Future<void> tapPlayOne(WidgetRef ref, CatalogueTrack track) async {
  final container = ProviderScope.containerOf(ref.context);
  final messenger = ScaffoldMessenger.maybeOf(ref.context);
  final mark = container.read(songMarkProvider(track.id));
  if (mark != null) {
    // The server already knows it cannot get this song (N-13): nothing spins, the server is not asked, and the row's tap says why.
    _say(messenger, mark.sentence);
    return;
  }
  switch (await _planFor(container, messenger)) {
    case TapPlan.full:
      await container.read(instantControllerProvider.notifier).play(track);
    case TapPlan.cannot:
      _say(messenger, kCannotPlayLine);
    case TapPlan.plainServer:
      _say(messenger, kPlainServerLine);
  }
}
