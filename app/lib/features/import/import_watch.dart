import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:meta/meta.dart';

import '../../app/app_in_front.dart';
import '../../app/providers.dart';
import '../../core/logger.dart';
import '../../data/encore/encore_api.dart';
import '../../data/encore/encore_models.dart';
import '../downloads/keep_providers.dart';

/// How often the server is asked while an import is still saving its songs.
final importPollProvider =
    Provider<Duration>((ref) => const Duration(seconds: 10));

/// How long an import that has stopped changing is waited for: songs the server could not get never come, and a card that waited for them for ever
/// would be a lie told every time the app is opened. The same patience applies to an import the server still calls `running` (it is stuck: see
/// [ImportWatchState.stalled]): asking every few seconds for ever, in the background, would cost every phone its battery for nothing.
const Duration kImportPatience = Duration(minutes: 30);

/// An import older than this is history, not something that is being saved.
const Duration kImportRecent = Duration(hours: 24);

@immutable
class ImportWatchState {
  const ImportWatchState({
    this.imports = const [],
    this.saving = const {},
    this.stalled = const {},
    this.stoppedHere = const {},
  });

  final List<EncoreImport> imports;

  /// Imports whose songs are all found but not all kept by the server yet, and are still moving: the server stage of an import, which is the long
  /// part (tens of minutes for a long list) and the one nobody could see.
  final Set<String> saving;

  /// Imports the server calls running whose numbers have not changed for [kImportPatience]: a stuck import. It is not followed (no asking every few
  /// seconds, no card) until something about it changes.
  final Set<String> stalled;

  /// Imports the person stopped on THIS phone: ending one of these leaves no card (the person knows).
  final Set<String> stoppedHere;
}

/// The person's imports, kept in step for the card of the downloads (docs/design S-95, P2-29); one instance for the whole app.
///
/// The server **pushes** `import.progress` (flat: `importId, state, total, matched, unmatched, pending, kept`) when a song of an import has been
/// matched and when an import is stopped; it does **not** push when its keeper stores a song, so `kept` moves silently after the matching. The watch
/// therefore reads `GET imports` at the start, at every (re)connection and every return to the app (events only make it faster, never correct, as
/// `keep.progress` does), takes the pushes as they come, and asks again every [importPollProvider] **only while an import is still running or saving
/// and has moved in the last [kImportPatience]**. Idle, or stuck, it asks nothing; a push or a look that finds a change makes it follow the import
/// again.
final importWatchProvider =
    NotifierProvider<ImportWatch, ImportWatchState>(ImportWatch.new);

class ImportWatch extends Notifier<ImportWatchState> {
  EncoreApi? _api;
  int _generation = 0;
  Timer? _timer;
  final Map<String, String> _seen = {};
  final Map<String, DateTime> _changedAt = {};

  @override
  ImportWatchState build() {
    final generation = ++_generation;
    _timer?.cancel();
    _seen.clear();
    _changedAt.clear();
    final api = _api = ref.watch(keepApiProvider);
    ref.onDispose(() {
      _generation++;
      _timer?.cancel();
    });
    if (api == null) return const ImportWatchState();

    final subs = <StreamSubscription<Object?>>[
      ref.watch(keepEventsProvider).listen((event) {
        if (event.type == 'import.progress') {
          _onProgress(event.data, generation);
        }
      }),
      ref.watch(keepConnectionProvider).listen((up) {
        if (up) unawaited(resync());
      }),
    ];
    ref.onDispose(() {
      for (final s in subs) {
        unawaited(s.cancel());
      }
    });
    // Coming back to the app: what happened meanwhile (an import ended, one was stopped elsewhere) is read now.
    ref.listen(appInFrontProvider, (_, front) {
      if (front) unawaited(resync());
    });
    unawaited(resync());
    return const ImportWatchState();
  }

  /// Reads the list of imports now (the person has just started one, the line came back, the app came back).
  Future<void> resync() async {
    final api = _api;
    final generation = _generation;
    if (api == null) return;
    final result = await api.imports();
    if (generation != _generation) return;
    final list = result.valueOrNull;
    if (list == null) {
      Log.debug('import', 'imports not read: ${result.failureOrNull?.message}');
      _schedule();
      return;
    }
    _apply(list);
  }

  void _onProgress(Map<String, dynamic> data, int generation) {
    if (generation != _generation) return;
    final id = data['importId'];
    final known = [
      for (final i in state.imports)
        if (i.id == id) i
    ];
    if (id is! String || known.isEmpty) {
      // An import this phone has not heard of (started on another device): the list says what it is.
      unawaited(resync());
      return;
    }
    int count(String key, int fallback) {
      final v = data[key];
      return v is num ? v.toInt() : fallback;
    }

    final old = known.single;
    final next = old.withProgress(
      state: data['state'] is String ? data['state'] as String : old.state,
      total: count('total', old.total),
      matched: count('matched', old.matched),
      unmatched: count('unmatched', old.unmatched),
      pending: count('pending', old.pending),
      kept: count('kept', old.kept),
    );
    _apply([for (final i in state.imports) i.id == id ? next : i]);
  }

  void _apply(List<EncoreImport> list) {
    final now = ref.read(clockProvider).now();
    final saving = <String>{};
    final stalled = <String>{};
    for (final i in list) {
      final signature =
          '${i.state}|${i.matched}|${i.unmatched}|${i.pending}|${i.kept}';
      if (_seen[i.id] != signature) {
        _seen[i.id] = signature;
        _changedAt[i.id] = now;
      }
      final recent = i.createdAtMs <= 0 ||
          now.difference(DateTime.fromMillisecondsSinceEpoch(i.createdAtMs)) <
              kImportRecent;
      final moving = now.difference(_changedAt[i.id]!) < kImportPatience;
      if (i.state == 'done' && i.matched > i.kept && recent && moving) {
        saving.add(i.id);
      } else if (i.isRunning && !moving) {
        stalled.add(i.id);
      }
    }
    state = ImportWatchState(
      imports: list,
      saving: saving,
      stalled: stalled,
      stoppedHere: state.stoppedHere,
    );
    _schedule();
  }

  /// Asks again in a while, if anything is still going on; otherwise nothing is scheduled.
  void _schedule() {
    _timer?.cancel();
    _timer = null;
    final active = state.saving.isNotEmpty ||
        state.imports.any((i) => i.isRunning && !state.stalled.contains(i.id));
    if (!active || _api == null) return;
    _timer = Timer(ref.read(importPollProvider), () => unawaited(resync()));
  }

  /// Stops an import for the person. It is remembered as stopped HERE, so that its end leaves no card (a stop somewhere else does).
  Future<void> stop(String id) async {
    final api = _api;
    if (api == null) return;
    state = ImportWatchState(
      imports: state.imports,
      saving: state.saving,
      stalled: state.stalled,
      stoppedHere: {...state.stoppedHere, id},
    );
    final stopped = await api.stopImport(id);
    if (stopped.isErr) {
      Log.debug('import', 'could not stop $id: ${stopped.failureOrNull}');
    }
    await resync();
  }
}
