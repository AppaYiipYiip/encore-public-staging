import 'dart:async';

import 'package:encore_session/encore_session.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../design/tokens.dart';
import 'add_songs_sheet.dart';
import 'jam_providers.dart';

/// Jam: listen together (docs/30). One phone plays, everybody in the Jam adds
/// songs and controls it. Before a Jam it says what it is and offers to start
/// one or join with a code; inside one it shows the code, who is in it, who
/// plays, what is queued and by whom.
class JamScreen extends ConsumerWidget {
  const JamScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final jam = ref.watch(jamControllerProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Jam')),
      body: jam.inJam ? _InJam(jam: jam) : _Before(jam: jam),
    );
  }
}

// ----------------------------------------------------------------- before

class _Before extends ConsumerStatefulWidget {
  const _Before({required this.jam});

  final JamSession jam;

  @override
  ConsumerState<_Before> createState() => _BeforeState();
}

class _BeforeState extends ConsumerState<_Before> {
  final _code = TextEditingController();

  @override
  void dispose() {
    _code.dispose();
    super.dispose();
  }

  void _join() => unawaited(
      ref.read(jamControllerProvider.notifier).join(_code.text.trim()));

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final hub = ref.watch(jamApiProvider);
    final busy = widget.jam.phase == JamPhase.connecting;
    return ListView(
      padding: const EdgeInsets.all(Space.gutter),
      children: [
        const SizedBox(height: Space.lg),
        Icon(Icons.groups_2_rounded, size: 56, color: c.accent),
        const SizedBox(height: Space.lg),
        Text('Listen together', style: context.text.headlineSmall),
        const SizedBox(height: Space.sm),
        Text(
          'Start a Jam and share its code. One phone plays; everybody in the '
          'Jam adds songs and controls it.',
          style: context.text.bodyMedium,
        ),
        if (widget.jam.phase == JamPhase.ended) ...[
          const SizedBox(height: Space.lg),
          Text('The Jam is over.',
              style: context.text.titleMedium?.copyWith(color: c.accent)),
        ],
        const SizedBox(height: Space.xl),
        if (hub.isLoading)
          const Center(child: CircularProgressIndicator())
        else if (hub.value == null)
          _Unavailable()
        else ...[
          FilledButton.icon(
            onPressed: busy
                ? null
                : () =>
                    unawaited(ref.read(jamControllerProvider.notifier).start()),
            icon: const Icon(Icons.play_circle_outline_rounded),
            label: const Text('Start a Jam'),
          ),
          const SizedBox(height: Space.xl),
          Text('Or join one', style: context.text.titleMedium),
          const SizedBox(height: Space.sm),
          Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _code,
                  textCapitalization: TextCapitalization.characters,
                  autocorrect: false,
                  maxLength: 6,
                  decoration: const InputDecoration(
                    labelText: 'Jam code',
                    counterText: '',
                  ),
                  onSubmitted: (_) => _join(),
                ),
              ),
              const SizedBox(width: Space.md),
              FilledButton(
                onPressed: busy ? null : _join,
                child: const Text('Join'),
              ),
            ],
          ),
        ],
      ],
    );
  }
}

class _Unavailable extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    return Container(
      padding: const EdgeInsets.all(Space.lg),
      decoration: BoxDecoration(
        color: c.surface,
        borderRadius: BorderRadius.circular(Radii.card),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Your server does not have Jam yet.',
              style: context.text.titleSmall),
          const SizedBox(height: Space.sm),
          Text(
            'Jam needs a small extra program on the server. Whoever runs it '
            'can switch it on: the server guide has a step called '
            '"Listening together".',
            style: context.text.bodyMedium,
          ),
        ],
      ),
    );
  }
}

// ------------------------------------------------------------------ in a Jam

class _InJam extends ConsumerWidget {
  const _InJam({required this.jam});

  final JamSession jam;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = jam.state!;
    final c = context.colors;
    final controller = ref.read(jamControllerProvider.notifier);
    final speaker = state.member(jam.speakerId ?? '');
    return ListView(
      padding: const EdgeInsets.fromLTRB(
          Space.gutter, Space.sm, Space.gutter, Space.xxl),
      children: [
        if (jam.reconnecting)
          Container(
            margin: const EdgeInsets.only(bottom: Space.md),
            padding: const EdgeInsets.all(Space.md),
            decoration: BoxDecoration(
              color: c.surface,
              borderRadius: BorderRadius.circular(Radii.card),
            ),
            child: Row(
              children: [
                const SizedBox.square(
                  dimension: 16,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
                const SizedBox(width: Space.md),
                Text('Reconnecting...', style: context.text.bodyMedium),
              ],
            ),
          ),
        _CodeCard(code: jam.code!),
        const SizedBox(height: Space.md),
        Text(
          jam.iPlay
              ? 'Playing on this phone'
              : 'Playing on ${speaker?.name ?? 'the host'}\'s phone',
          style: context.text.bodyMedium?.copyWith(color: c.onBgMuted),
        ),
        const SizedBox(height: Space.md),
        _PlayerCard(entry: state.current, queued: state.queue.length),
        const SizedBox(height: Space.md),
        FilledButton.icon(
          onPressed: () => unawaited(showAddSongsSheet(context)),
          icon: const Icon(Icons.add_rounded),
          label: const Text('Add songs'),
        ),
        const SizedBox(height: Space.xl),
        Text('In this Jam', style: context.text.titleMedium),
        const SizedBox(height: Space.xs),
        for (final member in state.members)
          _MemberRow(
            member: member,
            iAmHost: jam.isHost,
            isMe: member.id == jam.me,
            isSpeaker: member.id == jam.speakerId,
            onSend: controller.send,
          ),
        const SizedBox(height: Space.xl),
        if (jam.isHost)
          OutlinedButton(
            onPressed: () => unawaited(_confirmEnd(context, controller)),
            child: const Text('End Jam for everybody'),
          )
        else
          OutlinedButton(
            onPressed: () => unawaited(controller.leave()),
            child: const Text('Leave Jam'),
          ),
      ],
    );
  }

