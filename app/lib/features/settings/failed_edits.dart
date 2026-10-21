import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../data/sync/outbox_failures.dart';
import '../../design/tokens.dart';

/// The actions on edits the server turned down. `null` until a server is set up.
final outboxFailuresProvider = Provider.autoDispose<OutboxFailures?>((ref) {
  final serverId = ref.watch(activeServerIdProvider).value;
  if (serverId == null) return null;
  return OutboxFailures(
    db: ref.watch(databaseProvider),
    serverId: serverId,
    flush: () async {
      await ref.read(sessionProvider).value?.outbox.flush();
    },
    refresh: () async {
      ref.read(sessionProvider).value?.scheduler.requestSync();
    },
  );
});

/// Edits that could not be saved to the server, newest data first.
final failedEditsProvider = StreamProvider.autoDispose<List<FailedEdit>>(
  (ref) => ref.watch(outboxFailuresProvider)?.watch() ?? Stream.value(const []),
);

/// "N changes could not be saved" with Try again / Let go for each (B1).
///
/// Shows nothing at all when everything was saved, which is nearly always.
class FailedEditsSection extends ConsumerWidget {
  const FailedEditsSection({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final edits = ref.watch(failedEditsProvider).value ?? const [];
    final actions = ref.watch(outboxFailuresProvider);
    if (edits.isEmpty || actions == null) return const SizedBox.shrink();

    final colors = context.colors;
    final title = edits.length == 1
        ? '1 change could not be saved'
        : '${edits.length} changes could not be saved';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        ListTile(
          leading: Icon(Icons.error_outline_rounded, color: colors.warning),
          title: Text(title),
          subtitle: const Text(
            'The server turned them down. Try again, or let them go.',
          ),
          trailing: edits.length > 1
              ? TextButton(
                  onPressed: actions.retryAll,
                  child: const Text('Try all again'),
                )
              : null,
        ),
        for (final edit in edits)
          ListTile(
            key: ValueKey('failed-edit-${edit.id}'),
            contentPadding: const EdgeInsets.only(left: 72, right: Space.sm),
            title: Text(edit.what),
            subtitle: Text(edit.why),
            trailing: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                IconButton(
                  tooltip: 'Try again',
                  icon: const Icon(Icons.refresh_rounded),
                  onPressed: () => actions.retry(edit.id),
                ),
                IconButton(
                  tooltip: 'Let it go',
                  icon: const Icon(Icons.close_rounded),
                  onPressed: () => actions.discard(edit.id),
                ),
              ],
            ),
          ),
        const Divider(height: 1),
      ],
    );
  }
}
