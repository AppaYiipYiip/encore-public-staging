import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/navigation.dart';
import '../../data/fetch/import_models.dart';
import '../../design/tokens.dart';
import '../common/format.dart';
import 'import_providers.dart';

/// One import as a card: how far it is, what it is waiting for, and what to do
/// next (open the playlist, see the songs that were not found, stop it).
class ImportCard extends ConsumerWidget {
  const ImportCard({super.key, required this.job, this.compact = false});

  final ImportJob job;

  /// The Home version: one line and a bar, tapping it opens the import page.
  final bool compact;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.colors;
    final running = job.isRunning;
    final icon = running
        ? Icons.downloading_rounded
        : switch (job.state) {
            ImportState.done when job.missing == 0 =>
              Icons.check_circle_outline_rounded,
            ImportState.done => Icons.task_alt_rounded,
            ImportState.cancelled => Icons.stop_circle_outlined,
            _ => Icons.error_outline_rounded,
          };

    final children = <Widget>[
      Row(
        children: [
          Icon(icon, color: running ? c.accent : c.onBgMuted),
          const SizedBox(width: Space.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  job.isLiked ? 'Your liked songs' : job.name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: context.text.titleSmall,
                ),
                const SizedBox(height: Space.xxs),
                Text(
                  _status(),
                  maxLines: compact ? 1 : 3,
                  overflow: TextOverflow.ellipsis,
                  style: context.text.bodySmall?.copyWith(color: c.onBgMuted),
                ),
              ],
            ),
          ),
          if (compact && job.isFinished)
            IconButton(
              tooltip: 'Got it',
              icon: const Icon(Icons.close_rounded),
              onPressed: () =>
                  unawaited(ref.read(importsProvider.notifier).dismiss(job.id)),
            ),
        ],
      ),
      if (running) ...[
        const SizedBox(height: Space.md),
        ClipRRect(
          borderRadius: BorderRadius.circular(4),
          child: LinearProgressIndicator(
            value: job.total == 0 ? null : job.fraction,
            minHeight: 6,
          ),
        ),
      ],
      if (!compact) ..._actions(context, ref),
    ];

    final card = Card(
      margin: EdgeInsets.symmetric(
        horizontal: Space.gutter,
        vertical: compact ? Space.sm : Space.xs,
      ),
      child: Padding(
        padding: const EdgeInsets.all(Space.lg),
        child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch, children: children),
      ),
    );
    if (!compact) {
      return KeyedSubtree(key: Key('import-${job.id}'), child: card);
    }
    // On Home: a running import opens the page that shows it; a finished one
    // opens what it made (the playlist, or the liked songs).
    final playlist = job.playlistId;
    return InkWell(
      key: Key('import-${job.id}'),
      onTap: () {
        if (job.isFinished && playlist != null && !job.isLiked) {
          Nav.playlist(context, playlist);
        } else if (job.isFinished && job.isLiked && job.added > 0) {
          Nav.liked(context);
        } else if (job.isRunning) {
          Nav.importedPlaylist(context, job.id);
        } else {
          unawaited(context.push('/settings/import'));
        }
      },
      child: card,
    );
  }

  String _status() {
    if (job.isRunning) {
      final base = job.total == 0
          ? 'Starting...'
          : '${job.done} of ${plural(job.total, 'song')}';
      final paused = job.pausedMessage;
      if (paused != null) return '$base. $paused';
      final eta = job.etaText;
      return eta == null ? base : '$base - $eta';
    }
    final message = job.message;
    if (message != null && message.isNotEmpty) return message;
    return switch (job.state) {
      ImportState.cancelled => 'Stopped. ${plural(job.added, 'song')} added.',
      ImportState.failed => 'This import could not be finished.',
      _ => '${plural(job.added, 'song')} added.',
    };
  }

  List<Widget> _actions(BuildContext context, WidgetRef ref) {
    final playlist = job.playlistId;
    return [
      Wrap(
        alignment: WrapAlignment.end,
        spacing: Space.sm,
        children: [
          if (job.missing > 0)
            TextButton(
              onPressed: () => unawaited(_showMissing(context, ref)),
              child: Text(job.missing == 1
                  ? '1 song not found'
                  : '${job.missing} songs not found'),
            ),
          // While it runs the page lists every song at once, each one
          // playable now; afterwards the playlist in the library is the real
          // thing (likes, edits, offline).
          if (job.isRunning)
            FilledButton.tonal(
              onPressed: () => Nav.importedPlaylist(context, job.id),
              child: Text(job.isLiked ? 'See the songs' : 'Open playlist'),
            )
          else if (playlist != null && !job.isLiked)
            FilledButton.tonal(
              onPressed: () => Nav.playlist(context, playlist),
              child: const Text('Open playlist'),
            ),
          if (job.isFinished && job.isLiked && job.added > 0)
            FilledButton.tonal(
              onPressed: () => Nav.liked(context),
              child: const Text('Open liked songs'),
            ),
          if (job.isRunning)
            TextButton(
              onPressed: () => unawaited(_confirmStop(context, ref)),
              child: const Text('Stop'),
            ),
        ],
      ),
    ];
  }

  Future<void> _confirmStop(BuildContext context, WidgetRef ref) async {
    final stop = await showDialog<bool>(
      context: context,
      builder: (dialog) => AlertDialog(
        title: const Text('Stop this import?'),
        content: Text('The ${plural(job.added, 'song')} that arrived stay in '
            'your library${job.isLiked ? '' : ' and in the playlist'}. '
            'The rest are not fetched.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialog).pop(false),
            child: const Text('Keep going'),
          ),
          TextButton(
            onPressed: () => Navigator.of(dialog).pop(true),
            child: const Text('Stop'),
          ),
        ],
      ),
    );
    if (stop ?? false) {
      await ref.read(importsProvider.notifier).cancel(job.id);
    }
  }

  Future<void> _showMissing(BuildContext context, WidgetRef ref) async {
    final full = await ref.read(importsProvider.notifier).details(job.id);
    if (!context.mounted) return;
    final songs = full?.missingSongs ?? const <MissingSong>[];
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (sheet) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: 0.7,
        builder: (context, scroll) => ListView(
          controller: scroll,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(
                  Space.gutter, 0, Space.gutter, Space.sm),
              child: Text('Songs that could not be added',
                  style: context.text.titleMedium),
            ),
            if (songs.isEmpty)
              const ListTile(
                  title: Text('The list is not available right now.')),
            for (final song in songs)
              ListTile(
                title: Text(song.title,
                    maxLines: 1, overflow: TextOverflow.ellipsis),
                subtitle: Text(
                    '${song.artist}${song.message.isEmpty ? '' : '\n${song.message}'}'),
                isThreeLine: song.message.isNotEmpty,
              ),
          ],
        ),
      ),
    );
  }
}

