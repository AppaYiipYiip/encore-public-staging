import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/background_sync.dart';
import '../../app/branding.dart';
import '../../app/providers.dart';
import '../../data/repos/downloads_repository.dart';
import '../../data/sync/sync_scheduler.dart';
import '../../design/tokens.dart';
import '../../domain/audio_quality.dart';
import '../common/format.dart';
import '../downloads/download_providers.dart';
import '../downloads/storage_widgets.dart';
import '../instant/instant_controller.dart' show instantAvailableProvider;
import 'diagnostics_screen.dart';
import 'failed_edits.dart';
import 'settings_controller.dart';
import 'settings_page.dart';
import 'shrink_notice.dart';
import 'sign_out.dart';

/// Settings v2 (R-10, docs/06-ux-spec.md 4.9): searchable, <= 9 groups, plain
/// language, every row has a one-line description.
class SettingsScreen extends ConsumerStatefulWidget {
  const SettingsScreen({super.key});

  @override
  ConsumerState<SettingsScreen> createState() => _SettingsScreenState();
}

class _Group {
  const _Group(this.icon, this.title, this.subtitle, this.route, this.keywords);

  final IconData icon;
  final String title;
  final String subtitle;
  final String route;
  final String keywords;
}

class _SettingsScreenState extends ConsumerState<SettingsScreen> {
  String _filter = '';

  List<_Group> _groups(bool instant) => [
        ..._head,
        // Where a song can be played at once, "get new music" is the search;
        // the download service is only for a server that has one.
        if (instant)
          const _Group(
              Icons.notifications_none_rounded,
              'Notifications',
              'New music on your server, new releases',
              '/settings/notifications',
              'notifications alerts new releases arrived tell me notify')
        else
          const _Group(
              Icons.travel_explore_rounded,
              'Get new music',
              'Download service, requests, alerts',
              '/settings/requests',
              'request portal lidarr discover missing music artist album download service soulseek youtube fetch notifications alerts'),
        ..._tail,
      ];

  static const _head = [
    _Group(
        Icons.play_circle_outline_rounded,
        'Playback',
        'Quality, equalizer, volume levelling',
        '/settings/playback',
        'gapless quality stream transcode flac opus replaygain normalise loudness volume equalizer eq sound bass'),
    _Group(
        Icons.download_for_offline_outlined,
        'Downloads & storage',
        'Wi-Fi only, quality, storage',
        '/settings/downloads',
        'download offline wifi cellular data storage cache space quality'),
    _Group(
        Icons.sync_rounded,
        'Library & sync',
        'Update now, fix a library that looks wrong',
        '/settings/sync',
        'sync refresh update library server rebuild pending queue'),
    _Group(
        Icons.groups_outlined,
        'Privacy & your music',
        'Private listening, what Home and Library show',
        '/settings/home',
        'household family shared server private listening privacy library home scope everyone account scrobble history new on the server mine everything'),
    _Group(
        Icons.move_to_inbox_rounded,
        'Import music',
        'Spotify and YouTube Music playlists and artists',
        '/settings/import',
        'import spotify youtube music playlist artist link share transfer move migrate bring'),
  ];

  static const _tail = [
    _Group(Icons.lyrics_outlined, 'Lyrics', 'Size, keep screen on',
        '/settings/lyrics', 'lyrics text size font screen awake wakelock'),
    _Group(Icons.palette_outlined, 'Appearance', 'Theme, black background',
        '/settings/appearance', 'theme dark light amoled black colour color'),
    _Group(
        Icons.info_outline_rounded,
        'About & credits',
        'Version, credits, diagnostics',
        '/settings/about',
        'about credits licence license open source version diagnostics log'),
  ];

