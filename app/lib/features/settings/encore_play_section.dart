import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/connection.dart' show serverReachableProvider;
import '../../app/providers.dart';
import '../../data/encore/encore_models.dart';
import '../../design/tokens.dart';
import '../providers.dart' show hasDownloadsProvider;
import 'settings_controller.dart';

/// What an Encore server says about itself right now (is it allowed to fetch new songs, or resting). `null` when it does not answer
/// (tests replace it).
final encoreServerInfoProvider =
    FutureProvider.autoDispose<EncoreInfo?>((ref) async {
  // Asked again whenever the server is lost or found, so "did not answer" does not outlive the outage (QA round 1, R1-2).
  ref.watch(serverReachableProvider);
  final session = await ref.watch(sessionProvider.future);
  if (session == null || !session.encoreMode) return null;
  await session.whenAddressKnown();
  return (await session.encore.info()).valueOrNull;
});

/// "Play any song" on an Encore server: the switch, and in plain words whether new songs can be fetched at the moment. Playing a song
/// does not save it; what a person likes or downloads is kept on the server.
class EncorePlaySection extends ConsumerWidget {
  const EncorePlaySection({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final enabled =
        ref.watch(settingsProvider.select((s) => s.instantPlayEnabled));
    final info = ref.watch(encoreServerInfoProvider);
    // With no internet the page's own header already says that downloaded songs play: said once.
    final hasDownloads =
        ref.watch(hasDownloadsProvider) && ref.watch(phoneOnlineProvider);
    final c = context.colors;

    Widget status() {
      if (!enabled) {
        return const ListTile(
          leading: Icon(Icons.pause_circle_outline_rounded),
          title: Text('Switched off'),
          subtitle: Text('Songs your server does not have only offer a '
              '30-second preview.'),
        );
      }
      return info.when(
        loading: () => const ListTile(
          leading: SizedBox.square(
              dimension: 24, child: CircularProgressIndicator(strokeWidth: 2)),
          title: Text('Asking your server...'),
        ),
        error: (_, __) => _unreachable(c, hasDownloads),
        data: (value) {
          if (value == null) return _unreachable(c, hasDownloads);
          if (value.youtubeState == 'resting') {
            return ListTile(
              leading: Icon(Icons.hourglass_bottom_rounded, color: c.onBgMuted),
              title: const Text('Taking a short rest'),
              subtitle: Text('The web asked your server to slow down. Songs it '
                  'already has play as usual; new ones wait '
                  '${restWords(value.youtubeResumesInSec)}.'),
            );
          }
          if (value.youtubeState == 'off') {
            return ListTile(
              leading: Icon(Icons.cloud_off_outlined, color: c.onBgMuted),
              title: const Text('Not available on this server'),
              subtitle: const Text('Your server plays what it already has. '
                  'Whoever looks after it can switch on songs from the web.'),
            );
          }
          return ListTile(
            leading: Icon(Icons.bolt_rounded, color: c.accent),
            title: const Text('Ready'),
            subtitle: const Text('Tap any song in search or on an artist page '
                'and it plays in seconds. Playing does not save it: songs you '
                'like or download are kept on your server.'),
          );
        },
      );
    }

    return Column(
      children: [
        SwitchListTile(
          secondary: const Icon(Icons.bolt_outlined),
          title: const Text('Play songs your server does not have'),
          subtitle: const Text('They are fetched from the web as you play '
              'them. Nothing new to set up on the phone.'),
          value: enabled,
          onChanged: ref.read(settingsProvider.notifier).setInstantPlayEnabled,
        ),
        status(),
      ],
    );
  }

  /// Without the server only what was downloaded plays, so that is all the line may promise, and only when something was downloaded.
  Widget _unreachable(EncoreColors c, bool hasDownloads) => ListTile(
        leading: Icon(Icons.cloud_off_outlined, color: c.onBgMuted),
        title: const Text('Your server did not answer'),
        subtitle:
            Text('${hasDownloads ? 'Songs you downloaded still play. ' : ''}'
                'Try again when you are connected to it.'),
      );
}

/// "about 5 minutes", "about 2 hours": how long a rest still lasts, never "0".
String restWords(int seconds) {
  final minutes = (seconds / 60).ceil().clamp(1, 1 << 30);
  if (minutes < 90) {
    return 'about ${minutes == 1 ? '1 minute' : '$minutes minutes'}';
  }
  final hours = (minutes / 60).round();
  return 'about $hours hours';
}
