import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/share_out.dart';
import '../../data/encore/encore_people.dart' show EncorePeopleApi;
import '../../data/people/people_client.dart';
import '../../design/tokens.dart';
import '../common/link_code.dart';
import 'people_providers.dart';

/// "Invite someone" on a server that has the people service (docs/35, docs/31).
/// One link: the friend opens it, chooses their own name and password on a
/// page, and their account is made. A link works once and does not last long;
/// open ones can be taken back. What to say to them, and how to get the app,
/// is the sender's own message: this only hands over the link.
///
/// An owner also chooses what the person becomes (ADR-092): a guest, or
/// someone who can bring their own friends in.
class ServiceInviteDialog extends ConsumerStatefulWidget {
  const ServiceInviteDialog({super.key});

  @override
  ConsumerState<ServiceInviteDialog> createState() => _ServiceInviteState();
}

class _ServiceInviteState extends ConsumerState<ServiceInviteDialog> {
  CreatedInvite? _made;
  String? _error;
  bool _busy = false;
  List<InviteRow>? _rows;
  PersonRole _role = PersonRole.guest;

  @override
  void initState() {
    super.initState();
    unawaited(_load());
  }

  Future<void> _load() async {
    final api = await ref.read(peopleApiProvider.future);
    final result = await api?.invites();
    if (!mounted) return;
    setState(() => _rows = result?.valueOrNull);
  }

