import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/repos/request_repository.dart';
import '../../design/tokens.dart';
import '../requests/download_service_sheet.dart';
import '../requests/request_providers.dart';
import '../requests/request_ui.dart';
import 'notifications_screen.dart';
import 'settings_controller.dart';
import 'settings_page.dart';

/// Get new music: the connected download service, a connection test, the
/// alerts, and every request with its state (docs/07-request-pipeline.md).
class RequestsSettingsScreen extends ConsumerStatefulWidget {
  const RequestsSettingsScreen({super.key});

  @override
  ConsumerState<RequestsSettingsScreen> createState() =>
      _RequestsSettingsScreenState();
}

class _RequestsSettingsScreenState
    extends ConsumerState<RequestsSettingsScreen> {
  String? _testResult;
  bool _testing = false;

  Future<void> _test() async {
    setState(() {
      _testing = true;
      _testResult = null;
    });
    final backend = await ref.read(requestBackendProvider.future);
    if (backend == null) {
      if (mounted) {
        setState(() {
          _testing = false;
          _testResult = 'Not connected yet.';
        });
      }
      return;
    }
    final result = await backend.check();
    if (!mounted) return;
    setState(() {
      _testing = false;
      _testResult = result.when(
        ok: (user) => 'Connected as $user.',
        err: (failure) => failure.message,
      );
    });
  }

  @override
  Widget build(BuildContext context) {
    final settings = ref.watch(settingsProvider);
    final url = settings.requestPortalUrl;
    final connected = url != null && url.isNotEmpty;
    final repo = ref.watch(requestRepositoryProvider);
    final c = context.colors;

    return SettingsPage(
      title: 'Get new music',
      description:
          'Your music server only plays what it already has. To get more, '
          'Encore asks the download service - the part of your server that '
          'finds and downloads music. Search shows what exists beyond your '
          'library; Request and Import send it to that service.',
      children: [
        const SettingsSection('Download service'),
        ListTile(
          leading: Icon(
            connected ? Icons.cloud_done_outlined : Icons.cloud_off_outlined,
            color: connected ? c.accent : c.onBgMuted,
          ),
          title: Text(connected ? url : 'Not connected'),
          subtitle: Text(connected
              ? 'Signed in as ${settings.requestPortalUser ?? 'your server user'}'
              : 'Connect once; Encore looks for it for you.'),
          trailing: TextButton(
            onPressed: () async {
              final done = await showDownloadServiceSheet(context);
              if (done) ref.invalidate(requestBackendProvider);
            },
            child: Text(connected ? 'Change' : 'Connect'),
          ),
        ),
        SwitchListTile(
          title: const Text('Show Request and Import'),
          subtitle: const Text(
              'Switch off if your server has no download service; the rest '
              'of the app is unchanged.'),
          value: settings.requestsEnabled,
          onChanged: ref.read(settingsProvider.notifier).setRequestsEnabled,
        ),
        if (connected)
          ListTile(
            leading: const Icon(Icons.wifi_tethering_rounded),
            title: const Text('Test connection'),
            subtitle: _testing
                ? const LinearProgressIndicator()
                : (_testResult == null ? null : Text(_testResult!)),
            onTap: _testing ? null : _test,
          ),
        const SettingsSection('Notifications'),
        const NotificationSwitches(),
        const SettingsSection('Your requests'),
        if (repo == null) const SizedBox.shrink() else _RequestList(repo: repo),
      ],
    );
  }
}

class _RequestList extends ConsumerWidget {
  const _RequestList({required this.repo});

  final RequestRepository repo;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return StreamBuilder(
      stream: repo.watchAll(),
      builder: (context, snapshot) {
        final rows = snapshot.data ?? const [];
        if (rows.isEmpty) {
          return const ListTile(
            title: Text('Nothing requested yet'),
            subtitle: Text('Search for an artist or album you do not own.'),
          );
        }
        return Column(
          children: [
            for (final r in rows)
              ListTile(
                title: Text(r.album ?? r.artist),
                subtitle: Text(
                  [
                    if (r.album != null) r.artist,
                    _label(r.state),
                    if (r.state == RequestState.failed && r.detail != null)
                      r.detail!,
                  ].join(' - '),
                ),
                trailing: RequestChip(artist: r.artist, album: r.album),
              ),
          ],
        );
      },
    );
  }

  static String _label(String state) => switch (state) {
        RequestState.submitted => 'Sending',
        RequestState.requested => 'On its way',
        RequestState.inLibrary => 'In your library',
        RequestState.failed => 'Failed',
        _ => state,
      };
}
