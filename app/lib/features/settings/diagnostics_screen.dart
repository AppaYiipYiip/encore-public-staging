import 'dart:io' show Platform;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/background_sync.dart';
import '../../app/branding.dart';
import '../../app/notifications.dart';
import '../../app/power_wiring.dart';
import '../../app/providers.dart';
import '../../core/logger.dart';
import '../../core/perf.dart';
import '../../data/alerts/alerts_service.dart';
import '../../data/diagnostics/listening_log.dart';
import '../../data/sync/sync_state_store.dart';
import '../../design/tokens.dart';
import '../common/format.dart';
import '../downloads/download_providers.dart';
import '../providers.dart';
import 'settings_controller.dart';

/// Which kind of server the session is talking to, in words (AUDIT F53): every mode-dependent behaviour (the first minutes after a sign-in, a tap
/// on a catalogue song, Download, Import, Jam) depends on it, and a report that cannot say it has to be read from the outside. A phone that has
/// just signed in to an Encore server starts as a plain music server "still looking" and becomes an Encore server within seconds (F30).
String describeSessionMode({
  required bool signedIn,
  required bool encoreMode,
  required bool detecting,
}) {
  if (!signedIn) return 'none (nobody is signed in, or it is still starting)';
  if (encoreMode) return 'Encore server';
  return detecting
      ? 'plain music server, still looking for an Encore server'
      : 'plain music server';
}

/// Builds the plain-text report shown on screen and copied to the clipboard.
/// Pure (all inputs passed in) so its format is unit-tested.
String buildDiagnosticsReport({
  required Map<String, String> sections,
  required List<String> log,
}) {
  final b = StringBuffer();
  sections.forEach((title, body) {
    b
      ..writeln('== $title ==')
      ..writeln(body.trimRight())
      ..writeln();
  });
  b.writeln('== Recent log ==');
  for (final line in log) {
    b.writeln(line);
  }
  return b.toString();
}

/// Everything the owner needs to attach to a bug report, no passwords
/// (log lines are scrubbed at the source).
class DiagnosticsScreen extends ConsumerWidget {
  const DiagnosticsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final server = ref.watch(activeServerProvider).value;
    final sync = ref.watch(syncStatusProvider).value;
    final tracks = ref.watch(trackCountProvider).value;
    final network = ref.watch(networkKindProvider).value;
    final snapshot = ref.watch(playbackSnapshotProvider).value;
    final queue = ref.watch(playbackFacadeProvider).queue;
    final storage = ref.watch(storageSummaryProvider).value;
    final settings = ref.watch(settingsProvider);
    final perf = PerfMonitor.instance;
    final background = ref.watch(_backgroundRunProvider).value;
    final listening = ref.watch(listeningSessionsProvider).value;

    String mode() => kReleaseMode
        ? 'release'
        : kProfileMode
            ? 'profile'
            : 'debug';

    final spans = perf.spans.reversed
        .take(12)
        .map((s) => '${s.name}: ${s.duration.inMilliseconds} ms'
            '${s.detail == null ? '' : ' (${s.detail})'}')
        .join('\n');

    final session = ref.watch(sessionProvider).value;
    final sections = <String, String>{
      'App': '${AppBranding.name} ${AppBranding.versionLine} (${mode()})\n'
          '${Platform.operatingSystem} ${Platform.operatingSystemVersion}',
      'Server': 'session: ${describeSessionMode(signedIn: session != null, encoreMode: session?.encoreMode ?? false, detecting: session?.detecting.value ?? false)}\n'
          'name: ${server?.name ?? '-'}\n'
          'tracks in library: ${tracks ?? '-'}\n'
          'network: ${network?.name ?? '-'}\n'
          'last sync: ${sync?.lastSuccessAt?.toIso8601String() ?? 'never'}\n'
          'syncing: ${sync?.isSyncing ?? false}\n'
          'background sync: ${backgroundSyncLabel(settings.backgroundSyncHours)}'
          ', last pass: ${background ?? 'never'}'
          '${sync?.lastFailure == null ? '' : '\nlast failure: ${sync!.lastFailure!.message}'}',
      'Playback': 'track: ${snapshot?.track?.title ?? '-'}\n'
          'playing: ${snapshot?.isPlaying ?? false}\n'
          'queue: ${queue.items.length} items, position ${queue.currentIndex}\n'
          'shuffle: ${snapshot?.shuffle ?? false}  repeat: ${snapshot?.repeat.name ?? '-'}\n'
          'stream quality: wifi=${settings.streamQualityWifi.id} '
          'mobile=${settings.streamQualityMobile.id}\n'
          'replay gain: ${settings.replayGainMode.name}',
      'Downloads': 'downloaded: ${storage?.tracks ?? 0} songs, '
          '${formatBytes(storage?.bytes ?? 0)}\n'
          'quality: ${settings.downloadQuality.id}  '
          'wifi only: ${settings.wifiOnlyDownloads}',
      'Alerts': 'new on your server: ${settings.alertsOnServer}\n'
          'new releases: ${settings.alertsReleases}\n'
          'imports: ${settings.alertsImports}\n'
          'private listening: ${settings.privateListening}',
      'Battery while listening': _listeningSummary(listening),
      'Performance (since start)': perf.lifetimeSummary(),
      'Latencies': spans.isEmpty ? 'none recorded yet' : spans,
    };

