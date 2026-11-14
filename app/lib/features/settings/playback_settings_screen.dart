import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/providers.dart';
import '../../domain/audio_quality.dart';
import '../../playback/replay_gain.dart';
import 'data_saver_line.dart';
import 'settings_controller.dart';
import 'settings_page.dart';

/// Playback preferences: sound quality per situation, volume levelling,
/// equaliser (ADR-036). Gapless is always on.
class PlaybackSettingsScreen extends ConsumerWidget {
  const PlaybackSettingsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(settingsProvider);
    final ctrl = ref.read(settingsProvider.notifier);
    final inForce = ref.watch(dataSaverInForceProvider);

    return SettingsPage(
      title: 'Playback',
      description:
          'Gapless playback is always on. Quality is applied by your server, '
          'so it costs the phone no battery.',
      children: [
        const SettingsSection('Streaming quality'),
        QualityTile(
          title: 'On Wi-Fi',
          value: s.streamQualityWifi,
          onChanged: ctrl.setStreamQualityWifi,
          subtitle: 'Original keeps FLAC as FLAC (largest, best).',
        ),
        QualityTile(
          title: 'On mobile data',
          value: s.streamQualityMobile,
          onChanged: ctrl.setStreamQualityMobile,
          // While Data saver is in force the row keeps the person's own choice and says what limits it (the choice is back when it goes off).
          subtitle: DataSaverWords.streamingRowLine(s, inForce: inForce),
          options: const [
            AudioQuality.original,
            AudioQuality.high,
            AudioQuality.normal,
            AudioQuality.dataSaver,
            AudioQuality.compatible,
          ],
        ),
        // One line under the two quality rows: both are about mobile data (P4-24).
        const DataSaverLine(),
        const SettingsSection('Sound'),
        ListTile(
          leading: const Icon(Icons.equalizer_rounded),
          title: const Text('Equalizer'),
          subtitle: const Text('Presets and 5-band control.'),
          trailing: const Icon(Icons.chevron_right_rounded),
          onTap: () => context.push('/settings/equalizer'),
        ),
        const ListTile(
          title: Text('Volume levelling'),
          subtitle: Text(
              'Makes loud and quiet songs play at a similar volume (ReplayGain).'),
        ),
        RadioGroup<ReplayGainMode>(
          groupValue: s.replayGainMode,
          onChanged: (v) {
            if (v != null) ctrl.setReplayGainMode(v);
          },
          child: Column(
            children: [
              for (final (mode, label, hint) in const [
                (ReplayGainMode.off, 'Off', 'Play as recorded'),
                (ReplayGainMode.track, 'Song', 'Level every song'),
                (ReplayGainMode.album, 'Album', "Keep an album's dynamics"),
              ])
                RadioListTile<ReplayGainMode>(
                  value: mode,
                  title: Text(label),
                  subtitle: Text(hint),
                ),
            ],
          ),
        ),
        if (s.replayGainMode != ReplayGainMode.off)
          SwitchListTile(
            title: const Text('Quiet places'),
            subtitle: const Text(
                'Also make quiet songs louder. Can sound harsh; the volume buttons on your phone are the usual way.'),
            value: s.replayGainBoost,
            onChanged: ctrl.setReplayGainBoost,
          ),
      ],
    );
  }
}