  Future<void> _create() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    final api = await ref.read(peopleApiProvider.future);
    // Only an owner is shown the choice (so it stays a guest for everybody
    // else), and the service ignores it from anybody who is not one.
    final result = await api?.createInvite(role: _role);
    if (!mounted) return;
    setState(() {
      _busy = false;
      _made = result?.valueOrNull;
      _error = result == null
          ? 'This server has no invitations.'
          : result.failureOrNull?.message;
    });
    if (result?.isOk ?? false) unawaited(_load());
  }

  Future<void> _revoke(String id) async {
    final api = await ref.read(peopleApiProvider.future);
    await api?.revokeInvite(id);
    if (mounted) await _load();
  }

  static const _months = [
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', //
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
  ];

  static String _day(DateTime d) => '${d.day} ${_months[d.month - 1]}';

  /// "Open until 23 Oct", plus what the person becomes when that is more than
  /// a guest and, for an owner looking at everybody's, who made it.
  String _line(InviteRow row, {required bool showWho}) {
    final state = switch (row.state) {
      'open' => 'Open until ${_day(row.expiresAt)}',
      'used' => 'Used by ${row.redeemedBy ?? 'someone'}',
      'expired' => 'Expired',
      'revoked' => 'Revoked',
      final other => other,
    };
    return [
      state,
      if (row.role == PersonRole.inviter) 'can invite',
      if (showWho && row.inviter.isNotEmpty) 'by ${row.inviter}',
    ].join(' · ');
  }

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final made = _made;
    final owner = ref.watch(peopleProvider).value?.canManage ?? false;
    // An Encore server has owners and members: the second choice is another owner, who can invite and manage.
    final encore = ref.watch(encorePeopleApiProvider).value != null;
    return AlertDialog(
      title: const Text('Invite someone'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Send them this link. They choose their own name and password. '
              'Each link works once.',
              style: context.text.bodyMedium,
            ),
            if (owner && made == null) ...[
              const SizedBox(height: Space.md),
              Text('They will be', style: context.text.titleSmall),
              const SizedBox(height: Space.xs),
              SegmentedButton<PersonRole>(
                showSelectedIcon: false,
                segments: [
                  const ButtonSegment(
                      value: PersonRole.guest, label: Text('A guest')),
                  if (encore)
                    const ButtonSegment(
                        value: PersonRole.owner, label: Text('Another owner'))
                  else
                    const ButtonSegment(
                        value: PersonRole.inviter,
                        label: Text('Someone who can invite')),
                ],
                selected: {_role},
                onSelectionChanged: (s) => setState(() => _role = s.single),
              ),
              const SizedBox(height: Space.xs),
              Text(
                _role == PersonRole.owner
                    ? 'They can invite people and look after this server.'
                    : _role == PersonRole.inviter
                        ? 'They can bring their own friends in as guests.'
                        : 'They listen. They cannot invite anyone.',
                style: context.text.bodySmall?.copyWith(color: c.onBgMuted),
              ),
            ],
            const SizedBox(height: Space.md),
            if (made == null)
              FilledButton(
                onPressed: _busy ? null : _create,
                child: _busy
                    ? const SizedBox.square(
                        dimension: 18,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Text('Create invitation link'),
              )
            else ...[
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(Space.md),
                decoration: BoxDecoration(
                  color: c.surface,
                  borderRadius: BorderRadius.circular(Radii.card),
                ),
                child: SelectableText(made.url, style: context.text.bodySmall),
              ),
              const SizedBox(height: Space.sm),
              Text('Valid until ${_day(made.expiresAt)}, for one person.',
                  style: context.text.bodySmall?.copyWith(color: c.onBgMuted)),
              // A link with a home-network address opens only for somebody on that network: say so before it is sent.
              if (!EncorePeopleApi.worksAway(
                  Uri.tryParse(made.url) ?? Uri())) ...[
                const SizedBox(height: Space.sm),
                Text(
                  'This link opens only on your home network. To invite '
                  'somebody who is away, add the address you reach your '
                  'server at from outside, under Your server.',
                  key: const Key('invite-home-only'),
                  style: context.text.bodySmall?.copyWith(color: c.danger),
                ),
              ],
              const SizedBox(height: Space.lg),
              // For somebody sitting next to you: their own camera reads it
              // and offers to open the link in Encore. Light on dark, the way
              // a code is read.
              Center(child: LinkCode(data: made.url)),
              const SizedBox(height: Space.xs),
              Center(
                child: Text(
                  'Or let them scan this with their camera.',
                  style: context.text.bodySmall?.copyWith(color: c.onBgMuted),
                ),
              ),
            ],
            if (_error != null) ...[
              const SizedBox(height: Space.sm),
              Text(_error!,
                  style: context.text.bodyMedium?.copyWith(color: c.danger)),
            ],
            if (_rows != null && _rows!.isNotEmpty) ...[
              const SizedBox(height: Space.lg),
              Text('Invitations', style: context.text.titleSmall),
              for (final row in _rows!.take(10))
                Padding(
                  padding: const EdgeInsets.only(top: Space.xs),
                  child: Row(
                    children: [
                      Expanded(
                        child: Text(_line(row, showWho: owner),
                            style: context.text.bodyMedium),
                      ),
                      if (row.isOpen)
                        TextButton(
                          onPressed: () => unawaited(_revoke(row.id)),
                          child: const Text('Revoke'),
                        ),
                    ],
                  ),
                ),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Close'),
        ),
        if (made != null) ...[
          TextButton.icon(
            onPressed: () async {
              final messenger = ScaffoldMessenger.of(context);
              await Clipboard.setData(ClipboardData(text: made.url));
              if (!context.mounted) return;
              Navigator.of(context).pop();
              messenger.showSnackBar(const SnackBar(
                content: Text('Link copied.'),
              ));
            },
            icon: const Icon(Icons.copy_rounded, size: 18),
            label: const Text('Copy link'),
          ),
          FilledButton.icon(
            onPressed: () async {
              final messenger = ScaffoldMessenger.of(context);
              final opened = await ref
                  .read(shareOutProvider)
                  .text('Join me on Encore: ${made.url}');
              if (opened || !context.mounted) return;
              // No share sheet on this phone: the link can still be copied.
              messenger.showSnackBar(const SnackBar(
                content: Text('Could not open sharing. Copy the link instead.'),
              ));
            },
            icon: const Icon(Icons.ios_share_rounded, size: 18),
            label: const Text('Share'),
          ),
        ],
      ],
    );
  }
}