  @override
  Widget build(BuildContext context) {
    final server = ref.watch(activeServerProvider).value;
    final session = ref.watch(sessionProvider).value;
    final sync = ref.watch(syncStatusProvider).value ?? const SyncStatus();
    final f = _filter.trim().toLowerCase();
    final all = _groups(ref.watch(instantAvailableProvider));
    final groups = f.isEmpty
        ? all
        : all
            .where((g) =>
                g.title.toLowerCase().contains(f) ||
                g.subtitle.toLowerCase().contains(f) ||
                g.keywords.contains(f))
            .toList();

    return Scaffold(
      appBar: AppBar(title: const Text('Settings')),
      body: ListView(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(
                Space.gutter, Space.sm, Space.gutter, Space.md),
            child: TextField(
              onChanged: (v) => setState(() => _filter = v),
              decoration: InputDecoration(
                hintText: 'Search settings',
                prefixIcon: const Icon(Icons.search_rounded),
                filled: true,
                fillColor: context.colors.surfaceHigh,
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(Radii.card),
                  borderSide: BorderSide.none,
                ),
                contentPadding: const EdgeInsets.symmetric(vertical: 12),
              ),
            ),
          ),
          if (server != null && f.isEmpty)
            _ProfileCard(
              name: server.name,
              username: server.username,
              endpointLabel: session?.endpoints.current.label,
              reachable: session?.endpoints.isReachable ?? false,
              lastSync: sync.lastSuccessAt,
              syncing: sync.isSyncing,
            ),
          for (final g in groups)
            ListTile(
              leading: Icon(g.icon),
              title: Text(g.title, style: context.text.titleMedium),
              subtitle: Text(g.subtitle),
              trailing: const Icon(Icons.chevron_right_rounded),
              onTap: () => context.push(g.route),
            ),
          if (groups.isEmpty)
            Padding(
              padding: const EdgeInsets.all(Space.xxl),
              child: Center(
                child: Text('No settings match "$_filter"',
                    style: context.text.bodyMedium),
              ),
            ),
          if (server != null && f.isEmpty)
            ListTile(
              key: const Key('switch-user'),
              leading: const Icon(Icons.switch_account_rounded),
              title: Text('Switch user', style: context.text.titleMedium),
              subtitle: const Text('Somebody else listens on this device.'),
              trailing: const Icon(Icons.chevron_right_rounded),
              onTap: () => context.push('/profiles'),
            ),
          if (server != null && f.isEmpty)
            ListTile(
              leading: const Icon(Icons.logout_rounded),
              title: Text('Sign out', style: context.text.titleMedium),
              subtitle: Text('Signed in as ${server.username}'),
              onTap: () => unawaited(confirmAndSignOut(context, ref)),
            ),
        ],
      ),
    );
  }
}

class _ProfileCard extends ConsumerWidget {
  const _ProfileCard({
    required this.name,
    required this.username,
    required this.endpointLabel,
    required this.reachable,
    required this.lastSync,
    required this.syncing,
  });

  final String name;
  final String username;
  final String? endpointLabel;
  final bool reachable;
  final DateTime? lastSync;
  final bool syncing;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.colors;
    final now = ref.watch(clockProvider).now();
    final status = syncing
        ? 'Syncing…'
        : lastSync == null
            ? 'Not synced yet'
            : 'Synced ${_ago(now, lastSync!)}';
    final conn = reachable ? (endpointLabel ?? 'Connected') : 'Not connected';
    return Padding(
      padding:
          const EdgeInsets.fromLTRB(Space.gutter, 0, Space.gutter, Space.md),
      child: Material(
        color: c.surface,
        borderRadius: BorderRadius.circular(Radii.card),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: () => context.push('/settings/server'),
          child: Padding(
            padding: const EdgeInsets.all(Space.lg),
            child: Row(
              children: [
                CircleAvatar(
                  radius: 24,
                  backgroundColor: c.accent,
                  child: Text(username.characters.first.toUpperCase(),
                      style: context.text.titleMedium
                          ?.copyWith(color: c.onAccent)),
                ),
                const SizedBox(width: Space.lg),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(name, style: context.text.titleMedium),
                      Text('$username • $conn', style: context.text.bodyMedium),
                      Text(status, style: context.text.bodySmall),
                    ],
                  ),
                ),
                const Icon(Icons.chevron_right_rounded),
              ],
            ),
          ),
        ),
      ),
    );
  }

  static String _ago(DateTime now, DateTime t) {
    final d = now.difference(t);
    if (d.inSeconds < 60) return 'just now';
    if (d.inMinutes < 60) return '${d.inMinutes} min ago';
    if (d.inHours < 24) return '${d.inHours} h ago';
    return '${d.inDays} d ago';
  }
}

