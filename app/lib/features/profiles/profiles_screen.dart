import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/providers.dart';
import '../../data/db/app_database.dart';
import '../../design/tokens.dart';
import '../settings/sign_out.dart';

/// "Who's listening?" (P4-16): the people who signed in on this device, a tablet or a family phone. Picking one needs no password (the
/// sign-in was done once, on this device); everything of the person who was listening is left exactly as it was, and comes back when they
/// pick themselves again.
class ProfilesScreen extends ConsumerWidget {
  const ProfilesScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final profiles = ref.watch(profilesProvider).value ?? const <ServerRow>[];
    final active = ref.watch(activeServerProvider).value;
    final c = context.colors;
    return Scaffold(
      appBar: AppBar(
        title: const Text("Who's listening?"),
        leading: context.canPop()
            ? null
            : IconButton(
                tooltip: 'Back',
                icon: const Icon(Icons.arrow_back_rounded),
                onPressed: () => context.go('/home'),
              ),
      ),
      body: ListView(
        padding: const EdgeInsets.symmetric(vertical: Space.md),
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(
                Space.gutter, 0, Space.gutter, Space.md),
            child: Text(
              'Each person has their own library, playlists and downloads on '
              'this device. Switching does not sign anybody out.',
              style: context.text.bodyMedium?.copyWith(color: c.onBgMuted),
            ),
          ),
          for (final profile in profiles)
            _ProfileTile(
              profile: profile,
              active: profile.id == active?.id,
              onPick: () async {
                await ref.read(switchProfileProvider)(profile.id);
                if (context.mounted) context.go('/home');
              },
              onRemove: () => _remove(context, ref, profile),
            ),
          ListTile(
            key: const Key('add-someone'),
            leading: const CircleAvatar(
                radius: 22, child: Icon(Icons.person_add_alt_1_rounded)),
            title: Text('Add someone', style: context.text.titleMedium),
            subtitle: const Text('Sign in, or join with an invitation.'),
            onTap: () => context.push('/profiles/add'),
          ),
        ],
      ),
    );
  }

  /// Removing somebody from the device is the sign-out of that person: their copy of the library and their downloads go, the music server
  /// keeps everything. They are made the profile in use first (so the sign-out is theirs, with its usual words), and afterwards the person
  /// who was listening before is back.
  Future<void> _remove(
      BuildContext context, WidgetRef ref, ServerRow profile) async {
    await ref.read(switchProfileProvider)(profile.id);
    if (!context.mounted) return;
    await confirmAndSignOut(context, ref);
  }
}

class _ProfileTile extends StatelessWidget {
  const _ProfileTile({
    required this.profile,
    required this.active,
    required this.onPick,
    required this.onRemove,
  });

  final ServerRow profile;
  final bool active;
  final VoidCallback onPick;
  final VoidCallback onRemove;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final initial = profile.username.characters.first.toUpperCase();
    return ListTile(
      key: Key('profile-${profile.id}'),
      onTap: onPick,
      leading: CircleAvatar(
        radius: 22,
        backgroundColor: c.accent,
        child: Text(initial,
            style: context.text.titleMedium?.copyWith(color: c.onAccent)),
      ),
      title: Text(profile.username, style: context.text.titleMedium),
      subtitle: Text(active ? 'Listening now • ${profile.name}' : profile.name),
      trailing: PopupMenuButton<String>(
        tooltip: 'More about ${profile.username}',
        onSelected: (_) => onRemove(),
        itemBuilder: (_) => const [
          PopupMenuItem(
              value: 'remove', child: Text('Remove from this device')),
        ],
      ),
    );
  }
}

/// A shortcut for the places that offer "Switch user".
void openProfiles(BuildContext context) =>
    unawaited(context.push<void>('/profiles'));
