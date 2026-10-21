import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../data/sync/sync_state_store.dart';
import '../../design/tokens.dart';

/// What the sync's shrink guard is holding back, e.g. `40 of 100 songs`, or
/// `null` when nothing is held (docs/23, B6).
final shrinkNoticeProvider = StreamProvider.autoDispose<String?>((ref) {
  final serverId = ref.watch(activeServerIdProvider).value;
  if (serverId == null) return Stream.value(null);
  return SyncStateStore(ref.watch(databaseProvider), serverId)
      .watch(SyncStateStore.shrinkNotice);
});

/// "The server lists far fewer songs than before" with a way to follow it.
///
/// The app never empties the phone's library on a surprisingly small answer
/// (a music drive unplugged on the server answers "nothing"). If the person
/// really removed the music, this is where they say so. Shows nothing at all
/// otherwise.
class ShrinkNoticeSection extends ConsumerWidget {
  const ShrinkNoticeSection({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final notice = ref.watch(shrinkNoticeProvider).value;
    if (notice == null) return const SizedBox.shrink();
    final session = ref.watch(sessionProvider).value;
    return Column(
      children: [
        ListTile(
          leading:
              Icon(Icons.warning_amber_rounded, color: context.colors.warning),
          title: const Text('Your server lists far fewer songs than before'),
          subtitle: Text(
            'It reports $notice. Your library on this phone was left as it '
            'was. If you removed that music on purpose, follow the server.',
          ),
          isThreeLine: true,
        ),
        Align(
          alignment: Alignment.centerRight,
          child: Padding(
            padding: const EdgeInsets.only(right: Space.md),
            child: TextButton(
              onPressed: session == null
                  ? null
                  : () async {
                      final ok = await showDialog<bool>(
                        context: context,
                        builder: (context) => AlertDialog(
                          title: const Text('Follow the server?'),
                          content: const Text(
                            'Songs the server no longer lists will disappear '
                            'from this phone.',
                          ),
                          actions: [
                            TextButton(
                              onPressed: () => Navigator.pop(context, false),
                              child: const Text('Cancel'),
                            ),
                            TextButton(
                              onPressed: () => Navigator.pop(context, true),
                              child: const Text('Follow the server'),
                            ),
                          ],
                        ),
                      );
                      if (ok ?? false) {
                        session.scheduler
                            .requestSync(force: true, acceptShrink: true);
                      }
                    },
              child: const Text('Follow the server'),
            ),
          ),
        ),
        const Divider(height: 1),
      ],
    );
  }
}