    final log = Log.recent.reversed.take(120).map((r) => r.toString()).toList();
    final report = buildDiagnosticsReport(sections: sections, log: log);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Diagnostics'),
        actions: [
          IconButton(
            tooltip: 'Run a background sync pass now',
            icon: const Icon(Icons.bolt_rounded),
            onPressed: () async {
              await ref.read(backgroundSyncSchedulerProvider).runOnceNow();
              if (context.mounted) {
                ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
                    content: Text('Background sync pass requested')));
              }
            },
          ),
          IconButton(
            tooltip: 'Send a test notification',
            icon: const Icon(Icons.notifications_active_outlined),
            onPressed: () async {
              final notifications = ref.read(localNotificationsProvider);
              final allowed = await notifications.requestPermission();
              if (allowed) {
                await notifications.show(const AlertNotification(
                  id: 4199,
                  title: 'Notifications work',
                  body: 'This is what a new-music alert looks like.',
                  route: '/settings/requests',
                ));
              }
              if (context.mounted) {
                ScaffoldMessenger.of(context).showSnackBar(SnackBar(
                    content: Text(allowed
                        ? 'Test notification sent'
                        : 'Notifications are not allowed for Encore')));
              }
            },
          ),
          IconButton(
            tooltip: 'Copy report',
            icon: const Icon(Icons.copy_rounded),
            onPressed: () async {
              await Clipboard.setData(ClipboardData(text: report));
              if (context.mounted) {
                ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text('Report copied')));
              }
            },
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(Space.gutter),
        children: [
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('Show a performance counter'),
            subtitle: const Text('Frames per second, how long a frame takes '
                'to build and to draw, memory and CPU, on top of every '
                'screen. For finding slow spots; leave it off for daily use.'),
            value: settings.perfOverlay,
            onChanged: ref.read(settingsProvider.notifier).setPerfOverlay,
          ),
          const Divider(),
          SelectableText(
            report,
            style: context.text.bodySmall?.copyWith(fontFamily: 'monospace'),
          ),
        ],
      ),
    );
  }
}

/// Plain-text lines for the listening log (newest last).
String _listeningSummary(List<ListeningSession>? sessions) {
  if (sessions == null || sessions.isEmpty) {
    return 'nothing recorded yet - listen for 20 minutes or more with the '
        'phone unplugged and it appears here';
  }
  String two(int v) => v.toString().padLeft(2, '0');
  String length(Duration d) => d.inHours > 0
      ? '${d.inHours} h ${two(d.inMinutes % 60)} min'
      : '${d.inMinutes} min';
  final lines = <String>[];
  for (final s in sessions.reversed.take(6).toList().reversed) {
    final start = DateTime.fromMillisecondsSinceEpoch(s.startMs);
    final rate = s.percentPerHour;
    lines.add('${start.year}-${two(start.month)}-${two(start.day)} '
        '${two(start.hour)}:${two(start.minute)}  ${length(s.length)}  '
        '${s.startLevel}% -> ${s.endLevel}%'
        '${s.charged ? '  (charging)' : ''}'
        '${rate == null ? '' : '  ${rate.toStringAsFixed(1)} %/h'}');
  }
  final average = ListeningLog.average(sessions);
  lines.add(average == null
      ? 'average: not enough unplugged listening yet'
      : 'average: ${average.percentPerHour.toStringAsFixed(1)} %/h over '
          '${average.sessions} sessions (unplugged, 20 min or more)');
  return lines.join('\n');
}

/// "3 h ago - ok" for the last background pass, `null` if it never ran.
final _backgroundRunProvider =
    StreamProvider.autoDispose<String?>((ref) async* {
  final serverId = await ref.watch(activeServerIdProvider.future);
  if (serverId == null) {
    yield null;
    return;
  }
  final db = ref.watch(databaseProvider);
  final clock = ref.watch(clockProvider);
  // The job runs in another process-engine: poll the shared database.
  while (true) {
    final store = SyncStateStore(db, serverId);
    final at = await store.getInt(SyncStateStore.lastBackgroundRunAtMs);
    final result = await store.get(SyncStateStore.lastBackgroundResult);
    if (at == null) {
      yield null;
    } else {
      final age =
          clock.now().difference(DateTime.fromMillisecondsSinceEpoch(at));
      final text = age.inMinutes < 1
          ? 'just now'
          : age.inHours < 1
              ? '${age.inMinutes} min ago'
              : age.inDays < 1
                  ? '${age.inHours} h ago'
                  : '${age.inDays} d ago';
      yield '$text (${result ?? '?'})';
    }
    await Future<void>.delayed(const Duration(seconds: 5));
  }
});
