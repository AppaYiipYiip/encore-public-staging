import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../design/tokens.dart';
import '../../playback/queue_model.dart';
import '../common/cover_art.dart';
import '../common/format.dart';
import '../common/playlist_actions.dart';
import '../providers.dart';
import 'playback_facade.dart';

/// Streams the queue for the sheet (and anything else that wants it).
final queueSnapshotProvider = StreamProvider.autoDispose<QueueSnapshot>((ref) {
  final facade = ref.watch(playbackFacadeProvider);
  return Stream.multi((controller) {
    controller.add(facade.queue);
    final sub = facade.queueStream.listen(controller.add);
    controller.onCancel = sub.cancel;
  });
});

/// "Up next": what is playing, what comes next, drag to reorder, swipe to
/// remove (docs/06-ux-spec.md section 4.6).
Future<void> showQueueSheet(BuildContext context) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    showDragHandle: true,
    builder: (_) => const FractionallySizedBox(
      heightFactor: 0.9,
      child: _QueueSheet(),
    ),
  );
}

class _QueueSheet extends ConsumerWidget {
  const _QueueSheet();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final facade = ref.watch(playbackFacadeProvider);
    final queue = ref.watch(queueSnapshotProvider).value ?? facade.queue;
    final snapshot = ref.watch(playbackSnapshotProvider).value;
    final c = context.colors;

    final index = queue.currentIndex;
    final current =
        index >= 0 && index < queue.items.length ? queue.items[index] : null;
    final upNext = queue.upNext;
    final base = index + 1;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding:
              const EdgeInsets.fromLTRB(Space.gutter, 0, Space.sm, Space.sm),
          child: Row(
            children: [
              Expanded(
                child: Text('Queue', style: context.text.headlineSmall),
              ),
              if (queue.items.isNotEmpty)
                TextButton(
                  onPressed: () => unawaited(_saveAsPlaylist(
                    context,
                    [
                      for (final i in queue.items)
                        if (i.isLibraryTrack) i.id,
                    ],
                    snapshot?.sourceName,
                  )),
                  child: const Text('Save'),
                ),
              if (upNext.isNotEmpty)
                TextButton(
                  onPressed: () => unawaited(facade.clearUpNext()),
                  child: const Text('Clear'),
                ),
            ],
          ),
        ),
        if (current != null) ...[
          const _Label('Now playing'),
          _QueueRow(
            item: current,
            highlight: true,
            playing: snapshot?.isPlaying ?? false,
          ),
        ],
        _Label(upNext.isEmpty ? 'Nothing queued' : 'Next up'),
        if (upNext.isEmpty)
          Padding(
            padding: const EdgeInsets.all(Space.gutter),
            child: Text(
              'Add songs with the three-dot menu or swipe a song to the right.',
              style: context.text.bodyMedium?.copyWith(color: c.onBgMuted),
            ),
          )
        else
          Expanded(
            child: ReorderableListView.builder(
              buildDefaultDragHandles: false,
              padding: const EdgeInsets.only(bottom: Space.xxl),
              itemCount: upNext.length,
              onReorderItem: (oldIndex, newIndex) {
                HapticFeedback.selectionClick();
                unawaited(facade.moveInQueue(base + oldIndex, base + newIndex));
              },
              itemBuilder: (context, i) {
                final item = upNext[i];
                return Dismissible(
                  key: ValueKey('q-${item.uid}'),
                  direction: DismissDirection.endToStart,
                  background: Container(
                    color: c.danger,
                    alignment: Alignment.centerRight,
                    padding: const EdgeInsets.only(right: Space.xl),
                    child: const Icon(Icons.delete_outline_rounded,
                        color: Colors.white),
                  ),
                  onDismissed: (_) =>
                      unawaited(facade.removeFromQueue(base + i)),
                  child: _QueueRow(
                    item: item,
                    onTap: () => unawaited(facade.jumpToQueueIndex(base + i)),
                    handle: ReorderableDragStartListener(
                      index: i,
                      child: const Padding(
                        padding: EdgeInsets.all(Space.md),
                        child: Icon(Icons.drag_handle_rounded),
                      ),
                    ),
                  ),
                );
              },
            ),
          ),
      ],
    );
  }
}

/// "Save" in the queue sheet: the whole queue (previews excluded) becomes a
/// playlist, named after what was playing from.
Future<void> _saveAsPlaylist(
  BuildContext context,
  List<String> trackIds,
  String? sourceName,
) async {
  if (trackIds.isEmpty) return;
  await createPlaylistFlow(
    context,
    trackIds: trackIds,
    suggestedName: sourceName == null ? 'My queue' : '$sourceName (queue)',
  );
}

class _Label extends StatelessWidget {
  const _Label(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(
          Space.gutter, Space.md, Space.gutter, Space.xs),
      child: Text(text, style: context.text.titleSmall),
    );
  }
}

class _QueueRow extends StatelessWidget {
  const _QueueRow({
    required this.item,
    this.onTap,
    this.handle,
    this.highlight = false,
    this.playing = false,
  });

  final QueueItem item;
  final VoidCallback? onTap;
  final Widget? handle;
  final bool highlight;
  final bool playing;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final subtitle = [
      if (item.artist != null) item.artist!,
      if (item.duration != null) formatClock(item.duration!),
    ].join(' • ');
    return ListTile(
      onTap: onTap,
      leading: SizedBox.square(
        dimension: 48,
        child: CoverArt(
          coverArtId: item.coverArt,
          imageUrl: item.imageUrl,
          fallbackArtist: item.album == null ? null : item.artist,
          fallbackLabel: item.album ?? item.title,
        ),
      ),
      title: Text(
        item.title,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: context.text.bodyLarge?.copyWith(
          color: highlight ? c.accent : null,
          fontWeight: highlight ? FontWeight.w700 : null,
        ),
      ),
      subtitle: Text(subtitle, maxLines: 1, overflow: TextOverflow.ellipsis),
      trailing: handle ??
          (highlight
              ? Icon(
                  playing ? Icons.volume_up_rounded : Icons.volume_mute_rounded,
                  color: c.accent,
                )
              : null),
    );
  }
}
