import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:meta/meta.dart';

import '../../app/providers.dart';
import '../../core/logger.dart';
import '../../data/encore/encore_api.dart';
import '../../data/encore/encore_live.dart';
import '../../data/encore/encore_models.dart';
import '../../data/repos/downloads_repository.dart' show kLikedPinId;
import 'download_providers.dart';

/// The server's side of the phone's downloads (P2-22 parts 2 and 4, docs/17 "Keep progress").
///
/// A download has two stages: the server gets the songs, then the phone takes them. The phone's own table says how many songs are on the phone; this
/// says how far the **server** is: which downloads this phone watches (`PUT keep/watch`, said again on every reconnect, answered with the current
/// state), what it asks the server for (`POST keep/ask`, once per connection per download), what the server pushes (`keep.progress`), and Retry.
///
/// Events only make it faster, never correct: every reconnect says it all again and reads the answer. The server never hears which songs are on the
/// phone.

/// The Encore server's API when this phone is on one (only an Encore server keeps songs of its own), else `null`. Tests replace it.
final keepApiProvider = Provider<EncoreApi?>((ref) {
  return ref.watch(sessionProvider).value?.encoreApi;
});

/// What the server pushes down the live channel. Tests replace it.
final keepEventsProvider = Provider<Stream<LiveEvent>>((ref) =>
    ref.watch(sessionProvider).value?.live?.events ?? const Stream.empty());

/// `true` when the live channel connects, `false` when it ends. Tests replace it.
final keepConnectionProvider = Provider<Stream<bool>>((ref) =>
    ref.watch(sessionProvider).value?.live?.connection ?? const Stream.empty());

/// How long to wait for the pins to settle before talking to the server (a burst of pins and reconnects is one conversation).
final keepDebounceProvider =
    Provider<Duration>((ref) => const Duration(milliseconds: 600));

/// The most downloads one request may name (`keep/watch` replaces the whole list, so it cannot be sent in parts).
const int maxKeepGroups = 50;

/// The downloads that have songs on the server: each pinned playlist, the liked songs, and each catalogue release the person downloaded. Anything
/// else (a loose song, an album or artist of the person's own music) is not kept by the server on the person's behalf.
final keepGroupsProvider = Provider<List<KeepGroupKey>>((ref) {
  final pins = ref.watch(pinsProvider).value ?? const [];
  final releases = ref.watch(phoneReleasesProvider).value ?? const {};
  final keys = <KeepGroupKey>{};
  for (final pin in pins) {
    switch (pin.targetType) {
      case 'playlist':
        keys.add(KeepGroupKey('playlist', pin.targetId));
      case 'liked':
        keys.add(const KeepGroupKey('liked', kLikedPinId));
    }
  }
  for (final e in releases.entries) {
    if (e.value.download) {
      keys.add(KeepGroupKey('release', e.key, refs: e.value.refIds));
    }
  }
  final sorted = keys.toList()
    ..sort((a, b) => a.toString().compareTo(b.toString()));
  return sorted;
});

@immutable
class KeepState {
  const KeepState({
    this.supported = false,
    this.groups = const {},
    this.youtube = const KeepYoutube(),
    this.restingUntil,
    this.answered = false,
    this.stale = false,
    this.missing = const {},
  });

  /// The server keeps songs and tells the phone how it goes (`keep` in its features). Until it is known, and for a plain music server, the screens
  /// say what they have always said.
  final bool supported;

  final Map<KeepGroupKey, KeepGroup> groups;
  final KeepYoutube youtube;

  /// When YouTube lets the server go on, worked out ONCE when the answer arrived (`resumesInSec` counts down; adding it to "now" at every redraw
  /// would make the time slide), or `null` when it is not resting.
  final DateTime? restingUntil;

  /// The server has answered at least once in this session.
  final bool answered;

  /// The last try to talk to the server failed: the numbers may be old.
  final bool stale;

  /// Downloads the phone watches that the server did not answer for (a wrong id leaves a download without a line, silently, by design).
  final Set<KeepGroupKey> missing;

  KeepGroup? of(KeepGroupKey key) => groups[key];

  KeepState copyWith({
    bool? supported,
    Map<KeepGroupKey, KeepGroup>? groups,
    KeepYoutube? youtube,
    DateTime? Function()? restingUntil,
    bool? answered,
    bool? stale,
    Set<KeepGroupKey>? missing,
  }) =>
      KeepState(
        supported: supported ?? this.supported,
        groups: groups ?? this.groups,
        youtube: youtube ?? this.youtube,
        restingUntil: restingUntil == null ? this.restingUntil : restingUntil(),
        answered: answered ?? this.answered,
        stale: stale ?? this.stale,
        missing: missing ?? this.missing,
      );
}

final keepProvider =
    NotifierProvider<KeepController, KeepState>(KeepController.new);

class KeepController extends Notifier<KeepState> {
  EncoreApi? _api;

  /// Riverpod keeps ONE instance of this class and runs [build] again when the session changes (another server, a new sign-in), so every field is set
  /// again there, and every asynchronous step checks that the session it started in is still the current one: a late answer of the old server must
  /// not be written into the new state.
  int _generation = 0;
  Timer? _timer;
  bool _syncing = false;
  bool _again = false;

  /// What the server told us it can do; read again on every connection (a server may have been updated).
  bool _featuresKnown = false;
  bool _hasKeep = false;
  bool _hasAsk = false;

  /// Downloads already asked for on this connection: asking is once per connection, so a bad line that reconnects every second cannot make a storm.
  final Set<KeepGroupKey> _asked = {};
  Set<KeepGroupKey> _watched = {};
  final Set<KeepGroupKey> _reportedMissing = {};

