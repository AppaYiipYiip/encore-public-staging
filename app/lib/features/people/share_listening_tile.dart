import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../settings/settings_controller.dart';
import 'people_providers.dart';

/// "Share what I'm listening to" (docs/35): friends on this server see the song
/// that is playing. Off until the person turns it on. Not shown when the
/// server has no people service. What it shows is what the server holds.
class ShareListeningTile extends ConsumerWidget {
  const ShareListeningTile({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final me = ref.watch(peopleProvider).value;
    if (me == null) return const SizedBox.shrink();
    final private =
        ref.watch(settingsProvider.select((s) => s.privateListening));
    return SwitchListTile(
      title: const Text("Share what I'm listening to"),
      subtitle: Text(private
          ? 'Private listening is on, so nothing is shared right now.'
          : 'The friends on this server see the song you are playing: its '
              'title, artist and album. Nothing else, and no history.'),
      value: me.sharing,
      onChanged: (on) async {
        final failure = await ref.read(peopleProvider.notifier).setSharing(on);
        if (failure == null || !context.mounted) return;
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(failure.message)));
      },
    );
  }
}
