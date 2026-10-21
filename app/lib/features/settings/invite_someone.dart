import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/providers.dart';
import '../../data/db/app_database.dart';
import '../../data/sync/endpoint_resolver.dart';
import '../../design/tokens.dart';
import '../../domain/connect_link.dart';
import '../people/invite_dialog.dart';
import '../people/people_providers.dart';

/// The message to send someone you want to listen with: the setup link built
/// from this phone's own addresses (ADR-068). They paste it on the sign-in
/// screen and only have to type their own username and password.
ConnectLink inviteLinkFor(ServerRow server) {
  final endpoints = [
    for (final e in jsonDecode(server.endpointsJson) as List)
      ServerEndpoint.fromJson((e as Map).cast<String, dynamic>()),
  ];
  String show(Uri u) {
    final text = u.toString();
    return text.endsWith('/') ? text.substring(0, text.length - 1) : text;
  }

  return ConnectLink(
    server: show(endpoints.first.url),
    away: endpoints.length > 1 ? show(endpoints[1].url) : null,
    name: server.name,
  );
}

/// "Invite someone" on the Your server page: shown to the people who may
/// invite, and to nobody else (a guest has no use for a button that does not
/// work for them).
///
/// - A server with the people service: an owner or somebody who can invite
///   makes a link that creates the account itself, and the friend chooses their
///   own name and password.
/// - A server without it: only the person who administers the music server
///   sees it, and it hands over the setup link for somebody who already has an
///   account there.
class InviteSomeoneTile extends ConsumerWidget {
  const InviteSomeoneTile({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final server = ref.watch(activeServerProvider).value;
    if (server == null) return const SizedBox.shrink();
    // Watched, so it is already known when the person taps (not loaded by the tap).
    final people = ref.watch(peopleProvider);
    final me = people.value;
    final viaService = me != null;
    final may = viaService
        ? me.canInvite
        : people.hasValue &&
            (ref.watch(isMusicServerAdminProvider).value ?? false);
    if (!may) return const SizedBox.shrink();
    return ListTile(
      leading: const Icon(Icons.person_add_alt_1_rounded),
      title: const Text('Invite someone'),
      subtitle: Text(viaService
          ? 'Send a link. They choose their own name and password.'
          : 'Send the link that connects the app to your server.'),
      onTap: () {
        unawaited(showDialog<void>(
          context: context,
          builder: (_) => viaService
              ? const ServiceInviteDialog()
              : _InviteDialog(link: inviteLinkFor(server)),
        ));
      },
    );
  }
}

/// "People" on the Your server page: only for an owner.
class PeopleTile extends ConsumerWidget {
  const PeopleTile({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (!(ref.watch(peopleProvider).value?.canManage ?? false)) {
      return const SizedBox.shrink();
    }
    return ListTile(
      leading: const Icon(Icons.group_outlined),
      title: const Text('People'),
      subtitle: const Text('Who is on this server, and who may invite.'),
      trailing: const Icon(Icons.chevron_right_rounded),
      onTap: () => context.push('/settings/people'),
    );
  }
}

/// The server has no people service, so the account already exists (made in
/// Navidrome). All this gives is the link; what to say with it is the sender's
/// own message.
class _InviteDialog extends StatelessWidget {
  const _InviteDialog({required this.link});

  final ConnectLink link;

  @override
  Widget build(BuildContext context) {
    final url = link.toLink();
    return AlertDialog(
      title: const Text('Invite someone'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
                'For someone who already has an account on your server. '
                'They paste this link in the app and type their own username '
                'and password.',
                style: context.text.bodyMedium),
            const SizedBox(height: Space.md),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(Space.md),
              decoration: BoxDecoration(
                color: context.colors.surface,
                borderRadius: BorderRadius.circular(Radii.card),
              ),
              child: SelectableText(url, style: context.text.bodySmall),
            ),
            const SizedBox(height: Space.md),
            Text('The link holds the server address only: no password.',
                style: context.text.bodySmall
                    ?.copyWith(color: context.colors.onBgMuted)),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Close'),
        ),
        FilledButton.icon(
          onPressed: () async {
            final messenger = ScaffoldMessenger.of(context);
            await Clipboard.setData(ClipboardData(text: url));
            if (!context.mounted) return;
            Navigator.of(context).pop();
            messenger.showSnackBar(const SnackBar(
              content: Text('Link copied.'),
            ));
          },
          icon: const Icon(Icons.copy_rounded, size: 18),
          label: const Text('Copy link'),
        ),
      ],
    );
  }
}
