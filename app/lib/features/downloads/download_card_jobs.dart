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
  });

  final DownloadTarget target;
  final String name;

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
      ));
    } else if (type != null) {
      targets.add(CardTarget(
        target: DownloadTarget.pin(type, e.pin.targetId),
        name: e.title,
        playlistId: type == PinTargetType.playlist ? e.pin.targetId : null,
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

  for (final t in targets) {
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
    if (made != null) merged.add(made.id);
    final finding = made != null &&
            made.state != 'stopped' &&
            made.state != 'failed' &&
            made.pending > 0
        ? made
        : null;
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
    if (i.state == 'failed' || i.total < _kSmallestJob) continue;
    final job = _importJob(i, watch, keep, now);
    if (job != null) jobs.add(job);
  }
  return jobs;
});

CardJob? _importJob(
  EncoreImport i,
  ImportWatchState watch,
  KeepState keep,
  DateTime now,
) {
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
    key: 'import:${i.id}',
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