// ---------------------------------------------------------------- sub pages

class _Page extends StatelessWidget {
  const _Page({required this.title, this.description, required this.children});

  final String title;
  final String? description;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(title)),
      body: ListView(
        children: [
          if (description != null)
            Padding(
              padding: const EdgeInsets.fromLTRB(
                  Space.gutter, Space.sm, Space.gutter, Space.md),
              child: Text(description!, style: context.text.bodyMedium),
            ),
          ...children,
          const SizedBox(height: Space.xxl),
        ],
      ),
    );
  }
}

class AppearanceSettingsScreen extends ConsumerWidget {
  const AppearanceSettingsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(settingsProvider);
    final ctrl = ref.read(settingsProvider.notifier);
    return _Page(
      title: 'Appearance',
      description: 'How the app looks. Colours adapt to the music playing.',
      children: [
        RadioGroup<ThemeMode>(
          groupValue: s.themeMode,
          onChanged: (v) {
            if (v != null) ctrl.setThemeMode(v);
          },
          child: Column(
            children: [
              for (final (mode, label) in const [
                (ThemeMode.dark, 'Dark'),
                (ThemeMode.light, 'Light'),
                (ThemeMode.system, 'Follow system'),
              ])
                RadioListTile<ThemeMode>(
                  value: mode,
                  title: Text(label),
                ),
            ],
          ),
        ),
        const Divider(),
        SwitchListTile(
          title: const Text('True black background'),
          subtitle: const Text('Saves battery on OLED screens (dark theme).'),
          value: s.amoledBlack,
          onChanged: ctrl.setAmoled,
        ),
      ],
    );
  }
}

class LyricsSettingsScreen extends ConsumerWidget {
  const LyricsSettingsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(settingsProvider);
    final ctrl = ref.read(settingsProvider.notifier);
    return _Page(
      title: 'Lyrics',
      description: 'Lyrics come from your server first, then LRCLIB.',
      children: [
        ListTile(
          title: const Text('Text size'),
          subtitle: Slider(
            min: 0.8,
            max: 1.6,
            divisions: 8,
            value: s.lyricsTextScale,
            label: '${(s.lyricsTextScale * 100).round()}%',
            onChanged: ctrl.setLyricsTextScale,
          ),
          trailing: Text('${(s.lyricsTextScale * 100).round()}%'),
        ),
        SwitchListTile(
          title: const Text('Keep screen on'),
          subtitle: const Text('While the lyrics screen is open.'),
          value: s.keepScreenOnInLyrics,
          onChanged: ctrl.setKeepScreenOnInLyrics,
        ),
      ],
    );
  }
}

