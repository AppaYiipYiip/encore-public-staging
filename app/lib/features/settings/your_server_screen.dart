import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../data/fetch/fetch_client.dart';
import '../../data/sync/sync_scheduler.dart';
import '../../design/tokens.dart';
import '../common/format.dart';
import '../instant/instant_controller.dart';
import '../providers.dart';
import '../requests/download_service_sheet.dart';
import '../requests/request_providers.dart';
import 'invite_someone.dart';
import 'server_addresses.dart';
import 'settings_controller.dart';
import 'settings_page.dart';

/// What the server can do for this app, in plain words (ADR-052, ADR-056).
///
/// A music server plays and syncs; getting *new* music is a different job,
/// done by a download service next to it. This page says which of those the
/// phone has found, so setup is never a guess and a missing piece is a calm
/// "not set up" instead of an error.
class YourServerScreen extends ConsumerWidget {
  const YourServerScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final server = ref.watch(activeServerProvider).value;
    final session = ref.watch(sessionProvider).value;
    final sync = ref.watch(syncStatusProvider).value ?? const SyncStatus();
    final tracks = ref.watch(trackCountProvider).value ?? 0;
    final settings = ref.watch(settingsProvider);
    final c = context.colors;

    final reachable = session?.endpoints.isReachable ?? false;
    final extensions = session?.client.extensions ?? const <String>{};
    final serverLyrics = extensions.contains('songLyrics');
    final serviceUrl = settings.requestPortalUrl;
    final connected = serviceUrl != null && serviceUrl.isNotEmpty;
    final instantReady = ref.watch(fetchServiceProvider).value != null;
    final now = ref.watch(clockProvider).now();
    final synced = sync.isSyncing
        ? 'syncing now'
        : (sync.lastSuccessAt == null
            ? 'not synced yet'
            : 'synced ${_ago(now, sync.lastSuccessAt!)}');

