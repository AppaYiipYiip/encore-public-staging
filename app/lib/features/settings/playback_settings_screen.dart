import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../design/tokens.dart';
import '../../domain/audio_quality.dart';
import '../../playback/replay_gain.dart';
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
          options: const [
            AudioQuality.original,
            AudioQuality.high,
            AudioQuality.normal,
            AudioQuality.dataSaver,
            AudioQuality.compatible,
          ],
        ),
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
          ListTile(
            title: const Text('Level boost'),
            subtitle: Slider(
              min: -6,
              max: 6,
              divisions: 12,
              value: s.replayGainPreampDb,
              label: '${s.replayGainPreampDb.round()} dB',
              onChanged: ctrl.setReplayGainPreamp,
            ),
            trailing: SizedBox(
              width: 56,
              child: Text(
                '${s.replayGainPreampDb >= 0 ? '+' : ''}'
                '${s.replayGainPreampDb.round()} dB',
                textAlign: TextAlign.end,
                style: context.text.labelLarge,
              ),
            ),
          ),
      ],
    );
  }
}
