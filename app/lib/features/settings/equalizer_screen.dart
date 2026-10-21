import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/playback_providers.dart';
import '../../design/tokens.dart';
import '../../domain/eq_presets.dart';
import '../../playback/equalizer_service.dart';
import 'settings_page.dart';

final equalizerStateProvider = StreamProvider<EqualizerState>((ref) async* {
  final service = ref.watch(equalizerServiceProvider);
  yield service.state;
  yield* service.changes;
});

class EqualizerScreen extends ConsumerWidget {
  const EqualizerScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final service = ref.watch(equalizerServiceProvider);
    final state = ref.watch(equalizerStateProvider).value ?? service.state;
    final c = context.colors;

    if (!state.available) {
      return const SettingsPage(
        title: 'Equalizer',
        description:
            'The equalizer becomes available once music has started playing '
            'on this device.',
        children: [],
      );
    }

    return SettingsPage(
      title: 'Equalizer',
      description: 'Shape the sound. Changes apply to everything you play.',
      children: [
        SwitchListTile(
          title: const Text('Equalizer'),
          value: state.enabled,
          onChanged: service.setEnabled,
        ),
        const SettingsSection('Presets'),
        SizedBox(
          height: 52,
          child: ListView.separated(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: Space.gutter),
            itemCount: EqPreset.all.length,
            separatorBuilder: (_, __) => const SizedBox(width: Space.sm),
            itemBuilder: (context, i) {
              final p = EqPreset.all[i];
              return ChoiceChip(
                label: Text(p.label),
                selected: state.presetId == p.id,
                onSelected: (_) => service.applyPreset(p),
              );
            },
          ),
        ),
        const SettingsSection('Bands'),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: Space.gutter),
          child: Opacity(
            opacity: state.enabled ? 1 : 0.5,
            child: SizedBox(
              height: 300,
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  for (var i = 0; i < state.gains.length; i++)
                    Expanded(
                      child: Column(
                        children: [
                          Text(
                            '${state.gains[i] >= 0 ? '+' : ''}'
                            '${state.gains[i].toStringAsFixed(0)}',
                            style: context.text.labelSmall,
                          ),
                          Expanded(
                            child: RotatedBox(
                              quarterTurns: 3,
                              child: SliderTheme(
                                data: SliderTheme.of(context).copyWith(
                                  trackHeight: 4,
                                  activeTrackColor: c.accent,
                                ),
                                child: Slider(
                                  min: state.minDb,
                                  max: state.maxDb,
                                  value: state.gains[i]
                                      .clamp(state.minDb, state.maxDb),
                                  onChanged: (v) => service.setBandGain(i, v),
                                ),
                              ),
                            ),
                          ),
                          Text(
                            formatHz(state.centresHz[i]),
                            style: context.text.labelSmall,
                          ),
                        ],
                      ),
                    ),
                ],
              ),
            ),
          ),
        ),
        Padding(
          padding: const EdgeInsets.all(Space.gutter),
          child: Align(
            alignment: Alignment.centerLeft,
            child: TextButton.icon(
              onPressed: service.reset,
              icon: const Icon(Icons.restart_alt_rounded),
              label: const Text('Reset to flat'),
            ),
          ),
        ),
      ],
    );
  }
}
