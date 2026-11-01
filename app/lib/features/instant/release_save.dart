import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../core/result.dart';
import '../../data/catalogue/catalogue_models.dart';
import '../../data/encore/encore_models.dart';
import '../../data/repos/downloads_repository.dart';
import '../../data/repos/release_store.dart';
import '../downloads/download_providers.dart';
import '../settings/settings_controller.dart';
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
  ReleaseSaver({
    required this.resolve,
    required this.save,
    required this.pin,
    this.onSaved,
  });

  /// Gives a song its id on the server, or `null` when it could not (the title is only for logs and tests).
  final Future<String?> Function(String id, String title) resolve;

  /// `PUT saved-albums/{releaseId}` with the songs.
  final Future<Result<EncoreReleaseSave>> Function(
      String releaseId, List<String> refIds) save;

  /// Pins one song on the phone: it downloads when the server has it.
  final Future<void> Function(String refId) pin;

  /// Called once the server confirmed the save, **before the first song is pinned**: the phone writes down what it saved, so that an app that
  /// is killed in the middle of the pins can finish them when it starts again (D-35).
  final Future<void> Function(List<String> refIds)? onSaved;

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
    await onSaved?.call([for (final r in resolved) r.ref]);
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

/// What to tell the person after a release's download was taken off the phone, when [kept] of its songs stayed because another downloaded
/// release has them too; `null` when nothing stayed (the usual "Removed ..." line is enough).
String? releaseRemovedNote(String name, int kept) {
  if (kept <= 0) return null;
  final stays = kept == 1 ? 'One song stays' : '$kept songs stay';
  final them = kept == 1 ? 'it' : 'them';
  return 'Removed $name from this phone. $stays: another downloaded release has $them.';
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
    String? title,
    String? artist,
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
    final store = await _store();
    final saver = ReleaseSaver(
      resolve: (id, title) async {
        final status = await controller.fetch(byId[id]!, bulk: true);
        return status != null && status.isReady ? status.track?.id : null;
      },
      save: session.encore.saveRelease,
      pin: (refId) => actions.pin(PinTargetType.track, refId),
      // Written down before the first pin: what the phone keeps after a restart is the phone's own record of this release (D-35).
      onSaved: store == null
          ? null
          : (refIds) async {
              final before = (await store.phone())[releaseId];
              await store.put(
                releaseId,
                PhoneRelease(
                  refIds: refIds,
                  title: title ?? before?.title,
                  artist: artist ?? before?.artist,
                  download: download || (before?.download ?? false),
                ),
              );
            },
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

  /// Takes the downloaded copies of a release off the phone (the songs stay on the server and in the library). The songs come from what the
  /// phone wrote down, so this also works after a restart, when the page's own memory is empty (D-35).
  ///
  /// A song that **another downloaded release** has too stays: there is one pin per song, whoever asked for it, so unpinning it here would
  /// delete a file the person expects in the other release. Answers how many songs stayed, for the sentence [releaseRemovedNote].
  Future<int> removeDownload(String releaseId) async {
    final actions = ref.read(downloadActionsProvider);
    final store = await _store();
    final records = await store?.phone() ?? const <String, PhoneRelease>{};
    final refIds = {
      ...?state[releaseId]?.refIds,
      ...?records[releaseId]?.refIds
    };
    final wantedElsewhere = <String>{
      for (final e in records.entries)
        if (e.key != releaseId && e.value.download) ...e.value.refIds,
    };
    var kept = 0;
    for (final refId in refIds) {
      if (wantedElsewhere.contains(refId)) {
        kept++;
        continue;
      }
      await actions.unpin(PinTargetType.track, refId);
    }
    await store?.clearDownload(releaseId);
    final now = state[releaseId];
    if (now != null) {
      state = {
        ...state,
        releaseId: ReleaseState(now.phase, refIds: now.refIds),
      };
    }
    return kept;
  }

  /// Takes ONE downloaded song off the phone (the song menu's "Remove download"). The phone's record of the release is written first: a kill
  /// between the two steps must not leave a song that [resume] pins again at the next start, undoing what the person chose (D-35).
  Future<void> removeSongDownload(String refId) async {
    final store = await _store();
    await store?.dropSong(refId);
    await ref.read(downloadActionsProvider).unpin(PinTargetType.track, refId);
    // What the open release page remembers: the song is no longer one of its downloaded songs.
    final changed = {
      for (final e in state.entries)
        if (e.value.refIds.contains(refId))
          e.key: ReleaseState(e.value.phase,
              download: e.value.download,
              refIds: [
                for (final r in e.value.refIds)
                  if (r != refId) r
              ],
              message: e.value.message),
    };
    if (changed.isNotEmpty) state = {...state, ...changed};
  }

  /// Finishes what an app that was killed in the middle of a download had started: the songs of every release the person asked to download,
  /// that the phone wrote down and that have no pin yet, are pinned now (D-35). Answers how many were pinned.
  ///
  /// It reads and writes the pins through a repository built here from the server it awaited, not through the providers the screens start: as
  /// the app starts nothing else has (a read of an auto-disposed stream nobody listens to fails, and the repository provider is still empty), and a
  /// failure here would be swallowed without a word.
  Future<int> resume() async {
    final server = await ref.read(activeServerProvider.future);
    if (server == null) return 0;
    final db = ref.read(databaseProvider);
    final store = ReleaseStore(db, server.id);
    final repo =
        DownloadsRepository(db, server.id, clock: ref.read(clockProvider));
    final quality = ref.read(settingsProvider).downloadQuality;
    final pinned = {
      for (final p in await repo.pins())
        if (p.targetType == PinTargetType.track.name) p.targetId,
    };
    var count = 0;
    for (final release in (await store.phone()).values) {
      if (!release.download) continue;
      for (final refId in release.refIds) {
        if (pinned.contains(refId)) continue;
        await repo.pin(PinTargetType.track, refId, quality: quality);
        count++;
      }
    }
    return count;
  }

  Future<ReleaseStore?> _store() async {
    final server = await ref.read(activeServerProvider.future);
    return server == null
        ? null
        : ReleaseStore(ref.read(databaseProvider), server.id);
  }
}

final releaseSavesProvider =
    NotifierProvider<ReleaseSaves, Map<String, ReleaseState>>(ReleaseSaves.new);

/// Where a release stands, wherever a person looks (D-35). A save on its way, or just finished or failed in this run, is in memory and wins.
/// Otherwise what the phone wrote down proves the server confirmed the save (even before the next sync), and a release the sync names is
/// saved too: on a second phone it is simply in the library, with no downloads (those belong to each phone).
final releaseStateProvider =
    Provider.autoDispose.family<ReleaseState?, String>((ref, releaseId) {
  final live = ref.watch(releaseSavesProvider)[releaseId];
  if (live != null) return live;
  final mine = ref.watch(phoneReleasesProvider).value?[releaseId];
  if (mine != null) {
    return ReleaseState(ReleasePhase.saved,
        download: mine.download, refIds: mine.refIds);
  }
  if ((ref.watch(savedReleasesProvider).value ?? const <String>{})
      .contains(releaseId)) {
    return const ReleaseState(ReleasePhase.saved);
  }
  return null;
});

/// Run once for each person who is using the phone, as the app starts: finishes the downloads a kill left half done ([ReleaseSaves.resume]).
final releaseResumeProvider = FutureProvider<int>((ref) async {
  final server = await ref.watch(activeServerProvider.future);
  if (server == null) return 0;
  return ref.read(releaseSavesProvider.notifier).resume();
});

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