  Future<void> _confirmEnd(
      BuildContext context, JamController controller) async {
    final sure = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('End the Jam?'),
        content: const Text(
            'Everybody is disconnected and the queue is gone. The songs stay '
            'in everybody\'s libraries.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('End Jam'),
          ),
        ],
      ),
    );
    if (sure == true) await controller.leave();
  }
}

class _CodeCard extends StatelessWidget {
  const _CodeCard({required this.code});

  final String code;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    return Container(
      padding:
          const EdgeInsets.fromLTRB(Space.lg, Space.md, Space.sm, Space.md),
      decoration: BoxDecoration(
        color: c.surface,
        borderRadius: BorderRadius.circular(Radii.card),
      ),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Jam code',
                    style:
                        context.text.labelMedium?.copyWith(color: c.onBgMuted)),
                Text(code,
                    style: context.text.headlineMedium?.copyWith(
                        letterSpacing: 4, fontWeight: FontWeight.w800)),
                const SizedBox(height: Space.xs),
                Text(
                  'Friends open Encore, tap Jam and type it.',
                  style: context.text.bodySmall?.copyWith(color: c.onBgMuted),
                ),
              ],
            ),
          ),
          IconButton(
            tooltip: 'Copy the code',
            icon: const Icon(Icons.copy_rounded),
            onPressed: () async {
              final messenger = ScaffoldMessenger.of(context);
              await Clipboard.setData(ClipboardData(
                  text: 'Join my Jam on Encore: open the app, tap Jam on the '
                      'Home screen and type $code'));
              messenger
                  .showSnackBar(const SnackBar(content: Text('Code copied.')));
            },
          ),
        ],
      ),
    );
  }
}

/// The Jam's song is the person's song: the player at the bottom of every screen
/// and the full player with its queue are the Jam's (docs/39 F4). This card is
/// the way in to them.
class _PlayerCard extends StatelessWidget {
  const _PlayerCard({required this.entry, required this.queued});

  final QueueEntry? entry;
  final int queued;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final entry = this.entry;
    return Material(
      color: c.surfaceHigh,
      borderRadius: BorderRadius.circular(Radii.card),
      child: InkWell(
        borderRadius: BorderRadius.circular(Radii.card),
        onTap: entry == null ? null : () => context.push('/player'),
        child: Padding(
          padding: const EdgeInsets.all(Space.lg),
          child: Row(
            children: [
              Icon(
                entry == null
                    ? Icons.library_music_outlined
                    : Icons.graphic_eq_rounded,
                color: entry == null ? c.onBgMuted : c.accent,
              ),
              const SizedBox(width: Space.md),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      entry == null
                          ? 'Nothing playing yet'
                          : (entry.title ?? 'A song'),
                      style: context.text.titleMedium,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                    Text(
                      entry == null
                          ? 'Add songs, or play any song: it plays in the Jam.'
                          : [
                              if (entry.artist != null) entry.artist!,
                              queued == 1 ? '1 song' : '$queued songs',
                            ].join(' · '),
                      style:
                          context.text.bodySmall?.copyWith(color: c.onBgMuted),
                    ),
                  ],
                ),
              ),
              if (entry != null)
                Icon(Icons.chevron_right_rounded, color: c.onBgMuted),
            ],
          ),
        ),
      ),
    );
  }
}

class _MemberRow extends StatelessWidget {
  const _MemberRow({
    required this.member,
    required this.iAmHost,
    required this.isMe,
    required this.isSpeaker,
    required this.onSend,
  });

  final Member member;
  final bool iAmHost;
  final bool isMe;
  final bool isSpeaker;
  final Future<bool> Function(Command command) onSend;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    return ListTile(
      contentPadding: EdgeInsets.zero,
      leading: CircleAvatar(
        backgroundColor: c.accent,
        child: Text(member.name.characters.first.toUpperCase(),
            style: context.text.titleMedium?.copyWith(color: c.onAccent)),
      ),
      title: Text(isMe ? '${member.name} (you)' : member.name),
      subtitle: isSpeaker ? const Text('Plays the music') : null,
      trailing: member.isHost
          ? const Text('Host')
          : (iAmHost
              ? PopupMenuButton<String>(
                  tooltip: 'More for ${member.name}',
                  onSelected: (choice) {
                    if (choice == 'play') {
                      unawaited(onSend(Transfer(member.id)));
                    } else {
                      unawaited(onSend(Kick(member.id)));
                    }
                  },
                  itemBuilder: (_) => [
                    if (!isSpeaker)
                      PopupMenuItem(
                        value: 'play',
                        child: Text('Play on ${member.name}\'s phone'),
                      ),
                    const PopupMenuItem(
                        value: 'remove', child: Text('Remove from the Jam')),
                  ],
                )
              : null),
    );
  }
}
