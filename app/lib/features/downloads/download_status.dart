import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/encore/encore_models.dart';
import '../../data/repos/downloads_repository.dart';
import '../../design/tokens.dart';
import '../../domain/download_line.dart' show phoneFailureWords;
import 'download_line_providers.dart';
import 'download_providers.dart';
import 'keep_providers.dart';

/// The songs the PHONE could not take. Their sentences are in plain words (`phoneFailureWords`); the raw text the downloader recorded is never shown.
final phoneFailuresProvider = StreamProvider.autoDispose
    .family<List<FailedSong>, DownloadTarget>((ref, target) {
  final repo = ref.watch(downloadsRepositoryProvider);
  if (repo == null) return Stream.value(const []);
  return target.isRelease
      ? repo.watchFailedSongsIn(target.releaseRefIds)
      : repo.watchFailedSongs(target.type!, target.id);
});

/// The songs of a download that did not come, with the sentence for each: the server's (the cause for the Host, the plain fact for a member) and the
/// phone's.
final keepFailuresProvider = Provider.autoDispose
    .family<List<KeepFailure>, DownloadTarget>((ref, target) {
  final key = target.keepKey;
  final server = key == null
      ? const <KeepFailure>[]
      : ref.watch(keepProvider.select((s) => s.of(key)?.failures)) ??
          const <KeepFailure>[];
  final phone = ref.watch(phoneFailuresProvider(target)).value ?? const [];
  return [
    ...server,
    for (final f in phone)
      KeepFailure(
        ref: f.ref,
        title: f.title,
        artist: f.artist,
        reason: phoneFailureWords(f.error),
        retry: true,
      ),
  ];
});

/// What Retry does: asks the server again for the songs it failed to get (`keep/retry`), and the phone again for the files it could not take.
/// Both, because a download can be stuck on either side and the person pressed one button.
final retryDownloadProvider =
    Provider<Future<void> Function(DownloadTarget target)>((ref) {
  return (target) async {
    final key = target.keepKey;
    if (key != null) await ref.read(keepProvider.notifier).retry(key);
    await ref.read(downloadActionsProvider).retry();
  };
});

/// The bar under a download's line: filled = on the phone, lighter = ready on the server (docs/design S-16).
class DownloadBar extends StatelessWidget {
  const DownloadBar({
    super.key,
    required this.phoneFraction,
    required this.serverFraction,
  });

  final double phoneFraction;
  final double serverFraction;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    return ExcludeSemantics(
      child: SizedBox(
        height: 3,
        child: ClipRRect(
          borderRadius: BorderRadius.circular(2),
          child: Stack(
            fit: StackFit.expand,
            children: [
              ColoredBox(color: c.outline.withValues(alpha: 0.6)),
              FractionallySizedBox(
                alignment: AlignmentDirectional.centerStart,
                widthFactor: serverFraction.clamp(0.0, 1.0),
                child: ColoredBox(color: c.accent.withValues(alpha: 0.35)),
              ),
              FractionallySizedBox(
                alignment: AlignmentDirectional.centerStart,
                widthFactor: phoneFraction.clamp(0.0, 1.0),
                child: ColoredBox(color: c.accent),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// How many songs that did not come are named under a row; the rest are counted.
const int namedFailures = 3;

/// The line of the two stages for one download, with its bar, and - when songs did not come - Retry and, with [showNames], which ones and why. Shows
/// nothing for a download the person has not made, one that is finished, and the line a plain music server has always had (its screens keep their own).
class DownloadStatus extends ConsumerWidget {
  const DownloadStatus({
    super.key,
    required this.target,
    this.showNames = false,
    this.showLine = true,
    this.padding = EdgeInsets.zero,
  });

  final DownloadTarget target;

  /// Name the songs that did not come (the Library list); a page header keeps to the line.
  final bool showNames;

  /// Draw the line's text too. A row that already says it in its own subtitle passes `false` and gets only the bar and what follows.
  final bool showLine;

  /// Space around the status. It is part of the status, not of the row around it: when nothing is shown (a plain music server, a finished download)
  /// it takes no room at all, so those rows look exactly as they did.
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final line = ref.watch(downloadLineProvider(target));
    if (line == null || !line.twoStages || line.complete) {
      return const SizedBox.shrink();
    }
    // Names only while the line itself speaks of songs that did not come (not while the phone waits: the server's side is stale then).
    final failures = showNames && line.failed > 0
        ? ref.watch(keepFailuresProvider(target))
        : const <KeepFailure>[];
    final style = context.text.bodyMedium;
    return Padding(
        padding: padding,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            if (showLine) Text(line.text, style: style),
            const SizedBox(height: Space.xs),
            DownloadBar(
                phoneFraction: line.phoneFraction,
                serverFraction: line.serverFraction),
            // Retry never stands alone (owner, 7 Nov 2026: "a download that has no failed, or at least I can't tell it failed, why does it have a
            // Retry button"): while songs are still coming the line speaks of progress only, so the failures are told on their own line, whether or not
            // the names follow.
            if (line.failed > 0 && !line.text.contains('did not come'))
              Text(
                  '${line.failed == 1 ? '1 song' : '${line.failed} songs'} did not come',
                  style: style),
            if (line.failed > 0 && line.canRetry)
              Align(
                alignment: AlignmentDirectional.centerStart,
                child: TextButton(
                  onPressed: () => ref.read(retryDownloadProvider)(target),
                  child: Semantics(
                    label: 'Retry the songs that did not come',
                    excludeSemantics: true,
                    child: const Text('Retry'),
                  ),
                ),
              ),
            for (final f in failures.take(namedFailures))
              Text(f.title.isEmpty ? f.reason : '${f.title}: ${f.reason}',
                  style: context.text.bodySmall),
            if (showNames && failures.isNotEmpty && line.failed > namedFailures)
              Text('and ${line.failed - namedFailures} more',
                  style: context.text.bodySmall),
          ],
        ));
  }
}
