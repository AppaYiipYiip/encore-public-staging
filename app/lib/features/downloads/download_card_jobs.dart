import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart' show clockProvider;
import '../../data/encore/encore_models.dart';
import '../../data/repos/downloads_repository.dart';
import '../../domain/download_card.dart';
import '../../domain/download_card_words.dart';
import '../../domain/download_line.dart';
import '../import/import_watch.dart';
import '../instant/release_save.dart' show releasePinStateProvider;
import 'download_line_providers.dart';
import 'download_providers.dart';
import 'keep_providers.dart';

/// What the card of the downloads follows (docs/design S-95, P2-29): every download the person has (a playlist, an album, an artist, the liked songs,
/// a catalogue release), and every import of an Encore server, as [CardJob]s. The words of a download are S-16's own line (`downloadLineProvider`, the
/// one phrasing of how a download is going); the numbers are the phone's own table and the server's keep answer. Nothing is decided here about WHEN a
/// card is posted: that is `DownloadCardPresenter`.

/// One download the card can follow.
class CardTarget {
  const CardTarget({
    required this.target,
    required this.name,
    this.playlistId,
    this.knownSongs,
  });

  final DownloadTarget target;
  final String name;

  /// How many songs the download has, when the phone already knows (so that a single song is no card even in its first second, before any
  /// count of the download exists), else `null`.
  final int? knownSongs;

  /// The playlist this download is, when it is one: an import that made it is the same job.
  final String? playlistId;

  /// The same download is the same key from one moment to the next: it is what a result card is replaced by.
  String get key => target.isRelease
      ? 'release:${target.id}'
      : 'pin:${target.type!.name}:${target.id}';
}

/// The downloads the person has, without the loose songs (a song is never a card).
final cardTargetsProvider = Provider<List<CardTarget>>((ref) {
  final entries = ref.watch(downloadGroupEntriesProvider).value ?? const [];
  final targets = <CardTarget>[];
  for (final e in entries) {
    final type = PinTargetType.values.asNameMap()[e.pin.targetType];
    if (e.releaseId != null) {
      targets.add(CardTarget(
        target: DownloadTarget.release(e.releaseId!, e.releaseRefIds),
        name: e.title,
        knownSongs: e.songCount,
      ));
    } else if (type != null) {
      targets.add(CardTarget(
        target: DownloadTarget.pin(type, e.pin.targetId),
        name: e.title,
        playlistId: type == PinTargetType.playlist ? e.pin.targetId : null,
        knownSongs: e.songCount,
      ));
    }
  }
  return targets;
});

const DownloadCardWords _words = DownloadCardWords();

/// A job is a download of one song at most: a card for one song is seconds long and nobody wants it ("we all hate those").
const int _kSmallestJob = 2;

