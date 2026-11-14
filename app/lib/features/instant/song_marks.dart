import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/catalogue/catalogue_models.dart';
import '../../data/db/app_database.dart' show TrackRow;
import '../../data/encore/encore_instant.dart';
import '../../data/encore/encore_models.dart';
import '../common/playability.dart' show serverAwayProvider;
import '../providers.dart' show downloadedIdsProvider;
import 'instant_controller.dart';
import 'instant_play.dart';
import 'song_refusals.dart';

/// Songs the server already knows it cannot get, marked before anybody taps them (N-13; drawn 14 Nov 2026, docs/design S-12, S-15, S-17, S-18, S-19, S-34).
///
/// The screens ask the server once for the whole list they show (`POST refs/unavailable`, a read: it makes no ref and asks YouTube nothing) and a row
/// greys when its song is in the answer. A song is asked about the way the phone knows it: **a catalogue song** (Search, an album, an artist's Popular
/// songs) has no ref on the phone, so it is described; **a row of the phone's own library** is a ref, so it is asked by its ref id, the exact identity
/// (B-128: the song somebody tapped is a library row from then on, and a playlist entry or a liked song may have no file). What the server said is kept
/// until it stops believing it (`retryAfter`), so the same song in another list needs no second question. The two kinds of key (a catalogue id, a ref id)
/// never meet in one map entry.
///
/// **Safe across server versions:** a server with no such question (404 or 405) means "no verdicts here" for the rest of the session, one that does not
/// list `unavailable-ids` is never asked by ref id (a server of before B-128 would answer 400), and a plain music server (no Encore on it) is never
/// asked. Nothing is asked and nothing is shown while the server is away (offline always wins, S-12), and a failed ask is simply asked again the next
/// time a list is shown.
final songMarksProvider =
    NotifierProvider<SongMarks, Map<String, EncoreUnavailable>>(SongMarks.new);

/// The mark of one song (a catalogue id or a ref id), or null: only while the server still believes it and the server can be reached (offline always
/// wins: the row says "Not downloaded", or nothing, and the tap goes down the offline path).
final songMarkProvider = Provider.family<EncoreUnavailable?, String>((ref, id) {
  if (ref.watch(serverAwayProvider)) return null;
  final mark = ref.watch(songMarksProvider.select((marks) => marks[id]));
  if (mark == null) return null;
  return mark.liveAt(ref.read(songMarksClockProvider)()) ? mark : null;
});

/// What a library row needs to know to be marked: its ref id, and whether the server keeps a file of it (or it is not a ref at all: a plain music
/// server's row), which can never be unavailable.
typedef LibraryMarkKey = ({String id, bool hasFile});

extension LibraryMarkOfTrack on TrackRow {
  /// A row with a file on the server, or of a plain music server, is never asked about and never marked: it plays.
  LibraryMarkKey get markKey => (id: id, hasFile: fileId != null || !isRef);

  /// Whether this row is one the server may not be able to get: a ref of an Encore server with no file (and, to be asked, not on the phone either:
  /// see [libraryMarkProvider]).
  bool get mayBeUnavailable => isRef && fileId == null;
}

/// The mark of a row of the phone's own library, or null. **The rule that a song which can be played is never shown marked lives here, not in the
/// map:** a row with a file of the server, a row of a plain music server and a song downloaded on the phone are never marked, whatever the map holds
/// (a file may arrive inside the server's window; the server clears its memory then, the phone learns it at its next question).
final libraryMarkProvider =
    Provider.family<EncoreUnavailable?, LibraryMarkKey>((ref, row) {
  if (row.hasFile) return null;
  final downloaded = ref.watch(downloadedIdsProvider
      .select((ids) => ids.value?.contains(row.id) ?? false));
  if (downloaded) return null;
  return ref.watch(songMarkProvider(row.id));
});

/// The clock the marks are judged by; a test sets it.
final songMarksClockProvider =
    Provider<DateTime Function()>((ref) => DateTime.now);

/// How long a "no problem" answer is trusted before the same song is asked about again: a song the server learns it cannot get meanwhile gets its mark
/// within this long, without a question on every redraw. **A refusal ends the trust at once** ([SongMarks.refused]).
const Duration kSongMarksFreshFor = Duration(minutes: 10);

/// At most this many songs go in one question (the server's limit).
const int kSongMarksPerAsk = 100;

class SongMarks extends Notifier<Map<String, EncoreUnavailable>> {
  bool _unsupported = false;
  bool _unsupportedIds = false;
  final Map<String, DateTime> _askedAt = {};

  /// The keys being asked about now, each with the number of refusals ([songRefusalsProvider]) the question was asked under.
  final Map<String, int> _asking = {};

  /// The number of refusals the "no problem" answers in [_askedAt] were made under.
  int _epoch = 0;

  @override
  Map<String, EncoreUnavailable> build() => const {};