  @override
  KeepState build() {
    final generation = ++_generation;
    _api = ref.watch(keepApiProvider);
    _timer?.cancel();
    _syncing = false;
    _again = false;
    _featuresKnown = false;
    _hasKeep = false;
    _hasAsk = false;
    _asked.clear();
    _watched = {};
    _reportedMissing.clear();
    ref.onDispose(() {
      _generation++; // what is still on its way belongs to a session that is over
      _timer?.cancel();
    });
    final api = _api;
    if (api == null) return const KeepState();

    final subs = <StreamSubscription<Object?>>[
      ref.watch(keepEventsProvider).listen((event) {
        if (event.type != 'keep.progress') return;
        final progress = KeepProgress.fromJson(event.data);
        if (generation != _generation) return;
        state = state.copyWith(
          groups: {for (final g in progress.groups) g.key: g},
          youtube: progress.youtube,
          restingUntil: () => _until(progress.youtube),
          answered: true,
          stale: false,
        );
      }),
      ref.watch(keepConnectionProvider).listen((up) {
        if (!up) return;
        _asked.clear();
        _featuresKnown = false;
        _schedule();
      }),
    ];
    ref.onDispose(() {
      for (final s in subs) {
        unawaited(s.cancel());
      }
    });
    ref.listen(keepGroupsProvider, (previous, next) {
      if (!_same(previous ?? const [], next)) _schedule();
    });
    _schedule();
    return const KeepState();
  }

  DateTime? _until(KeepYoutube youtube) => youtube.resting
      ? ref
          .read(clockProvider)
          .now()
          .add(Duration(seconds: youtube.resumesInSec))
      : null;

  static bool _same(List<KeepGroupKey> a, List<KeepGroupKey> b) =>
      a.length == b.length && a.toSet().containsAll(b);

  void _schedule() {
    _timer?.cancel();
    final generation = _generation;
    _timer = Timer(ref.read(keepDebounceProvider), () {
      if (generation == _generation) unawaited(_sync(generation));
    });
  }

  Future<void> _sync(int generation) async {
    if (_syncing) {
      _again = true;
      return;
    }
    _syncing = true;
    try {
      do {
        _again = false;
        await _syncOnce(generation);
      } while (_again && generation == _generation);
    } finally {
      if (generation == _generation) _syncing = false;
    }
  }

  Future<void> _syncOnce(int generation) async {
    final api = _api;
    if (api == null || generation != _generation) return;
    var groups = ref.read(keepGroupsProvider);
    if (groups.length > maxKeepGroups) {
      Log.warn('keep',
          'more than $maxKeepGroups downloads are pinned: only the first $maxKeepGroups are followed');
      groups = groups.sublist(0, maxKeepGroups);
    }

    if (!_featuresKnown) {
      final info = (await api.info()).valueOrNull;
      if (generation != _generation) return;
      if (info == null) {
        state = state.copyWith(stale: true);
        return;
      }
      _featuresKnown = true;
      _hasKeep = info.hasKeep;
      _hasAsk = info.hasKeepAsk;
    }
    if (state.supported != _hasKeep) {
      state = state.copyWith(supported: _hasKeep);
    }
    if (!_hasKeep) return;
    if (groups.isEmpty && _watched.isEmpty) return;

    final watched = (await api.watchKeep(groups)).valueOrNull;
    if (generation != _generation) return;
    if (watched == null) {
      state = state.copyWith(stale: true);
      return;
    }
    _watched = groups.toSet();
    final answered = {for (final g in watched.groups) g.key: g};
    final missing = {
      for (final g in groups)
        if (!answered.containsKey(g)) g
    };
    for (final g in missing) {
      if (_reportedMissing.add(g)) {
        Log.warn('keep',
            'the server did not answer for the download $g: it shows no server line (a wrong id looks like this)');
      }
    }
    state = state.copyWith(
      groups: answered,
      youtube: watched.youtube,
      restingUntil: () => _until(watched.youtube),
      answered: true,
      stale: false,
      missing: missing,
    );

    if (!_hasAsk) return;
    final todo = [
      for (final g in groups)
        if (!_asked.contains(g) && _askable(answered[g])) g
    ];
    if (todo.isEmpty) return;
    _asked.addAll(todo);
    final asked = (await api.askKeep(todo)).valueOrNull;
    if (generation != _generation) return;
    if (asked == null) {
      // Not heard (a line that dropped): the next look asks again.
      _asked.removeAll(todo);
      return;
    }
    state = state.copyWith(
      groups: {
        ...state.groups,
        for (final g in asked.progress.groups) g.key: g,
      },
      youtube: asked.progress.youtube,
      restingUntil: () => _until(asked.progress.youtube),
    );
  }

  /// Something the server can still be asked for: songs waiting in its queue, or ones nobody fetched. (A song whose keep failed is not tried by an
  /// ask, only by Retry; the server decides which is which, so this over-asks at most once per connection and writes nothing.)
  static bool _askable(KeepGroup? g) => g != null && g.queued + g.retryable > 0;

  /// The Retry button: asks the server again for the songs of ONE download that failed. Returns how many it asked for, or `null` when it could not
  /// (the server does not answer, or does not know that download any more).
  Future<int?> retry(KeepGroupKey key) async {
    final api = _api;
    if (api == null) return null;
    final generation = _generation;
    final result = (await api.retryKeep(key)).valueOrNull;
    if (result == null || generation != _generation) return null;
    final group = result.group;
    state = state.copyWith(
      groups: {...state.groups, if (group != null) group.key: group},
      youtube: result.youtube,
      restingUntil: () => _until(result.youtube),
    );
    return result.retried;
  }

  /// Looks at the server now (the person pinned something, or came back to a screen): the same conversation as at a connection.
  void refresh() => _schedule();
}
