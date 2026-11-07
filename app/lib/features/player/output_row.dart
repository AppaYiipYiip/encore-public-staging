import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/audio_output.dart';
import '../../design/tokens.dart';
import '../common/encore_sheet.dart';

/// The icon of an output: the speaker of the phone, a wired headset, a Bluetooth device.
IconData audioOutputIcon(AudioOutputKind kind) => switch (kind) {
      AudioOutputKind.speaker => Icons.speaker_phone_outlined,
      AudioOutputKind.wired => Icons.headphones_rounded,
      AudioOutputKind.bluetooth => Icons.bluetooth_audio_rounded,
      AudioOutputKind.other => Icons.speaker_group_outlined,
    };

/// Spotify's row on the left of the player's last line: a small speaker and the name of where the sound goes, in the accent colour. A tap opens
/// Encore's own Devices sheet (D-66, P1-25), never Android's chooser directly (D-28: that one moves every app's sound).
class OutputChip extends ConsumerWidget {
  const OutputChip({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final info =
        ref.watch(audioOutputProvider).value ?? AudioOutputInfo.thisPhone;
    final c = context.colors;
    return Semantics(
      button: true,
      label: 'Sound plays on ${info.name}. Choose where to play',
      excludeSemantics: true,
      child: InkWell(
        borderRadius: BorderRadius.circular(Radii.card),
        onTap: () => unawaited(showDevicesSheet(context)),
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: 48),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: Space.xs),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(audioOutputIcon(info.kind), size: 20, color: c.accent),
                const SizedBox(width: Space.sm),
                Flexible(
                  child: Text(
                    info.name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: context.text.labelLarge?.copyWith(color: c.accent),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

Future<void> showDevicesSheet(BuildContext context) => showEncoreSheet<void>(
      context: context,
      builder: (_) => const DevicesSheet(),
    );

/// Encore's own Devices sheet (D-66). Section "This phone": where the sound goes now and a way to change it. Section "Your other devices"
/// (another phone on the account, a browser: Play here / Play there) is P4-07 and joins this same sheet; until then it says so in one line.
class DevicesSheet extends ConsumerWidget {
  const DevicesSheet({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final info =
        ref.watch(audioOutputProvider).value ?? AudioOutputInfo.thisPhone;
    final c = context.colors;
    return SafeArea(
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(
                  Space.gutter, Space.lg, Space.gutter, Space.sm),
              child: Text('Play on', style: context.text.titleLarge),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(
                  Space.gutter, Space.sm, Space.gutter, Space.xs),
              child: Text('THIS PHONE',
                  style: context.text.labelSmall?.copyWith(color: c.onBgMuted)),
            ),
            ListTile(
              key: const Key('devices-current'),
              leading: Icon(audioOutputIcon(info.kind), color: c.accent),
              title: Text(info.name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(color: c.accent)),
              subtitle: const Text('The sound is playing here'),
              trailing: Icon(Icons.check_rounded, color: c.accent),
            ),
            ListTile(
              key: const Key('devices-switcher'),
              leading: const Icon(Icons.swap_horiz_rounded),
              title: const Text('Choose another sound output'),
              subtitle: const Text(
                  'Opens Android\'s own list (speaker, headphones, Bluetooth). It changes the sound of the whole phone, not only Encore.'),
              onTap: () async {
                final messenger = ScaffoldMessenger.maybeOf(context);
                final shown =
                    await ref.read(audioOutputServiceProvider).showSwitcher();
                if (shown || !context.mounted) return;
                messenger?.showSnackBar(const SnackBar(
                    content: Text(
                        'This phone cannot open its list from here. Use the sound controls in Android\'s quick settings.')));
              },
            ),
            const Divider(height: Space.xl),
            Padding(
              padding: const EdgeInsets.fromLTRB(
                  Space.gutter, 0, Space.gutter, Space.xs),
              child: Text('YOUR OTHER DEVICES',
                  style: context.text.labelSmall?.copyWith(color: c.onBgMuted)),
            ),
            ListTile(
              key: const Key('devices-others'),
              enabled: false,
              leading: Icon(Icons.devices_other_outlined, color: c.onBgMuted),
              title: const Text('Another phone or a browser'),
              subtitle: const Text(
                  'Playing on your other devices from here is not built yet.'),
            ),
            const SizedBox(height: Space.md),
          ],
        ),
      ),
    );
  }
}
