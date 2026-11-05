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
    // No internet is "You're offline", and so is a network that Android itself found no internet on (a 4G radio with no data, a Wi-Fi with a sign-in
    // page): the person's own word for it (31 Oct: "it never says offline"). Only when the internet is there and the server does not answer is it
    // "Can't reach your server." (docs/31 CN-4b, D-45 amended 5 Nov 2026). Said once, like every outage; the details are on Settings > Your server.
    final internet = ref.watch(phoneHasInternetProvider).value ?? true;
    final offline = hasDownloads
        ? 'You\'re offline. Downloaded music still plays.'
        : 'You\'re offline. Nothing can play until you reconnect.';
    final another = ref.watch(anotherServerAtProvider).value;
    final (icon, text) = switch (problem) {
      ConnectionProblem.offline => (Icons.cloud_off_rounded, offline),
      ConnectionProblem.serverUnreachable => (
          Icons.cloud_off_rounded,
          internet ? "Can't reach your server." : offline,
        ),
      // A wrong key is not an outage and is not said as one (docs/31 O-6): the phone is online, and something that is not the server answers.
      ConnectionProblem.anotherServer => (
          Icons.gpp_maybe_rounded,
          another == null
              ? 'Another server answers at this address.'
              : 'Another server answers at ${another.host}.'
        ),
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
