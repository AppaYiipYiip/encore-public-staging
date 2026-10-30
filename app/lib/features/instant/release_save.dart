import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../core/result.dart';
import '../../data/catalogue/catalogue_models.dart';
import '../../data/encore/encore_models.dart';
import '../../data/repos/downloads_repository.dart';
import '../downloads/download_providers.dart';
import 'instant_controller.dart';

/// What happened when a release was saved or downloaded (D-21, docs/17 "Saving a release").
class ReleaseOutcome {
  const ReleaseOutcome({
    this.saved = const [],
    this.unresolved = const [],
    this.keepFailed = const [],
    this.problem,
  });

  /// The songs (their ids) the server confirmed.
  final List<String> saved;

  /// Titles of songs that could not be resolved to a song of the server's.
  final List<String> unresolved;

  /// Songs the server says it could not keep, by title, with the server's reason when it gave one.
  final List<({String title, String? reason})> keepFailed;

  /// A sentence for a person when nothing was saved at all.
  final String? problem;

  /// What to tell the person, or `null` when everything went well. Never silence.
  String? get message {
    if (problem != null) return problem;
    final names = [
      ...unresolved,
      for (final f in keepFailed)
        f.reason == null || f.reason!.isEmpty
            ? f.title
            : '${f.title} (${f.reason})',
    ];
    if (names.isEmpty) return null;
    final count = unresolved.length + keepFailed.length;
    return "Couldn't get $count ${count == 1 ? 'song' : 'songs'}: ${names.join(', ')}.";
  }
}

/// Saves or downloads a catalogue release on an Encore server: the songs are resolved, ONE call asks the server to save the release and
/// keep them (whether or not the phone stays), and only what the server confirmed is pinned on the phone. The pieces are injected.
class ReleaseSaver {
  ReleaseSaver({required this.resolve, required this.save, required this.pin});

  /// Gives a song its id on the server, or `null` when it could not (the title is only for logs and tests).
  final Future<String?> Function(String id, String title) resolve;

  /// `PUT saved-albums/{releaseId}` with the songs.
  final Future<Result<EncoreReleaseSave>> Function(
      String releaseId, List<String> refIds) save;

  /// Pins one song on the phone: it downloads when the server has it.
  final Future<void> Function(String refId) pin;

  Future<ReleaseOutcome> run({
    required String releaseId,
    required List<({String id, String title})> songs,
    required bool download,
  }) async {
    final resolved = <({String ref, String title})>[];
    final unresolved = <String>[];
    for (final song in songs) {
      final ref = await resolve(song.id, song.title);
      if (ref == null) {
        unresolved.add(song.title);
      } else {
        resolved.add((ref: ref, title: song.title));
      }
    }
    if (resolved.isEmpty) {
      return const ReleaseOutcome(
          problem: "Couldn't get any of these songs. Nothing was saved.");
    }

    final result = await save(releaseId, [for (final r in resolved) r.ref]);
    final answer = result.valueOrNull;
    if (answer == null) {
      return ReleaseOutcome(problem: _problemOf(result.failureOrNull));
    }

    final failed = <({String title, String? reason})>[];
    for (final r in resolved) {
      final keep = answer.keep[r.ref];
      if (keep != null && keep.isFailed) {
        failed.add((title: r.title, reason: keep.reason));
      }
    }
    if (download) {
      for (final r in resolved) {
        await pin(r.ref);
      }
    }
    return ReleaseOutcome(
      saved: [for (final r in resolved) r.ref],
      unresolved: unresolved,
      keepFailed: failed,
    );
  }

  static String _problemOf(AppFailure? failure) => switch (failure) {
        NetworkFailure() => "Can't reach your server. Nothing was saved.",
        NotFoundFailure() =>
          'Your server did not know one of these songs. Nothing was saved. Try again.',
        _ => 'Your server could not save this. Nothing was saved. Try again.',
      };
}

// ------------------------------------------------------------------------------------------ what the screen shows

/// Where saving a release stands on this phone. `saved` only once the SERVER confirmed it (D-21).
enum ReleasePhase { saving, saved, failed }

@immutable
class ReleaseState {
  const ReleaseState(
    this.phase, {
    this.download = false,
    this.refIds = const [],
    this.message,
  });

  final ReleasePhase phase;

  /// The person asked for it on the phone too, not only on the server.
  final bool download;

  /// The songs the server confirmed.
  final List<String> refIds;

  /// What to tell the person, if anything.
  final String? message;
}

/// Saves and downloads catalogue releases on an Encore server, by release id (`cat:<catalogue album id>`).
class ReleaseSaves extends Notifier<Map<String, ReleaseState>> {
  @override
  Map<String, ReleaseState> build() => const {};

  /// Saves [tracks] as one release; with [download] also pins them on this phone. Answers what to tell the person (`null` when all went
  /// well). Asking again while it is on its way does nothing.
  Future<String?> save(
    String releaseId,
    List<CatalogueTrack> tracks, {
    required bool download,
  }) async {
    if (state[releaseId]?.phase == ReleasePhase.saving) return null;
    state = {
      ...state,
      releaseId: ReleaseState(ReleasePhase.saving, download: download)
    };
    final session = await ref.read(sessionProvider.future);
    if (session == null || !session.encoreMode) {
      state = {...state}..remove(releaseId);
      return 'This needs an Encore server.';
    }
    final byId = {for (final t in tracks) t.id: t};
    final controller = ref.read(instantControllerProvider.notifier);
    final actions = ref.read(downloadActionsProvider);
    final saver = ReleaseSaver(
      resolve: (id, title) async {
        final status = await controller.fetch(byId[id]!, bulk: true);
        return status != null && status.isReady ? status.track?.id : null;
      },
      save: session.encore.saveRelease,
      pin: (refId) => actions.pin(PinTargetType.track, refId),
    );
    final outcome = await saver.run(
      releaseId: releaseId,
      songs: [for (final t in tracks) (id: t.id, title: t.title)],
      download: download,
    );
    state = {
      ...state,
      releaseId: ReleaseState(
        outcome.saved.isEmpty ? ReleasePhase.failed : ReleasePhase.saved,
        download: download,
        refIds: outcome.saved,
        message: outcome.message,
      ),
    };
    return outcome.message;
  }

  /// Takes the downloaded copies of a release off the phone (the songs stay on the server and in the library).
  Future<void> removeDownload(String releaseId) async {
    final actions = ref.read(downloadActionsProvider);
    for (final refId in state[releaseId]?.refIds ?? const <String>[]) {
      await actions.unpin(PinTargetType.track, refId);
    }
    final now = state[releaseId];
    if (now != null) {
      state = {
        ...state,
        releaseId: ReleaseState(now.phase, refIds: now.refIds),
      };
    }
  }
}

final releaseSavesProvider =
    NotifierProvider<ReleaseSaves, Map<String, ReleaseState>>(ReleaseSaves.new);

/// The download state of a saved release: the pins of its songs added up. [joined] is the song ids, comma separated.
final releasePinStateProvider =
    Provider.autoDispose.family<PinState, String>((ref, joined) {
  var pinned = false;
  var total = 0, done = 0, active = 0, failed = 0, bytes = 0;
  for (final id in joined.isEmpty ? const <String>[] : joined.split(',')) {
    final s = ref.watch(pinStateProvider((PinTargetType.track, id))).value ??
        PinState.none;
    pinned = pinned || s.pinned;
    total += s.total;
    done += s.done;
    active += s.active;
    failed += s.failed;
    bytes += s.bytes;
  }
  return PinState(
      pinned: pinned,
      total: total,
      done: done,
      active: active,
      failed: failed,
      bytes: bytes);
});
