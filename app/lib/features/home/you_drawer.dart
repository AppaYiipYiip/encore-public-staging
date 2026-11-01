import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/navigation.dart';
import '../../app/providers.dart';
import '../../data/db/app_database.dart';
import '../../design/tokens.dart';
import '../jam/jam_providers.dart' show jamEntryShownProvider;
import '../news/news_providers.dart';
import '../people/people_providers.dart';
import '../settings/sign_out.dart';

/// What the avatar on Home opens (S-27, one profile; AUDIT F51, D-34): who is signed in, then one row per place, as Spotify arranges it.
/// Only rows whose place exists: What's new where the server keeps news, People for an owner, Jam where the server has Jam (no grey
/// placeholders). Left out until they exist: "View profile" (S-26, S-28) and "Recently played" (S-23). With several people on the device
/// the drawn "Who's listening" block comes first, so switching stays one tap from the avatar.
///
/// Sign out and Switch user are in Settings as well (S-70 draws them there).
class YouDrawer extends ConsumerWidget {
  const YouDrawer({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.colors;
    final server = ref.watch(activeServerProvider).value;
    final profiles = ref.watch(profilesProvider).value ?? const <ServerRow>[];
    final news = ref.watch(newsProvider);
    final canManage = ref.watch(peopleProvider).value?.canManage ?? false;
    final jam = ref.watch(jamEntryShownProvider);
    final reachable = ref.watch(phoneOnlineProvider) &&
        (ref.watch(sessionProvider).value?.endpoints.isReachable ?? false);
    final several = profiles.length > 1;

    // Closes the drawer, then opens the place (both in the same breath, while the context is still there).
    void open(VoidCallback place) {
      Navigator.of(context).pop();
      place();
    }

    return Drawer(
      key: const Key('you-drawer'),
      child: SafeArea(
        child: ListView(
          padding: const EdgeInsets.symmetric(vertical: Space.md),
          children: [
            if (server != null) _Header(name: server.username),
            if (several) ...[
              Padding(
                padding: const EdgeInsets.fromLTRB(
                    Space.gutter, Space.md, Space.gutter, Space.xs),
                child: Text("Who's listening",
                    style:
                        context.text.labelLarge?.copyWith(color: c.onBgMuted)),
              ),
              for (final profile in profiles)
                _ProfileRow(
                  profile: profile,
                  active: profile.id == server?.id,
                  onPick: () async {
                    if (profile.id != server?.id) {
                      await ref.read(switchProfileProvider)(profile.id);
                    }
                    if (context.mounted) Navigator.of(context).pop();
                  },
                ),
              ListTile(
                key: const Key('drawer-add-someone'),
                leading: const Icon(Icons.person_add_alt_1_rounded),
                title: const Text('Add someone'),
                onTap: () =>
                    open(() => unawaited(context.push<void>('/profiles/add'))),
              ),
              const Divider(),
            ],
            if (news.available)
              ListTile(
                key: const Key('drawer-news'),
                leading: const Icon(Icons.notifications_none_rounded),
                title: const Text("What's new"),
                trailing: news.unread > 0
                    ? Text('${news.unread} new',
                        style:
                            context.text.labelLarge?.copyWith(color: c.accent))
                    : null,
                onTap: () => open(() => Nav.news(context)),
              ),
            if (canManage)
              ListTile(
                key: const Key('drawer-people'),
                leading: const Icon(Icons.group_outlined),
                title: const Text('People'),
                onTap: () => open(
                    () => unawaited(context.push<void>('/settings/people'))),
              ),
            if (jam)
              ListTile(
                key: const Key('drawer-jam'),
                leading: const Icon(Icons.groups_2_rounded),
                title: const Text('Jam'),
                onTap: () => open(() => Nav.jam(context)),
              ),
            ListTile(
              key: const Key('drawer-settings'),
              leading: const Icon(Icons.settings_outlined),
              title: const Text('Settings'),
              onTap: () => open(() => Nav.settings(context)),
            ),
            if (server != null)
              ListTile(
                key: const Key('drawer-server'),
                leading: const Icon(Icons.dns_outlined),
                title: const Text('Your server'),
                subtitle: Text(
                    '${server.name} · ${reachable ? 'Connected' : 'Not connected'}'),
                onTap: () => open(
                    () => unawaited(context.push<void>('/settings/server'))),
              ),
            if (!several)
              ListTile(
                key: const Key('drawer-add-account'),
                leading: const Icon(Icons.person_add_alt_1_rounded),
                title: const Text('Add account'),
                onTap: () =>
                    open(() => unawaited(context.push<void>('/profiles/add'))),
              ),
            if (server != null)
              ListTile(
                key: const Key('drawer-sign-out'),
                leading: const Icon(Icons.logout_rounded),
                title: const Text('Sign out'),
                // The drawer stays under the question: the sign-out needs this widget's `ref`, which a closed drawer no longer has.
                onTap: () => unawaited(confirmAndSignOut(context, ref)),
              ),
          ],
        ),
      ),
    );
  }
}

class _Header extends StatelessWidget {
  const _Header({required this.name});

  final String name;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    return Padding(
      padding: const EdgeInsets.fromLTRB(
          Space.gutter, Space.md, Space.gutter, Space.md),
      child: Row(
        children: [
          CircleAvatar(
            radius: 24,
            backgroundColor: c.accent,
            child: Text(name.characters.first.toUpperCase(),
                style: context.text.titleLarge?.copyWith(color: c.onAccent)),
          ),
          const SizedBox(width: Space.md),
          Expanded(
            child: Text(name,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: context.text.titleLarge),
          ),
        ],
      ),
    );
  }
}

class _ProfileRow extends StatelessWidget {
  const _ProfileRow(
      {required this.profile, required this.active, required this.onPick});

  final ServerRow profile;
  final bool active;
  final VoidCallback onPick;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    return ListTile(
      key: Key('drawer-profile-${profile.id}'),
      leading: CircleAvatar(
        radius: 18,
        backgroundColor: c.accent,
        child: Text(profile.username.characters.first.toUpperCase(),
            style: context.text.titleSmall?.copyWith(color: c.onAccent)),
      ),
      title: Text(profile.username),
      subtitle: Text(profile.name),
      trailing: active
          ? Icon(Icons.check_rounded, color: c.accent, semanticLabel: 'Active')
          : null,
      onTap: onPick,
    );
  }
}