  /// Asks about the songs of a list that were not asked about lately. Never throws; does nothing where nothing can be asked.
  Future<void> check(TrackList list) async {
    if (list.isEmpty) return;
    if (ref.read(serverAwayProvider)) return;
    final now = ref.read(songMarksClockProvider)();
    // **A refusal ends the trust in "no problem" at once.** The server has just told this phone that its memory of what it cannot get changed (a
    // stream was refused for good, or a tap found the song marked): every answer of before may be stale, so every list asks again now. The phone does not
    // copy what the server knows (the reason, the sentence, the 7 days: its rule, which would rot here the day it changes, and an older server that
    // remembers nothing would be handed a mark it never made): it asks. If that read fails the row stays as it was and the next tap is refused from the
    // server's memory with no look-up at YouTube, so the failure is quiet and cheap.
    final epoch = ref.read(songRefusalsProvider);
    if (epoch != _epoch) {
      _epoch = epoch;
      _askedAt.clear();
    }
    // A mark the server no longer believes goes now, whether or not the question is asked again.
    final stillLive = {
      for (final e in state.entries)
        if (e.value.liveAt(now)) e.key: e.value,
    };
    if (stillLive.length != state.length) state = stillLive;
    bool wanted(String key) =>
        _asking[key] != epoch &&
        (_askedAt[key] == null ||
            now.difference(_askedAt[key]!) >= kSongMarksFreshFor);
    final tracks = [
      if (!_unsupported)
        for (final t in list.tracks)
          if (wanted(t.id)) t,
    ];
    final refIds = [
      if (!_unsupportedIds)
        for (final id in list.refIds)
          if (wanted(id)) id,
    ];
    if (tracks.isEmpty && refIds.isEmpty) return;
    final backend = await ref.read(instantBackendProvider.future);
    if (backend is! EncoreInstantBackend) return;
    await _ask<CatalogueTrack>(
      epoch,
      tracks,
      keyOf: (t) => t.id,
      ask: (chunk) => backend.unavailableAmong(
          [for (final t in chunk) InstantPlayService.requestFor(t)]),
      unsupported: () => _unsupported = true,
    );
    await _ask<String>(
      epoch,
      refIds,
      keyOf: (id) => id,
      ask: backend.unavailableAmongRefs,
      unsupported: () => _unsupportedIds = true,
    );
  }

  Future<void> _ask<T>(
    int epoch,
    List<T> items, {
    required String Function(T) keyOf,
    required Future<({bool supported, List<EncoreUnavailable?> verdicts})?>
            Function(List<T> chunk)
        ask,
    required void Function() unsupported,
  }) async {
    for (var start = 0; start < items.length; start += kSongMarksPerAsk) {
      final chunk = items.skip(start).take(kSongMarksPerAsk).toList();
      final keys = [for (final item in chunk) keyOf(item)];
      final now = ref.read(songMarksClockProvider)();
      for (final key in keys) {
        _asking[key] = epoch;
      }
      try {
        final answer = await ask(chunk);
        if (!ref.mounted) return;
        // Asked before a refusal: its "no problem" may be the very thing the refusal made untrue. It is dropped; the lists ask again.
        if (ref.read(songRefusalsProvider) != epoch) continue;
        if (answer == null) continue; // could not be asked: next time
        if (!answer.supported) {
          unsupported();
          return;
        }
        final marks = {...state};
        for (var i = 0; i < keys.length; i++) {
          _askedAt[keys[i]] = now;
          final verdict = answer.verdicts[i];
          if (verdict != null && verdict.liveAt(now)) {
            marks[keys[i]] = verdict;
          } else {
            marks.remove(keys[i]);
          }
        }
        state = marks;
      } finally {
        for (final key in keys) {
          if (_asking[key] == epoch) _asking.remove(key);
        }
      }
    }
  }
}

/// The songs of a list, as one key: the catalogue songs a screen shows (asked about by description) and the rows of the phone's own library it shows
/// ([refIds], asked about by ref id; give only the rows that [LibraryMarkOfTrack.mayBeUnavailable] and that are not downloaded). A screen watches
/// [songMarksCheckProvider] with its list and the question is asked when the list is new.
class TrackList {
  TrackList(this.tracks, {this.refIds = const []})
      : _key = '${tracks.map((t) => t.id).join('\u0000')}\u0001'
            '${refIds.join('\u0000')}';

  final List<CatalogueTrack> tracks;
  final List<String> refIds;
  final String _key;

  bool get isEmpty => tracks.isEmpty && refIds.isEmpty;

  @override
  bool operator ==(Object other) => other is TrackList && other._key == _key;

  @override
  int get hashCode => _key.hashCode;
}

/// Watch this with the list a screen shows: it asks the server which of its songs it cannot get, once per list (and again after a refusal).
final songMarksCheckProvider =
    FutureProvider.autoDispose.family<void, TrackList>((ref, list) async {
  // When the phone is no longer away the list is asked about again (the question is not asked while it is), and after a refusal.
  ref.watch(serverAwayProvider);
  ref.watch(songRefusalsProvider);
  // A provider may not change another while it is being built: let this build finish before the marks are touched.
  await Future<void>.value();
  await ref.read(songMarksProvider.notifier).check(list);
});
