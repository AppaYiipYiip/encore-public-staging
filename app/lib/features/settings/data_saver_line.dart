import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../design/tokens.dart';
import '../../domain/audio_quality.dart';
import 'settings_controller.dart';

/// What the Data saver line says (P4-24, drawn in docs/design S-72). Pure, so the plain words are tested and the Playback page and the
/// Downloads page cannot say different things about the same cap.
abstract final class DataSaverWords {
  /// "Opus 48 kbps": the level every capped stream and download is held to.
  static String get cap => 'Opus ${AudioQuality.dataSaver.bitRate} kbps';

  /// A quality the cap cannot lower although it is above Data saver: Compatible, whose format (MP3) has no lower level. The cap never changes
  /// the codec, so it is left as it is, and the line says so.
  static bool keeps(AudioQuality q) =>
      q.rank > AudioQuality.dataSaver.rank && !q.isLoweredByDataSaver;

  /// Whether the cap holds the downloads on mobile data at all: only when the person allowed downloads there. With "Download over Wi-Fi only"
  /// on (the default) nothing downloads on mobile data, so there is nothing to cap and nothing to say about it.
  static bool _downloadsOnMobile(AppSettings s) => !s.wifiOnlyDownloads;

  static bool _keepsSomething(AppSettings s) =>
      keeps(s.streamQualityMobile) ||
      (_downloadsOnMobile(s) && keeps(s.downloadQuality));

  static const _kept =
      'Compatible quality stays as it is: its format cannot go lower.';

  /// The line under the switch's title.
  static String subtitle(AppSettings s) =>
      'Uses less mobile data: lower quality, smaller pictures, less loaded ahead. Never on Wi-Fi.'
      '${_keepsSomething(s) ? ' $_kept' : ''}';

  /// The second line of the "On mobile data" streaming row while the cap is in force, or `null` (the row says what it always says).
  static String? streamingRowLine(AppSettings s, {required bool inForce}) =>
      inForce && s.streamQualityMobile.isLoweredByDataSaver
          ? 'Data saver is limiting this to $cap right now.'
          : null;

  /// The second line of the download "Quality" row while the cap is in force, or `null`.
  static String? downloadRowLine(AppSettings s, {required bool inForce}) =>
      inForce && _downloadsOnMobile(s) && s.downloadQuality.isLoweredByDataSaver
          ? 'Applies to new downloads. Data saver is limiting them to $cap while you are on mobile data.'
          : null;

  /// The note under the switch: nothing while it is off; a grey "only used on mobile data" while the phone is not on mobile data (Wi-Fi,
  /// Ethernet and offline all say the same, because nothing is limited on any of them); what is happening while it is in force.
  static ({String title, String detail, bool active})? note(
    AppSettings s, {
    required NetworkKind network,
  }) {
    if (!s.dataSaver) return null;
    if (network != NetworkKind.mobile) {
      return (
        title: 'Only used on mobile data.',
        detail: "You're not on mobile data, so nothing is limited now.",
        active: false,
      );
    }
    final streams = s.streamQualityMobile.isLoweredByDataSaver;
    final downloads =
        _downloadsOnMobile(s) && s.downloadQuality.isLoweredByDataSaver;
    final quality = streams && downloads
        ? 'Music streams and downloads at $cap'
        : streams
            ? 'Music streams at $cap'
            : downloads
                ? 'New downloads are made at $cap'
                : null;
    const smaller = 'pictures are small';
    const ahead = 'only the next song is loaded ahead';
    final sentence = quality == null
        ? 'Pictures are small and $ahead.'
        : '$quality, $smaller, and $ahead.';
    return (
      title: 'Data saver is working.',
      detail: '$sentence${_keepsSomething(s) ? ' $_kept' : ''}',
      active: true,
    );
  }
}

/// The Data saver switch and its note, one line under the two streaming-quality rows on Playback. Not shown where the platform cannot say that
/// the phone is on mobile data (a browser): a switch that can never do anything is not offered.
class DataSaverLine extends ConsumerWidget {
  const DataSaverLine({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (!ref.watch(mobileDataReportableProvider)) {
      return const SizedBox.shrink();
    }
    final s = ref.watch(settingsProvider);
    final network = ref.watch(networkKindProvider).value ?? NetworkKind.wifi;
    final note = DataSaverWords.note(s, network: network);
    final c = context.colors;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SwitchListTile(
          key: const Key('data-saver-switch'),
          title: const Text('Data saver'),
          subtitle: Text(DataSaverWords.subtitle(s)),
          value: s.dataSaver,
          onChanged: ref.read(settingsProvider.notifier).setDataSaver,
        ),
        if (note != null)
          Semantics(
            liveRegion: true,
            child: Container(
              key: const Key('data-saver-note'),
              margin: const EdgeInsets.fromLTRB(
                  Space.gutter, Space.xs, Space.gutter, Space.sm),
              padding: const EdgeInsets.all(Space.md),
              decoration: BoxDecoration(
                color: note.active
                    ? c.accent.withValues(alpha: 0.13)
                    : c.surfaceHigh,
                borderRadius: BorderRadius.circular(Radii.card),
                border: Border.all(
                    color: note.active
                        ? c.accent.withValues(alpha: 0.5)
                        : c.outline),
              ),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(
                    note.active
                        ? Icons.check_circle_outline_rounded
                        : Icons.wifi_rounded,
                    color: note.active ? c.accent : c.onBgMuted,
                  ),
                  const SizedBox(width: Space.md),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(note.title, style: context.text.titleSmall),
                        const SizedBox(height: Space.xs),
                        Text(note.detail, style: context.text.bodyMedium),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
      ],
    );
  }
}
