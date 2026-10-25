import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/notifications.dart';
import '../../core/logger.dart';
import 'settings_controller.dart';
import 'settings_page.dart';

/// The three things the app may tell a person about, each a switch. Shown on its
/// own page where songs can be played at once, and inside "Get new music"
/// where a download service is the way to get music.
class NotificationSwitches extends ConsumerWidget {
  const NotificationSwitches({super.key});

  /// Android 13+ asks once; later calls are no-ops.
  static Future<void> _allow(WidgetRef ref) async {
    try {
      await ref.read(localNotificationsProvider).requestPermission();
    } on Object catch (error) {
      // Notifications are a convenience; the switch stays as chosen.
      Log.debug('notifications', 'asking for permission failed: $error');
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final settings = ref.watch(settingsProvider);
    final notifier = ref.read(settingsProvider.notifier);
    return Column(
      children: [
        SwitchListTile(
          title: const Text('New on your server'),
          subtitle: const Text(
              'An album by an artist you play reaches your server. Checked '
              'after each background sync - nothing is sent anywhere.'),
          value: settings.alertsOnServer,
          onChanged: (v) {
            notifier.setAlertsOnServer(v);
            if (v) unawaited(_allow(ref));
          },
        ),
        SwitchListTile(
          title: const Text('New releases you do not have'),
          subtitle: const Text(
              'Once a day the public music catalogue is asked what the '
              'artists you play most released lately, and you are told '
              'what your server lacks. Their names are sent to that '
              'catalogue, as in search.'),
          value: settings.alertsReleases,
          onChanged: (v) {
            notifier.setAlertsReleases(v);
            if (v) unawaited(_allow(ref));
          },
        ),
        SwitchListTile(
          title: const Text('Imports and requests'),
          subtitle: const Text(
              'Songs of an imported playlist have arrived, or it is complete.'),
          value: settings.alertsImports,
          onChanged: (v) {
            notifier.setAlertsImports(v);
            if (v) unawaited(_allow(ref));
          },
        ),
      ],
    );
  }
}

/// Settings > Notifications.
class NotificationsSettingsScreen extends StatelessWidget {
  const NotificationsSettingsScreen({super.key});

  @override
  Widget build(BuildContext context) => const SettingsPage(
        title: 'Notifications',
        description: 'Encore does not notify your phone unless you ask it to: '
            'everything on this page is off, and Android asks for its '
            'permission only when you switch one on. Nothing here is sent to '
            'anybody: the checks happen on your phone.',
        children: [NotificationSwitches()],
      );
}
