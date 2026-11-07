import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../design/tokens.dart';
import '../common/encore_sheet.dart';
import '../requests/request_providers.dart';
import '../requests/request_ui.dart';
import '../settings/settings_controller.dart';

/// What the words on a release that is not in the library yet mean, in plain
/// language (ADR-067). Spotify never makes a person learn a vocabulary; this
/// is the one place that explains ours, in four short lines.
Future<void> showAddingMusicHelp(BuildContext context,
    {required bool instant}) {
  return showEncoreSheet<void>(
    context: context,
    builder: (_) => _AddingMusicHelp(instant: instant),
  );
}

class _AddingMusicHelp extends StatelessWidget {
  const _AddingMusicHelp({required this.instant});

  final bool instant;

  @override
  Widget build(BuildContext context) {
    final entries = instant
        ? const [
            (
              Icons.play_arrow_rounded,
              'Play',
              'Tap any song. If it is not in your library yet it is added '
                  'first - a few seconds - and then it plays.',
            ),
            (
              Icons.library_add_rounded,
              'Add to library',
              'Puts a whole album in your library without playing it. Your '
                  'library lives on your music server, so it is there on all '
                  'your devices.',
            ),
            (
              Icons.arrow_downward_rounded,
              'Download',
              'Keeps music on this phone so it plays without internet. '
                  'Download here does both: adds it to your library and keeps '
                  'it on the phone.',
            ),
            (
              Icons.high_quality_rounded,
              'Ask for better quality',
              'Songs added this way sound about as good as YouTube. Ask, and '
                  'your music server looks for the original full-quality '
                  'files. That can take days; until then you keep playing '
                  'what you have.',
            ),
          ]
        : const [
            (
              Icons.add_rounded,
              'Request',
              'Asks your music server to get the whole album. It can take '
                  'hours or days, and it shows up in your library by itself '
                  'when it arrives.',
            ),
          ];
    return SafeArea(
      child: Padding(
        padding:
            const EdgeInsets.fromLTRB(Space.gutter, 0, Space.gutter, Space.xl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('How adding music works', style: context.text.titleLarge),
            const SizedBox(height: Space.lg),
            for (final (icon, title, text) in entries)
              Padding(
                padding: const EdgeInsets.only(bottom: Space.lg),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Icon(icon, color: context.colors.accent),
                    const SizedBox(width: Space.md),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(title, style: context.text.titleSmall),
                          const SizedBox(height: 2),
                          Text(text, style: context.text.bodyMedium),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }
}

/// The "..." on a release page that is not in the library: the actions most
/// people never need (asking for the full-quality files) and the explanation,
/// kept off the main row so the page reads like any music app (ADR-067).
class CatalogueMoreMenu extends ConsumerWidget {
  const CatalogueMoreMenu({super.key, required this.artist, this.album});

  final String artist;
  final String? album;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Only for a person who connected a download service of their own (the
    // author's stack). A friend on somebody else's server has none and cannot
    // make one: the menu must not lead them to "Connect your download service".
    final canAsk =
        ref.watch(settingsProvider.select((s) => s.requestsEnabled)) &&
            ref.watch(requestBackendProvider).value != null;
    return PopupMenuButton<String>(
      tooltip: 'More options',
      icon: const Icon(Icons.more_vert_rounded),
      onSelected: (value) {
        switch (value) {
          case 'ask':
            unawaited(requestMusic(context, ref, artist: artist, album: album));
          case 'help':
            unawaited(showAddingMusicHelp(context, instant: true));
        }
      },
      itemBuilder: (_) => [
        if (canAsk)
          PopupMenuItem(
            value: 'ask',
            child: ListTile(
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.high_quality_rounded),
              title: const Text('Ask for better quality'),
              subtitle: const Text('The original files. Can take days.'),
            ),
          ),
        const PopupMenuItem(
          value: 'help',
          child: ListTile(
            contentPadding: EdgeInsets.zero,
            leading: Icon(Icons.help_outline_rounded),
            title: Text('How does this work?'),
          ),
        ),
      ],
    );
  }
}