    return SettingsPage(
      title: 'Your server',
      description: 'Encore plays music from your own server. This is what it '
          'found there, and what is missing.',
      children: [
        const SettingsSection('Music server'),
        ListTile(
          leading: Icon(
            reachable ? Icons.check_circle_rounded : Icons.cloud_off_rounded,
            color: reachable ? c.accent : c.onBgMuted,
          ),
          title: Text(server?.name ?? 'Music server'),
          subtitle: Text(
            [
              if (server != null) 'Signed in as ${server.username}',
              if (session != null)
                '${session.endpoints.current.label} (${session.endpoints.current.url.host})',
            ].join(' - '),
          ),
          trailing: Text(reachable ? 'Working' : 'Not reachable',
              style: context.text.labelLarge
                  ?.copyWith(color: reachable ? c.accent : c.onBgMuted)),
        ),
        ListTile(
          leading: const Icon(Icons.library_music_outlined),
          title: Text('${plural(tracks, 'song')} on this phone'),
          subtitle: Text('Library $synced. Play, sync, offline copies and '
              'playlists need only this.'),
        ),
        const ServerAddressesSection(),
        const InviteSomeoneTile(),
        const PeopleTile(),
        // The older way to get new music (a request portal next to the music
        // server) is shown only to somebody who uses it or has no "play any
        // song": a friend on a server with the instant-play service was told
        // "Not set up - Find it" for something that server does not have.
        if (connected || !instantReady) ...[
          const SettingsSection('Adding music'),
          if (!settings.requestsEnabled)
            ListTile(
              leading: Icon(Icons.cloud_off_outlined, color: c.onBgMuted),
              title: const Text('Switched off'),
              subtitle: const Text('Request and Import are hidden because you '
                  'said your server has no download service.'),
              trailing: TextButton(
                onPressed: () async {
                  ref.read(settingsProvider.notifier).setRequestsEnabled(true);
                  final done = await showDownloadServiceSheet(context);
                  if (done) ref.invalidate(requestBackendProvider);
                },
                child: const Text('Switch on'),
              ),
            )
          else if (connected)
            _ConnectedService(url: serviceUrl, user: settings.requestPortalUser)
          else
            ListTile(
              leading: Icon(Icons.cloud_off_outlined, color: c.onBgMuted),
              title: const Text('Not set up'),
              subtitle: const Text('Your server plays what it already has. A '
                  'download service finds and downloads new music, so '
                  'Request and Import work. Encore looks for it next to your '
                  'music server.'),
              trailing: TextButton(
                onPressed: () async {
                  final done = await showDownloadServiceSheet(context);
                  if (done) ref.invalidate(requestBackendProvider);
                },
                child: const Text('Find it'),
              ),
            ),
        ],
        const SettingsSection('Play any song'),
        const _InstantPlaySection(),
        const SettingsSection('Lyrics'),
        ListTile(
          leading: const Icon(Icons.lyrics_outlined),
          title: Text(serverLyrics
              ? 'Your server can serve lyrics'
              : 'Lyrics come from the web'),
          subtitle: Text(serverLyrics
              ? 'Encore asks your server first and falls back to LRCLIB on '
                  'the web for songs it has none for. A lyrics plugin on the '
                  'server (Navidrome 0.63 or newer) fills the gaps for every '
                  'app at once.'
              : 'This server does not offer lyrics, so Encore asks LRCLIB '
                  'on the web and keeps what it finds on the phone.'),
        ),
        const SettingsSection('What does my server need?'),
        const _Need(
          icon: Icons.dns_outlined,
          title: 'A music server - required',
          text: 'Navidrome, or any server that speaks the Subsonic API. It '
              'keeps the library; Encore keeps a copy on the phone so '
              'everything works offline.',
        ),
        const _Need(
          icon: Icons.download_for_offline_outlined,
          title: 'A download service - optional',
          text: 'The part that finds and downloads music your server does '
              'not have (for example Lidarr with Soulseek, torrents or '
              'YouTube behind a request page). Without it Encore is a '
              'complete player; with it you can Request albums and import '
              'Spotify or YouTube Music playlists.',
        ),
        const _Need(
          icon: Icons.language_rounded,
          title: 'A second address - optional',
          text: 'Add your Tailscale address when you sign in and the '
              'library works away from home too.',
        ),
      ],
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

/// The instant-play companion service: found or not, switched on or off.
class _InstantPlaySection extends ConsumerWidget {
  const _InstantPlaySection();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final enabled =
        ref.watch(settingsProvider.select((s) => s.instantPlayEnabled));
    final service = ref.watch(fetchServiceProvider);
    final c = context.colors;
    final notifier = ref.read(settingsProvider.notifier);

    Widget status() {
      if (!enabled) {
        return const ListTile(
          leading: Icon(Icons.pause_circle_outline_rounded),
          title: Text('Switched off'),
          subtitle: Text('Songs your server does not have only offer a '
              '30-second preview.'),
        );
      }
      return service.when(
        loading: () => const ListTile(
          leading: SizedBox.square(
              dimension: 24, child: CircularProgressIndicator(strokeWidth: 2)),
          title: Text('Looking next to your music server...'),
        ),
        error: (_, __) => _notFound(context, ref),
        data: (uri) => uri == null
            ? _notFound(context, ref)
            : ListTile(
                leading: Icon(Icons.bolt_rounded, color: c.accent),
                title: Text('Ready - ${uri.host}:${uri.port}'),
                subtitle: const Text('Tap any song in search or on an artist '
                    'page: your server gets it from the web, adds it to your '
                    'library at the best quality YouTube has (not lossless) '
                    'and it plays in seconds.'),
                trailing: TextButton(
                  onPressed: () => _askAddress(context, ref),
                  child: const Text('Change'),
                ),
              ),
      );
    }

    return Column(
      children: [
        SwitchListTile(
          secondary: const Icon(Icons.bolt_outlined),
          title: const Text('Play songs your server does not have'),
          subtitle: const Text('Needs the encore-fetch service on your '
              'server (see docs/19-instant-play.md). It signs in with your '
              'music login; nothing new to set up on the phone.'),
          value: enabled,
          onChanged: notifier.setInstantPlayEnabled,
        ),
        status(),
      ],
    );
  }

  Widget _notFound(BuildContext context, WidgetRef ref) {
    return ListTile(
      leading: Icon(Icons.cloud_off_outlined, color: context.colors.onBgMuted),
      title: const Text('Not found'),
      subtitle: const Text('No instant-play service answers next to your '
          'music server. Previews still work.'),
      trailing: Wrap(
        children: [
          TextButton(
            onPressed: () => ref.invalidate(fetchServiceProvider),
            child: const Text('Look again'),
          ),
          TextButton(
            onPressed: () => _askAddress(context, ref),
            child: const Text('Type'),
          ),
        ],
      ),
    );
  }

  Future<void> _askAddress(BuildContext context, WidgetRef ref) async {
    final controller = TextEditingController();
    final messenger = ScaffoldMessenger.of(context);
    final text = await showDialog<String>(
      context: context,
      builder: (dialog) => AlertDialog(
        title: const Text('Instant-play address'),
        content: TextField(
          controller: controller,
          autofocus: true,
          keyboardType: TextInputType.url,
          decoration: const InputDecoration(hintText: '192.168.1.10:8701'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialog).pop(),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.of(dialog).pop(controller.text),
            child: const Text('Check'),
          ),
        ],
      ),
    );
    controller.dispose();
    if (text == null || text.trim().isEmpty) return;
    final raw = text.trim();
    final uri = Uri.tryParse(raw.contains('://') ? raw : 'http://$raw');
    if (uri == null || uri.host.isEmpty) {
      messenger.showSnackBar(
          const SnackBar(content: Text('That is not an address.')));
      return;
    }
    final target = uri.hasPort ? uri : uri.replace(port: kFetchPort);
    final info = await EncoreFetchClient.probe(target);
    if (info == null || !info.canPlayNow) {
      messenger.showSnackBar(SnackBar(
          content: Text('Nothing that plays songs answers at '
              '${target.host}:${target.port}.')));
      return;
    }
    ref
        .read(settingsProvider.notifier)
        .setFetchServiceUrl('${target.scheme}://${target.host}:${target.port}');
    ref.invalidate(fetchServiceProvider);
  }
}

