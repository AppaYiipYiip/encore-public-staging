import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/power.dart';
import '../data/diagnostics/listening_log.dart';
import '../data/sync/sync_state_store.dart';
import '../features/providers.dart';
import 'providers.dart';

final powerProbeProvider =
    Provider<PowerProbe>((ref) => MethodChannelPowerProbe());

/// The listening log of the configured server (battery level at both ends of
/// every stretch of listening).
final listeningLogProvider = Provider<ListeningLog?>((ref) {
  final serverId = ref.watch(activeServerIdProvider).value;
  if (serverId == null) return null;
  return ListeningLog(
    store: SyncStateStore(ref.watch(databaseProvider), serverId),
    probe: ref.watch(powerProbeProvider),
    clock: ref.watch(clockProvider),
  );
});

/// Follows playback and feeds [listeningLogProvider]. Watched once by the
/// app widget.
final listeningLoggerProvider = Provider<void>((ref) {
  final log = ref.watch(listeningLogProvider);
  if (log == null) return;
  var playing = false;
  Timer? ticker;
  ref.listen(playbackSnapshotProvider, (previous, next) {
    final now = next.value?.isPlaying ?? false;
    if (now == playing) return;
    playing = now;
    if (now) {
      unawaited(log.started());
      // Notes charging and screen state; one wake-up a minute while the
      // audio already keeps the CPU busy.
      ticker ??= Timer.periodic(
        const Duration(minutes: 1),
        (_) => unawaited(log.tick()),
      );
    } else {
      ticker?.cancel();
      ticker = null;
      unawaited(log.stopped());
    }
  });
  ref.onDispose(() => ticker?.cancel());
});

/// Recorded listening sessions for the Diagnostics screen.
final listeningSessionsProvider =
    FutureProvider.autoDispose<List<ListeningSession>>((ref) async {
  final log = ref.watch(listeningLogProvider);
  if (log == null) return const <ListeningSession>[];
  return log.sessions();
});
