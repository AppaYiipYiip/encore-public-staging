import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../people/share_listening_tile.dart';
import 'settings_controller.dart';
import 'settings_page.dart';

/// Home, library and privacy on a server that other people use too (ADR-049).
class HouseholdSettingsScreen extends ConsumerWidget {
  const HouseholdSettingsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final settings = ref.watch(settingsProvider);
    final notifier = ref.read(settingsProvider.notifier);
    final server = ref.watch(activeServerProvider).value;

    return SettingsPage(
      title: 'Privacy & your music',
      description:
          'One server can hold the music of a whole household. Everybody '
          'signs in with their own account so likes, history and playlists '
          'stay separate; these switches decide how much of everyone else '
          'you see.',
      children: [
        // "Only your music / the whole server" lives on the Library page, where it applies (AUDIT F41, D-27): one control, not two.
        const SettingsSection('Home'),
        SwitchListTile(
          title: const Text('Show "New on the server"'),
          subtitle: const Text(
              'What everybody added recently, at the bottom of Home. New '
              'releases from artists you play always show.'),
          value: settings.showNewOnServer,
          onChanged: notifier.setShowNewOnServer,
        ),
        const SettingsSection('Privacy'),
        SwitchListTile(
          title: const Text('Private listening'),
          subtitle: const Text(
              'Nothing you play is added to your history, counted as a play '
              'or shown as "now playing" to the others on the server.'),
          value: settings.privateListening,
          onChanged: notifier.setPrivateListening,
        ),
        const ShareListeningTile(),
        const SettingsSection('Account'),
        ListTile(
          leading: const Icon(Icons.person_outline_rounded),
          title: Text('Signed in as ${server?.username ?? '-'}'),
          subtitle: const Text(
              'Likes, ratings, play history and playlists belong to this '
              'account. If several people share one login they share all of '
              'that - ask whoever runs the server for your own account.'),
        ),
      ],
    );
  }
}
