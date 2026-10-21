import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/result.dart';
import '../../data/people/people_client.dart';
import '../../design/tokens.dart';
import '../settings/settings_page.dart';
import 'invite_dialog.dart';
import 'people_providers.dart';

/// Your server > People (ADR-092): everybody on the server, what each person
/// is, and for an owner the means to change it. An owner can make another
/// owner (a couple who both run the server), let a trusted friend invite, or
/// take someone off the server. Everybody else is told, in a line, that this
/// is for owners.
class PeopleScreen extends ConsumerStatefulWidget {
  const PeopleScreen({super.key});

  @override
  ConsumerState<PeopleScreen> createState() => _PeopleScreenState();
}

class _PeopleScreenState extends ConsumerState<PeopleScreen> {
  bool _busy = false;

  /// Runs one change on the server, then asks the server again what it holds:
  /// what is shown is never a guess about what happened.
  Future<void> _apply(
    Future<Result<void>> Function(PeopleApi api) change, {
    String? done,
  }) async {
    if (_busy) return;
    final messenger = ScaffoldMessenger.of(context);
    setState(() => _busy = true);
    final api = await ref.read(peopleApiProvider.future);
    final result = api == null
        ? const Result<void>.err(
            NotFoundFailure('This server has no list of people.'))
        : await change(api);
    ref.invalidate(peopleDirectoryProvider);
    await ref.read(peopleDirectoryProvider.future);
    if (!mounted) return;
    setState(() => _busy = false);
    final failure = result.failureOrNull;
    final text = failure?.message ?? done;
    if (text != null) {
      messenger
        ..hideCurrentSnackBar()
        ..showSnackBar(SnackBar(content: Text(text)));
    }
  }

  Future<void> _setRole(PersonOnServer person, PersonRole role) async {
    if (role == person.role) return;
    if (role == PersonRole.owner && !await _confirmOwner(person)) return;
    await _apply((api) => api.setRole(person.user, role));
  }

  Future<void> _remove(PersonOnServer person) async {
    if (!await _confirmRemove(person)) return;
    await _apply(
      (api) => api.removePerson(person.user),
      done: '${person.user} was removed from the server.',
    );
  }

  Future<bool> _confirmOwner(PersonOnServer person) async =>
      await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: Text('Make ${person.user} an owner?'),
          content: const Text(
              'Owners can invite people, change who may invite and remove '
              'people. Only do this for someone you trust as much as '
              'yourself.'),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(context).pop(false),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () => Navigator.of(context).pop(true),
              child: const Text('Make owner'),
            ),
          ],
        ),
      ) ??
      false;

  Future<bool> _confirmRemove(PersonOnServer person) async =>
      await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: Text('Remove ${person.user}?'),
          content: Text(
              "${person.user}'s account, playlists and likes are deleted from "
              'the server. The music files stay where they are. Invitations '
              'they made stop working; the people they invited stay.'),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(context).pop(false),
              child: const Text('Cancel'),
            ),
            FilledButton(
              style: FilledButton.styleFrom(
                  backgroundColor: context.colors.danger),
              onPressed: () => Navigator.of(context).pop(true),
              child: const Text('Remove'),
            ),
          ],
        ),
      ) ??
      false;

  @override
  Widget build(BuildContext context) {
    final me = ref.watch(peopleProvider);
    return SettingsPage(
      title: 'People',
      description: 'Owners run the server: they invite people, choose who '
          'else may invite, and remove people. Someone who can invite brings '
          'their friends in. Guests listen.',
      children: me.when(
        loading: () => const [_Waiting()],
        error: (_, __) => const [_Note('This server has no list of people.')],
        data: (me) {
          if (me == null) {
            return const [_Note('This server has no list of people.')];
          }
          if (!me.canManage) {
            return const [
              _Note('Only an owner can see and change who is on the server.'),
            ];
          }
          return [
            ListTile(
              leading: const Icon(Icons.person_add_alt_1_rounded),
              title: const Text('Invite someone'),
              subtitle: const Text('Send a link. They choose their own name '
                  'and password.'),
              onTap: () => unawaited(showDialog<void>(
                context: context,
                builder: (_) => const ServiceInviteDialog(),
              )),
            ),
            const SettingsSection('On this server'),
            ..._people(me),
          ];
        },
      ),
    );
  }

  List<Widget> _people(PeopleMe me) {
    final list = ref.watch(peopleDirectoryProvider);
    return list.when(
      loading: () => const [_Waiting()],
      error: (_, __) => const [_Note('The list could not be read.')],
      data: (result) {
        final people = result.valueOrNull;
        if (people == null) {
          return [
            _Note(
                result.failureOrNull?.message ?? 'The list could not be read.'),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: Space.gutter),
              child: Align(
                alignment: Alignment.centerLeft,
                child: TextButton(
                  onPressed: () => ref.invalidate(peopleDirectoryProvider),
                  child: const Text('Try again'),
                ),
              ),
            ),
          ];
        }
        return [
          for (final person in people)
            _PersonTile(
              person: person,
              isMe: person.user == me.user,
              busy: _busy,
              onRole: (role) => unawaited(_setRole(person, role)),
              onRemove: () => unawaited(_remove(person)),
            ),
        ];
      },
    );
  }
}

class _PersonTile extends StatelessWidget {
  const _PersonTile({
    required this.person,
    required this.isMe,
    required this.busy,
    required this.onRole,
    required this.onRemove,
  });

  final PersonOnServer person;
  final bool isMe;
  final bool busy;
  final ValueChanged<PersonRole> onRole;
  final VoidCallback onRemove;

  String get _line {
    final by = person.invitedBy;
    if (person.isFounding) return '${person.role.label} · set on the server';
    return by == null
        ? person.role.label
        : '${person.role.label} · invited by $by';
  }

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    // Yourself and the owners the server itself names are not changed here.
    final changeable = !isMe && !person.isFounding;
    return ListTile(
      leading: CircleAvatar(
        backgroundColor: c.accent,
        child: Text(person.user.characters.first.toUpperCase(),
            style: context.text.titleMedium?.copyWith(color: c.onAccent)),
      ),
      title: Text(isMe ? '${person.user} (you)' : person.user),
      subtitle: Text(_line),
      trailing: changeable
          ? PopupMenuButton<Object>(
              tooltip: 'Change ${person.user}',
              enabled: !busy,
              icon: const Icon(Icons.more_vert_rounded),
              onSelected: (choice) {
                if (choice is PersonRole) {
                  onRole(choice);
                } else {
                  onRemove();
                }
              },
              itemBuilder: (_) => [
                for (final role in PersonRole.values)
                  CheckedPopupMenuItem<Object>(
                    value: role,
                    checked: role == person.role,
                    child: Text(role.label),
                  ),
                const PopupMenuDivider(),
                PopupMenuItem<Object>(
                  value: 'remove',
                  child: Text('Remove from server',
                      style: TextStyle(color: c.danger)),
                ),
              ],
            )
          : null,
    );
  }
}

class _Note extends StatelessWidget {
  const _Note(this.text);

  final String text;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.all(Space.gutter),
        child: Text(text,
            style: context.text.bodyMedium
                ?.copyWith(color: context.colors.onBgMuted)),
      );
}

class _Waiting extends StatelessWidget {
  const _Waiting();

  @override
  Widget build(BuildContext context) => const Padding(
        padding: EdgeInsets.all(Space.xl),
        child: Center(child: CircularProgressIndicator()),
      );
}
