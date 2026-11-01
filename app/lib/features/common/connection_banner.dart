import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/connection.dart';
import '../../design/tokens.dart';
import '../providers.dart' show hasDownloadsProvider;

/// A slim strip above the player that says what is wrong with the connection,
/// when it has been wrong for a few seconds, and nothing otherwise: no internet
/// (downloaded music still plays), a server that does not answer, a Jam that is
/// listening again. "A widget to show you lost the internet" (owner,
/// 2026-10-17).
class ConnectionBanner extends ConsumerWidget {
  const ConnectionBanner({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final problem = ref.watch(connectionStripProvider);
    return AnimatedSize(
      duration: Motion.standard,
      curve: Motion.curve,
      alignment: Alignment.bottomCenter,
      child: problem == ConnectionProblem.none
          ? const SizedBox(width: double.infinity)
          : _Strip(problem: problem),
    );
  }
}

class _Strip extends ConsumerWidget {
  const _Strip({required this.problem});

  final ConnectionProblem problem;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.colors;
    final hasDownloads = ref.watch(hasDownloadsProvider);
    // No internet and a server that does not answer are one thing to the person (4G on, no data): one calm sentence. The details are on
    // Settings > Your server.
    final offline = hasDownloads
        ? 'You\'re offline. Downloaded music still plays.'
        : 'You\'re offline. Nothing can play until you reconnect.';
    final (icon, text) = switch (problem) {
      ConnectionProblem.offline => (Icons.cloud_off_rounded, offline),
      ConnectionProblem.serverUnreachable => (Icons.cloud_off_rounded, offline),
      ConnectionProblem.jamReconnecting => (
          Icons.groups_2_rounded,
          'Reconnecting to the Jam…'
        ),
      ConnectionProblem.none => (Icons.check, ''),
    };
    return Semantics(
      liveRegion: true,
      label: text,
      child: Material(
        color: c.surfaceHigh,
        child: Padding(
          padding: const EdgeInsets.symmetric(
              horizontal: Space.gutter, vertical: Space.sm),
          child: Row(
            children: [
              if (problem == ConnectionProblem.jamReconnecting)
                const SizedBox.square(
                  dimension: 16,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              else
                Icon(icon, size: 18, color: c.warning),
              const SizedBox(width: Space.md),
              Expanded(
                child: Text(text, style: context.text.bodySmall),
              ),
              if (problem != ConnectionProblem.jamReconnecting)
                IconButton(
                  tooltip: 'Dismiss',
                  visualDensity: VisualDensity.compact,
                  icon: const Icon(Icons.close_rounded, size: 18),
                  color: c.onBgMuted,
                  onPressed: () =>
                      ref.read(connectionStripProvider.notifier).dismiss(),
                ),
            ],
          ),
        ),
      ),
    );
  }
}
