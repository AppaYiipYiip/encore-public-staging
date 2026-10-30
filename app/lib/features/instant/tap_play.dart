import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../data/catalogue/catalogue_models.dart';
import '../catalogue/catalogue_widgets.dart' show playPreviewRun;
import '../player/playback_facade.dart';
import '../providers.dart';
import 'instant_controller.dart';

/// What a tap on a catalogue song does (D-24, AUDIT F33). The owner's phone played 30 seconds of every song: the instant-play backend was
/// not ready (the first minutes of a fresh sign-in, or still loading), and a tap silently started a 30-second preview.
///
/// A tap means the FULL song. When the backend is not ready yet the tap **waits** for it. A preview is never the answer on an Encore server;
/// it comes only from a long-press ([playExplicitPreview]), or, on a plain music server where it is all there is, from a tap on rows that say
/// "preview". An Encore server that really cannot get the song says so in words, and so does a server that is not known yet (no address
/// answered, too slow): a preview is only for a server KNOWN to be a plain music server.
enum TapPlan { full, preview, cannot }

/// What to say when an Encore server cannot play a song that is not on it yet.
const String kCannotPlayLine =
    "Your server can't get this song right now. Songs it already has still play. Try again in a moment.";

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
  return knownPlain() ? TapPlan.preview : TapPlan.cannot;
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

/// A tap on row [startIndex] of [items]: the full song, with the rest of the list behind it.
Future<void> tapPlayRun(
  WidgetRef ref,
  List<CatalogueTrack> items, {
  required int startIndex,
  required String sourceName,
  required String sourceId,
}) async {
  final container = ProviderScope.containerOf(ref.context);
  final messenger = ScaffoldMessenger.maybeOf(ref.context);
  switch (await _planFor(container, messenger)) {
    case TapPlan.full:
      await container.read(instantControllerProvider.notifier).playRun(items,
          startIndex: startIndex, sourceName: sourceName, sourceId: sourceId);
    case TapPlan.preview:
      await playPreviewRun(container.read(playbackFacadeProvider), items,
          index: startIndex, sourceName: sourceName, sourceId: sourceId);
    case TapPlan.cannot:
      messenger
        ?..hideCurrentSnackBar()
        ..showSnackBar(const SnackBar(content: Text(kCannotPlayLine)));
  }
}

/// A tap on one song of a search (no list behind it).
Future<void> tapPlayOne(WidgetRef ref, CatalogueTrack track) async {
  final container = ProviderScope.containerOf(ref.context);
  final messenger = ScaffoldMessenger.maybeOf(ref.context);
  switch (await _planFor(container, messenger)) {
    case TapPlan.full:
      await container.read(instantControllerProvider.notifier).play(track);
    case TapPlan.preview:
      final preview = track.previewUrl;
      if (preview == null) return;
      await container.read(playbackFacadeProvider).playPreview(
            id: track.id,
            title: track.title,
            uri: Uri.parse(preview),
            artist: track.artistName,
            catalogueArtistId: track.artistId,
            album: track.albumTitle,
            imageUrl: track.coverUrl,
            duration: const Duration(seconds: 30),
          );
    case TapPlan.cannot:
      messenger
        ?..hideCurrentSnackBar()
        ..showSnackBar(const SnackBar(content: Text(kCannotPlayLine)));
  }
}

/// A long-press: the 30-second sample of row [index], chosen on purpose. The only other way to a preview run.
Future<void> playExplicitPreview(
  PlaybackFacade facade,
  List<CatalogueTrack> items, {
  required int index,
  required String sourceName,
  required String sourceId,
}) =>
    playPreviewRun(facade, items,
        index: index, sourceName: sourceName, sourceId: sourceId);