class SyncSettingsScreen extends ConsumerWidget {
  const SyncSettingsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final status = ref.watch(syncStatusProvider).value ?? const SyncStatus();
    final session = ref.watch(sessionProvider).value;
    final tracks = ref.watch(_trackCountForSettings).value ?? 0;
    return _Page(
      title: 'Library & sync',
      description:
          'Your library is kept up to date in the background. Nothing here needs '
          'your attention unless something looks wrong.',
      children: [
        const FailedEditsSection(),
        const ShrinkNoticeSection(),
        ListTile(
          title: const Text('Songs on this device'),
          trailing: Text('$tracks'),
        ),
        ListTile(
          title: const Text('Last sync'),
          subtitle: Text(
            status.isSyncing
                ? 'Syncing…'
                : status.lastSuccessAt == null
                    ? 'Not yet'
                    : status.lastSuccessAt!
                        .toLocal()
                        .toString()
                        .split('.')
                        .first,
          ),
        ),
        if (status.lastFailure != null)
          ListTile(
            leading:
                Icon(Icons.info_outline_rounded, color: context.colors.warning),
            title: const Text('Last attempt did not finish'),
            subtitle: Text(status.lastFailure!.message),
          ),
        ListTile(
          leading: const Icon(Icons.schedule_rounded),
          title: const Text('Sync while the app is closed'),
          subtitle: Text(
            '${backgroundSyncLabel(ref.watch(settingsProvider).backgroundSyncHours)}'
            ' - only on a network, never on a low battery.',
          ),
          onTap: () async {
            final current = ref.read(settingsProvider).backgroundSyncHours;
            final choice = await showDialog<int>(
              context: context,
              builder: (_) => SimpleDialog(
                title: const Text('Sync while the app is closed'),
                children: [
                  for (final h in kBackgroundSyncHourChoices)
                    ListTile(
                      title: Text(backgroundSyncLabel(h)),
                      trailing: h == current
                          ? Icon(Icons.check_rounded,
                              color: context.colors.accent)
                          : null,
                      onTap: () => Navigator.of(context).pop(h),
                    ),
                ],
              ),
            );
            if (choice != null) {
              ref
                  .read(settingsProvider.notifier)
                  .setBackgroundSyncHours(choice);
            }
          },
        ),
        ListTile(
          leading: const Icon(Icons.sync_rounded),
          title: const Text('Sync now'),
          subtitle: const Text('Check the server for changes.'),
          enabled: session != null && !status.isSyncing,
          onTap: () => session?.scheduler.requestSync(force: false),
        ),
        ListTile(
          leading: const Icon(Icons.build_circle_outlined),
          title: const Text('Rebuild library'),
          subtitle: const Text(
              'Re-read everything from the server. Use if something looks off.'),
          enabled: session != null && !status.isSyncing,
          onTap: () => session?.scheduler.requestSync(force: true),
        ),
      ],
    );
  }
}

final _trackCountForSettings = StreamProvider.autoDispose<int>((ref) {
  final repo = ref.watch(libraryRepositoryProvider);
  return repo?.watchTrackCount() ?? const Stream.empty();
});

class PlaceholderSettingsScreen extends StatelessWidget {
  const PlaceholderSettingsScreen(
      {super.key, required this.title, required this.note});

  final String title;
  final String note;

  @override
  Widget build(BuildContext context) =>
      _Page(title: title, description: note, children: const []);
}

class DownloadsSettingsScreen extends ConsumerWidget {
  const DownloadsSettingsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(settingsProvider);
    final ctrl = ref.read(settingsProvider.notifier);
    final storage = ref.watch(storageSummaryProvider).value;
    final entries = ref.watch(pinEntriesProvider).value ?? const [];
    final actions = ref.read(downloadActionsProvider);
    final free = ref.watch(freeSpaceProvider).value;

