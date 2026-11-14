import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/connection.dart' show serverReachabilityProvider;
import '../../data/catalogue/catalogue_models.dart';
import '../../data/encore/encore_instant.dart';
import '../../data/encore/encore_models.dart';
import 'instant_controller.dart';
import 'instant_play.dart';

/// Songs the server already knows it cannot get, marked before anybody taps them (N-13; drawn 14 Nov 2026, docs/design S-12, S-18, S-19).
///
/// A Search is all catalogue songs, which have no ref on the phone, so the screens ask the server once for the whole list they show
/// (`POST refs/unavailable`, a read: it makes no ref and asks YouTube nothing) and a row greys when its song is in the answer. What the server
/// said is kept until it stops believing it (`retryAfter`), so the same song in another list needs no second question.
///
/// **Safe across server versions:** a server with no such question (404 or 405) means "no verdicts here" for the rest of the session, and a plain
/// music server (no Encore on it) is never asked. Nothing is asked while the server is away (offline always wins, S-12), and a failed ask is simply
/// asked again the next time a list is shown.
final songMarksProvider =
    NotifierProvider<SongMarks, Map<String, EncoreUnavailable>>(SongMarks.new);

/// The mark of one catalogue song, or null: only while the server still believes it.
final songMarkProvider = Provider.family<EncoreUnavailable?, String>((ref, id) {
  final mark = ref.watch(songMarksProvider.select((marks) => marks[id]));
  if (mark == null) return null;
  return mark.liveAt(ref.read(songMarksClockProvider)()) ? mark : null;
});

/// The clock the marks are judged by; a test sets it.
final songMarksClockProvider =
    Provider<DateTime Function()>((ref) => DateTime.now);

/// How long a "no problem" answer is trusted before the same song is asked about again: a song the server learns it cannot get meanwhile gets its
/// mark within this long, without a question on every redraw.
const Duration kSongMarksFreshFor = Duration(minutes: 10);

/// At most this many songs go in one question (the server's limit).
const int kSongMarksPerAsk = 100;

class SongMarks extends Notifier<Map<String, EncoreUnavailable>> {
  bool _unsupported = false;
  final Map<String, DateTime> _askedAt = {};
  final Set<String> _asking = {};

  @override
  Map<String, EncoreUnavailable> build() => const {};

  /// Asks about the songs of a list that were not asked about lately. Never throws; does nothing where nothing can be asked.
  Future<void> check(List<CatalogueTrack> tracks) async {
    if (_unsupported || tracks.isEmpty) return;
    if (ref.read(serverReachabilityProvider).isAway) return;
    final now = ref.read(songMarksClockProvider)();
    // A mark the server no longer believes goes now, whether or not the question is asked again.
    final stillLive = {
      for (final e in state.entries)
        if (e.value.liveAt(now)) e.key: e.value,
    };
    if (stillLive.length != state.length) state = stillLive;
    final wanted = <CatalogueTrack>[
      for (final t in tracks)
        if (!_asking.contains(t.id) &&
            (_askedAt[t.id] == null ||
                now.difference(_askedAt[t.id]!) >= kSongMarksFreshFor))
          t,
    ];
    if (wanted.isEmpty) return;
    final backend = await ref.read(instantBackendProvider.future);
    if (backend is! EncoreInstantBackend) return;
    for (var start = 0; start < wanted.length; start += kSongMarksPerAsk) {
      final chunk = wanted.skip(start).take(kSongMarksPerAsk).toList();
      _asking.addAll(chunk.map((t) => t.id));
      try {
        final answer = await backend.unavailableAmong(
            [for (final t in chunk) InstantPlayService.requestFor(t)]);
        if (answer == null) continue; // could not be asked: next time
        if (!answer.supported) {
          _unsupported = true;
          return;
        }
        final marks = {...state};
        for (var i = 0; i < chunk.length; i++) {
          _askedAt[chunk[i].id] = now;
          final verdict = answer.verdicts[i];
          if (verdict != null && verdict.liveAt(now)) {
            marks[chunk[i].id] = verdict;
          } else {
            marks.remove(chunk[i].id);
          }
        }
        state = marks;
      } finally {
        _asking.removeAll(chunk.map((t) => t.id));
      }
    }
  }
}

/// The songs of a list, as one key: a screen watches [songMarksCheckProvider] with its list and the question is asked when the list is new.
class TrackList {
  TrackList(this.tracks) : _key = tracks.map((t) => t.id).join('\u0000');

  final List<CatalogueTrack> tracks;
  final String _key;

  @override
  bool operator ==(Object other) => other is TrackList && other._key == _key;

  @override
  int get hashCode => _key.hashCode;
}

/// Watch this with the list a screen shows (rows of catalogue songs): it asks the server which of them it cannot get, once per list.
final songMarksCheckProvider =
    FutureProvider.autoDispose.family<void, TrackList>((ref, list) async {
  // When the phone is no longer away the list is asked about again (the question is not asked while it is).
  ref.watch(serverReachabilityProvider.select((r) => r.isAway));
  // A provider may not change another while it is being built: let this build finish before the marks are touched.
  await Future<void>.value();
  await ref.read(songMarksProvider.notifier).check(list.tracks);
});