final downloadCardJobsProvider = Provider<List<CardJob>>((ref) {
  final targets = ref.watch(cardTargetsProvider);
  final watch = ref.watch(importWatchProvider);
  final keep = ref.watch(keepProvider);
  final importOf = <String, EncoreImport>{
    for (final i in watch.imports)
      if (i.playlistId != null) i.playlistId!: i,
  };
  final jobs = <CardJob>[];
  final merged = <String>{};

  /// Imports that go on beside a Download the person stopped (N-39): a job of their own, with a key of their own.
  final beside = <String>{};

  for (final t in targets) {
    // One song is seconds long and nobody wants a card for it: not even for the first second, "Starting...", that would be gone a moment later.
    if ((t.knownSongs ?? _kSmallestJob) < _kSmallestJob) continue;
    final line = ref.watch(downloadLineProvider(t.target));
    if (line == null) continue;
    final phone = t.target.isRelease
        ? ref.watch(releasePinStateProvider(t.target.releaseRefIds.join(',')))
        : ref.watch(pinStateProvider((t.target.type!, t.target.id))).value ??
            PinState.none;
    if (phone.phase == PinPhase.empty) continue;
    final key = t.target.keepKey;
    final group = key == null || !keep.supported ? null : keep.of(key);
    var songs = phone.total > 0 ? phone.total : group?.total ?? 0;
    final held = group == null ? phone.done : group.ready;
    final ready = held < phone.done ? phone.done : held;
    final saving = group != null && group.keeping + group.queued > 0;

    // An import that made this playlist and is still going is the same job, its words first.
    final made = t.playlistId == null ? null : importOf[t.playlistId];
    // A stuck import (the server says running, nothing has changed for half an hour) lends the Download nothing: it is a Download again.
    // KNOWN GAP (docs/33 PB-43 (i)): an import stopped on another device while this Download goes on leaves no "Import stopped" card: the one job
    // is the Download, and its line is the download's. Removal trigger: a frame for it drawn in S-95.
    final going = made != null &&
        made.state != 'stopped' &&
        made.state != 'failed' &&
        made.pending > 0 &&
        !watch.stalled.contains(made.id);
    // A Download the person stopped (N-39) stops only the phone copy: the import goes on, on its own Stop. The card is then the download's ("Prog snob
    // is stopped") and the import is a job of its own (its running words, its end card when it comes), not the words of this one.
    final finding = going && !line.stopped ? made : null;
    if (made != null) {
      (going && line.stopped ? beside : merged).add(made.id);
    }
    final importing = finding != null;
    if (finding != null) songs = finding.total;
    if (songs < _kSmallestJob && !line.starting) continue;

    final bar = downloadBar(songs: songs, onPhone: phone.done, ready: ready);
    jobs.add(CardJob(
      key: t.key,
      name: t.name,
      text: finding != null
          ? _words.findingSongs(
              looked: finding.matched + finding.unmatched, total: finding.total)
          : line.text,
      songs: songs,
      onPhone: phone.done,
      ready: ready,
      failed: line.failed,
      phase: line.complete
          ? CardPhase.ready
          : line.stopped
              ? CardPhase.stopped
              : line.stuck
                  ? CardPhase.partly
                  : CardPhase.running,
      starting: line.starting && !importing,
      saving: saving || importing,
      importing: importing,
      progressDone: bar.done,
      progressOf: bar.of,
    ));
  }

  final now = ref.read(clockProvider).now();
  for (final i in watch.imports) {
    if (merged.contains(i.id) || watch.stoppedHere.contains(i.id)) continue;
    // KNOWN GAP (docs/33 PB-43 (ii)): a failed import is dropped here, so its running card goes away with no word and no result card (the import
    // page still says it failed). Removal trigger: a frame for it drawn in S-95.
    if (i.state == 'failed' || i.total < _kSmallestJob) continue;
    final job = _importJob(i, watch, keep, now, ownKey: beside.contains(i.id));
    if (job != null) jobs.add(job);
  }
  return jobs;
});

CardJob? _importJob(
  EncoreImport i,
  ImportWatchState watch,
  KeepState keep,
  DateTime now, {
  bool ownKey = false,
}) {
  // A stuck import is not followed: it is ABSENT (not "over": that would be a result card saying it is ready, which it is not). Its card, if one was
  // on screen, goes away; the import page still says what the server says, and a change brings the card back.
  if (watch.stalled.contains(i.id)) return null;
  final running = i.isRunning || watch.saving.contains(i.id);
  final recent = i.createdAtMs <= 0 ||
      now.difference(DateTime.fromMillisecondsSinceEpoch(i.createdAtMs)) <
          kImportRecent;
  // What is over and old is history: it is not followed, and it never makes a card.
  if (!running && !recent) return null;

  final phase = running
      ? CardPhase.running
      : i.state == 'stopped'
          ? CardPhase.stopped
          : CardPhase.ready;
  final finding = i.pending > 0;
  final String text;
  if (finding) {
    text = _words.findingSongs(looked: i.matched + i.unmatched, total: i.total);
  } else {
    text = describeDownload(DownloadFacts(
      phoneDone: 0,
      phoneTotal: 0,
      serverKeeps: true,
      server: ServerStage(
        total: i.matched,
        ready: i.kept,
        keeping: 0,
        queued: i.matched > i.kept ? i.matched - i.kept : 0,
        failed: 0,
        restingUntil: keep.restingUntil,
      ),
    )).text;
  }
  final bar = importBar(
    total: i.total,
    matched: i.matched,
    unmatched: i.unmatched,
    kept: i.kept,
  );
  final playlist = i.playlistId;
  return CardJob(
    // The key of the playlist when it has one, the same key the Download of that playlist has: pressing Download on a playlist that is still
    // being imported must not look like another job (the bar would start again, and the card of its end would be two).
    // The one exception: beside a Download that the person stopped (N-39) it is its own job, so that the stopped download's card and the import's end
    // are two cards and not one replaced by the other.
    key: playlist == null || ownKey
        ? 'import:${i.id}'
        : 'pin:playlist:$playlist',
    name: i.name,
    kind: CardJobKind.import,
    text: text,
    songs: i.total,
    serverTotal: finding ? null : i.matched,
    ready: i.kept,
    inLibrary: i.matched,
    phase: phase,
    starting: i.total == 0,
    saving: running,
    importing: true,
    liked: playlist == null,
    progressDone: bar.done,
    progressOf: bar.of,
    importRoute:
        playlist == null ? '/library/liked' : '/library/playlist/$playlist',
  );
}
