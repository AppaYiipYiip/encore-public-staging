import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../design/tokens.dart';
import '../../domain/storage_guard.dart';
import '../common/format.dart';
import '../settings/settings_controller.dart';
import 'download_providers.dart';

/// Free space on the phone (refreshed when the screen is opened).
final freeSpaceProvider = FutureProvider.autoDispose<int?>((ref) async {
  return ref.watch(diskSpaceProvider)?.freeBytes();
});

/// Shown wherever downloads are listed while the queue is paused because the
/// storage cap is reached or the phone is nearly full. Silent when all is
/// well - the app never nags.
class DownloadsPausedBanner extends ConsumerWidget {
  const DownloadsPausedBanner({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final verdict =
        ref.watch(downloadVerdictProvider).value ?? StorageVerdict.ok;
    if (verdict == StorageVerdict.ok) return const SizedBox.shrink();

    final c = context.colors;
    final limit = ref.watch(
      settingsProvider.select((s) => s.downloadLimitBytes),
    );
    final message = switch (verdict) {
      StorageVerdict.limitReached => 'Downloads are paused: the storage limit'
          '${limit == null ? '' : ' of ${formatBytes(limit)}'} is reached. '
          'Raise it in Settings or remove something you no longer need.',
      StorageVerdict.lowSpace =>
        'Downloads are paused: your phone is almost full. Free some space '
            'and they continue by themselves.',
      StorageVerdict.ok => '',
    };
    return Semantics(
      liveRegion: true,
      child: Container(
        margin: const EdgeInsets.fromLTRB(
            Space.gutter, Space.sm, Space.gutter, Space.sm),
        padding: const EdgeInsets.all(Space.md),
        decoration: BoxDecoration(
          color: c.warning.withValues(alpha: 0.16),
          borderRadius: BorderRadius.circular(Radii.card),
          border: Border.all(color: c.warning.withValues(alpha: 0.5)),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(Icons.pause_circle_outline_rounded, color: c.warning),
            const SizedBox(width: Space.md),
            Expanded(child: Text(message, style: context.text.bodyMedium)),
          ],
        ),
      ),
    );
  }
}

/// The caps offered in Settings, in bytes (`null` = no cap).
const List<int?> kStorageLimitChoices = [
  null,
  2 * 1024 * 1024 * 1024,
  5 * 1024 * 1024 * 1024,
  10 * 1024 * 1024 * 1024,
  20 * 1024 * 1024 * 1024,
  50 * 1024 * 1024 * 1024,
];

String storageLimitLabel(int? bytes) =>
    bytes == null ? 'No limit' : formatBytes(bytes);
