import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/repos/downloads_repository.dart';
import '../../design/tokens.dart';
import '../downloads/download_providers.dart';
import 'encore_sheet.dart';
import 'format.dart';

/// Spotify-style "Download" toggle for an album / playlist / liked songs.
///
/// States: outline arrow (off) -> progress ring (downloading) -> filled
/// accent circle (complete) -> warning (needs attention). Tapping an active
/// toggle asks before throwing the files away.
class DownloadButton extends ConsumerWidget {
  const DownloadButton({
    super.key,
    required this.type,
    required this.targetId,
    required this.name,
    this.size = 34,
  });

  final PinTargetType type;
  final String targetId;

  /// Human name for messages ("Downloading Prog Snob").
  final String name;
  final double size;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state =
        ref.watch(pinStateProvider((type, targetId))).value ?? PinState.none;
    final waiting = ref.watch(downloadsWaitProvider);
    final c = context.colors;

    final (IconData icon, Color fg, Color? fill, String label) =
        switch (state.phase) {
      PinPhase.off => (
          Icons.arrow_downward_rounded,
          c.onBgMuted,
          null,
          'Download $name',
        ),
      PinPhase.preparing || PinPhase.downloading => (
          Icons.arrow_downward_rounded,
          c.accent,
          null,
          waiting == null
              ? 'Downloading $name, ${(state.progress * 100).round()} percent'
              : '$waiting to download $name',
        ),
      PinPhase.complete => (
          Icons.arrow_downward_rounded,
          c.onAccent,
          c.accent,
          'Downloaded. Tap to remove $name from this phone',
        ),
      PinPhase.attention => (
          Icons.priority_high_rounded,
          c.onAccent,
          c.warning,
          'Some downloads failed. Tap for options',
        ),
    };

    final busy = state.phase == PinPhase.preparing ||
        state.phase == PinPhase.downloading;

    return Semantics(
      button: true,
      label: label,
      excludeSemantics: true,
      child: InkResponse(
        radius: size,
        onTap: () => _onTap(context, ref, state),
        child: SizedBox.square(
          dimension: 48,
          child: Center(
            child: SizedBox.square(
              dimension: size,
              child: Stack(
                alignment: Alignment.center,
                children: [
                  DecoratedBox(
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: fill,
                      border: fill == null
                          ? Border.all(
                              color: busy ? c.outline : c.onBgMuted,
                              width: 1.6,
                            )
                          : null,
                    ),
                    child: SizedBox.square(
                      dimension: size,
                      child: Icon(icon, size: size * 0.6, color: fg),
                    ),
                  ),
                  if (busy)
                    SizedBox.square(
                      dimension: size,
                      child: CircularProgressIndicator(
                        strokeWidth: 2.4,
                        // Indeterminate until the first file lands.
                        value: state.done == 0 ? null : state.progress,
                        color: c.accent,
                        backgroundColor: Colors.transparent,
                      ),
                    ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  Future<void> _onTap(
      BuildContext context, WidgetRef ref, PinState state) async {
    unawaited(HapticFeedback.selectionClick());
    final actions = ref.read(downloadActionsProvider);
    final messenger = ScaffoldMessenger.of(context);

    if (state.phase == PinPhase.off) {
      await actions.pin(type, targetId);
      messenger
        ..hideCurrentSnackBar()
        ..showSnackBar(SnackBar(
          content: Text('Downloading $name for offline listening'),
        ));
      return;
    }

    final remove = await showEncoreSheet<bool>(
      context: context,
      builder: (sheet) => _RemoveSheet(
          name: name, state: state, waiting: ref.read(downloadsWaitProvider)),
    );
    if (remove == true) {
      await actions.unpin(type, targetId);
      messenger
        ..hideCurrentSnackBar()
        ..showSnackBar(
            SnackBar(content: Text('Removed $name from this phone')));
    } else if (remove == false) {
      await actions.retry();
    }
  }
}

class _RemoveSheet extends StatelessWidget {
  const _RemoveSheet({required this.name, required this.state, this.waiting});

  final String name;
  final PinState state;

  /// Why nothing is moving ("Waiting for Wi-Fi"), when that is the case.
  final String? waiting;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final size = formatBytes(state.bytes);
    final title = switch (state.phase) {
      PinPhase.complete => 'Downloaded',
      PinPhase.attention => 'Some songs could not be downloaded',
      _ => waiting == null
          ? 'Downloading ${state.done} of ${state.total}'
          : '$waiting - ${state.done} of ${state.total}',
    };
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(
            Space.gutter, Space.lg, Space.gutter, Space.md),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(name,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: context.text.titleLarge),
            const SizedBox(height: Space.xs),
            Text(
              '$title - ${plural(state.total, 'song')}'
              '${state.bytes > 0 ? ', $size on this phone' : ''}',
              style: context.text.bodyMedium,
            ),
            const SizedBox(height: Space.lg),
            if (state.phase == PinPhase.attention)
              ListTile(
                leading: const Icon(Icons.refresh_rounded),
                title: const Text('Try again now'),
                onTap: () => Navigator.of(context).pop(false),
              ),
            ListTile(
              leading: Icon(Icons.delete_outline_rounded, color: c.danger),
              title: Text(
                state.phase == PinPhase.complete
                    ? 'Remove download'
                    : 'Stop and remove download',
                style: TextStyle(color: c.danger),
              ),
              onTap: () => Navigator.of(context).pop(true),
            ),
            ListTile(
              leading: const Icon(Icons.close_rounded),
              title: const Text('Keep downloaded'),
              onTap: () => Navigator.of(context).pop(),
            ),
          ],
        ),
      ),
    );
  }
}
