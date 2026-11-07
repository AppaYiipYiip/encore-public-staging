import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../data/catalogue/catalogue_models.dart';
import 'instant_controller.dart';

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
    case TapPlan.cannot:
      _say(messenger, kCannotPlayLine);
    case TapPlan.plainServer:
      _say(messenger, kPlainServerLine);
  }
}

void _say(ScaffoldMessengerState? messenger, String line) => messenger
  ?..hideCurrentSnackBar()
  ..showSnackBar(SnackBar(content: Text(line)));

/// A tap on one song of a search (no list behind it).
Future<void> tapPlayOne(WidgetRef ref, CatalogueTrack track) async {
  final container = ProviderScope.containerOf(ref.context);
  final messenger = ScaffoldMessenger.maybeOf(ref.context);
  switch (await _planFor(container, messenger)) {
    case TapPlan.full:
      await container.read(instantControllerProvider.notifier).play(track);
    case TapPlan.cannot:
      _say(messenger, kCannotPlayLine);
    case TapPlan.plainServer:
      _say(messenger, kPlainServerLine);
  }
}