class _ConnectedService extends ConsumerStatefulWidget {
  const _ConnectedService({required this.url, required this.user});

  final String url;
  final String? user;

  @override
  ConsumerState<_ConnectedService> createState() => _ConnectedServiceState();
}

class _ConnectedServiceState extends ConsumerState<_ConnectedService> {
  String? _result;
  bool _testing = false;

  Future<void> _test() async {
    setState(() {
      _testing = true;
      _result = null;
    });
    final backend = await ref.read(requestBackendProvider.future);
    final result = backend == null
        ? 'Not connected yet.'
        : (await backend.check()).when(
            ok: (user) => 'Working - signed in as $user.',
            err: (failure) => failure.message,
          );
    if (!mounted) return;
    setState(() {
      _testing = false;
      _result = result;
    });
  }

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final uri = Uri.tryParse(widget.url);
    final where = uri == null || uri.host.isEmpty
        ? widget.url
        : (uri.hasPort ? '${uri.host}:${uri.port}' : uri.host);
    return Column(
      children: [
        ListTile(
          leading: Icon(Icons.cloud_done_outlined, color: c.accent),
          title: Text('Connected - $where'),
          subtitle:
              Text('Signed in as ${widget.user ?? 'your music server user'}. '
                  'Request albums and import Spotify or YouTube Music '
                  'playlists.'),
          trailing: TextButton(
            onPressed: () async {
              final done = await showDownloadServiceSheet(context);
              if (done) ref.invalidate(requestBackendProvider);
            },
            child: const Text('Change'),
          ),
        ),
        ListTile(
          leading: const Icon(Icons.wifi_tethering_rounded),
          title: const Text('Test connection'),
          subtitle: _testing
              ? const LinearProgressIndicator()
              : (_result == null ? null : Text(_result!)),
          onTap: _testing ? null : _test,
        ),
      ],
    );
  }
}

class _Need extends StatelessWidget {
  const _Need({required this.icon, required this.title, required this.text});

  final IconData icon;
  final String title;
  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(
          horizontal: Space.gutter, vertical: Space.sm),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 22, color: context.colors.onBgMuted),
          const SizedBox(width: Space.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: context.text.titleSmall),
                const SizedBox(height: 2),
                Text(text, style: context.text.bodyMedium),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