    return SettingsPage(
      title: 'Downloads & storage',
      description:
          'Download playlists and albums to listen without a connection. '
          'Changes on your server reach the downloaded copies by themselves.',
      children: [
        const SettingsSection('Download quality'),
        QualityTile(
          title: 'Quality',
          value: s.downloadQuality,
          onChanged: ctrl.setDownloadQuality,
          subtitle: 'Applies to new downloads. ${s.downloadQuality.detail}',
        ),
        SwitchListTile(
          title: const Text('Download over Wi-Fi only'),
          subtitle: const Text('Avoid using mobile data for downloads.'),
          value: s.wifiOnlyDownloads,
          onChanged: ctrl.setWifiOnlyDownloads,
        ),
        const SettingsSection('On this phone'),
        const DownloadsPausedBanner(),
        ListTile(
          leading: const Icon(Icons.sd_storage_outlined),
          title: Text(storage == null || storage.tracks == 0
              ? 'No downloads yet'
              : '${plural(storage.tracks, 'song')} downloaded'),
          subtitle: Text([
            if (storage != null && storage.bytes > 0)
              formatBytes(storage.bytes),
            if (free != null) '${formatBytes(free)} free on the phone',
          ].join(' • ')),
        ),
        ListTile(
          leading: const Icon(Icons.data_usage_rounded),
          title: const Text('Storage limit'),
          subtitle: Text(
            '${storageLimitLabel(s.downloadLimitBytes)} - downloads pause '
            'when it is reached.',
          ),
          onTap: () async {
            final choice = await showDialog<_LimitChoice>(
              context: context,
              builder: (_) =>
                  _StorageLimitDialog(current: s.downloadLimitBytes),
            );
            if (choice != null) ctrl.setDownloadLimitBytes(choice.bytes);
          },
        ),
        for (final e in entries)
          ListTile(
            leading: const Icon(Icons.arrow_downward_rounded),
            title: Text(e.title, maxLines: 1, overflow: TextOverflow.ellipsis),
            subtitle:
                Text('${e.kind} • ${AudioQuality.byId(e.pin.quality).label}'),
            trailing: IconButton(
              tooltip: 'Remove download',
              icon: const Icon(Icons.delete_outline_rounded),
              onPressed: () async {
                final type = PinTargetType.values.asNameMap()[e.pin.targetType];
                if (type == null) return;
                await actions.unpin(type, e.pin.targetId);
              },
            ),
          ),
        if (entries.isNotEmpty)
          Padding(
            padding: const EdgeInsets.all(Space.gutter),
            child: Align(
              alignment: Alignment.centerLeft,
              child: TextButton.icon(
                onPressed: () async {
                  // Asks first: this removes every song kept for offline use.
                  final sure = await showDialog<bool>(
                    context: context,
                    builder: (dialog) => AlertDialog(
                      title: const Text('Remove all downloads?'),
                      content: Text(
                        '${entries.length} ${entries.length == 1 ? 'download' : 'downloads'} '
                        'will be removed from this phone. Your music stays on '
                        'your server and you can download it again.',
                      ),
                      actions: [
                        TextButton(
                          onPressed: () => Navigator.of(dialog).pop(false),
                          child: const Text('Cancel'),
                        ),
                        FilledButton(
                          onPressed: () => Navigator.of(dialog).pop(true),
                          child: const Text('Remove'),
                        ),
                      ],
                    ),
                  );
                  if (sure != true) return;
                  for (final e in entries) {
                    final type =
                        PinTargetType.values.asNameMap()[e.pin.targetType];
                    if (type != null) {
                      await actions.unpin(type, e.pin.targetId);
                    }
                  }
                },
                icon: const Icon(Icons.delete_sweep_outlined),
                label: const Text('Remove all downloads'),
              ),
            ),
          ),
      ],
    );
  }
}

/// Wrapper so "No limit" (a `null` byte count) can be told apart from a
/// dismissed dialog.
class _LimitChoice {
  const _LimitChoice(this.bytes);

  final int? bytes;
}

class _StorageLimitDialog extends StatelessWidget {
  const _StorageLimitDialog({required this.current});

  final int? current;

  @override
  Widget build(BuildContext context) {
    return SimpleDialog(
      title: const Text('Storage limit'),
      children: [
        for (final bytes in kStorageLimitChoices)
          ListTile(
            title: Text(storageLimitLabel(bytes)),
            trailing: bytes == current
                ? Icon(Icons.check_rounded, color: context.colors.accent)
                : null,
            onTap: () => Navigator.of(context).pop(_LimitChoice(bytes)),
          ),
      ],
    );
  }
}

class AboutSettingsScreen extends StatelessWidget {
  const AboutSettingsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return _Page(
      title: 'About & credits',
      children: [
        ListTile(
          title: Text(AppBranding.name),
          subtitle: Text('Version ${AppBranding.version}'),
        ),
        ListTile(
          leading: const Icon(Icons.favorite_outline_rounded),
          title: const Text('Open-source licences'),
          subtitle: const Text('The free software Encore is built with.'),
          onTap: () => showLicensePage(
            context: context,
            applicationName: AppBranding.name,
            applicationVersion: AppBranding.version,
          ),
        ),
        ListTile(
          leading: const Icon(Icons.article_outlined),
          title: const Text('Diagnostics'),
          subtitle: const Text('Recent app activity (no passwords).'),
          onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(
              builder: (_) => const DiagnosticsScreen())),
        ),
      ],
    );
  }
}

String settingsFormatStorage(int bytes) => formatBytes(bytes);