/// The part of Home that tells about imports: the ones that run and the ones
/// that just finished and were not closed yet.
class ImportsHomeCards extends ConsumerWidget {
  const ImportsHomeCards({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(importsProvider);
    final now = DateTime.now();
    final running = state.running;
    final finished = state.recentlyFinished(now);
    if (running.isEmpty && finished.isEmpty) return const SizedBox.shrink();
    return Column(
      children: [
        if (running.length > 1)
          _SeveralRunning(jobs: running)
        else
          for (final job in running) ImportCard(job: job, compact: true),
        for (final job in finished.take(2)) ImportCard(job: job, compact: true),
      ],
    );
  }
}

class _SeveralRunning extends StatelessWidget {
  const _SeveralRunning({required this.jobs});

  final List<ImportJob> jobs;

  @override
  Widget build(BuildContext context) {
    final done = jobs.fold<int>(0, (sum, j) => sum + j.done);
    final total = jobs.fold<int>(0, (sum, j) => sum + j.total);
    return InkWell(
      key: const Key('imports-several'),
      onTap: () => context.push('/settings/import'),
      child: Card(
        margin: const EdgeInsets.symmetric(
            horizontal: Space.gutter, vertical: Space.sm),
        child: Padding(
          padding: const EdgeInsets.all(Space.lg),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(children: [
                Icon(Icons.downloading_rounded, color: context.colors.accent),
                const SizedBox(width: Space.md),
                Expanded(
                  child: Text(
                      'Importing ${jobs.length} playlists: $done of '
                      '${plural(total, 'song')}',
                      style: context.text.titleSmall),
                ),
              ]),
              const SizedBox(height: Space.md),
              LinearProgressIndicator(
                  value: total == 0 ? null : (done / total).clamp(0.0, 1.0),
                  minHeight: 6),
            ],
          ),
        ),
      ),
    );
  }
}
