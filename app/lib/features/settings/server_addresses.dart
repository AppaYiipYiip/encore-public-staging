import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/connection.dart'
    show ServerReachability, serverReachabilityProvider;
import '../../app/providers.dart';
import '../../data/auth/server_setup_service.dart';
import '../../data/db/app_database.dart';
import '../../data/sync/endpoint_resolver.dart';
import '../../design/tokens.dart';
import '../instant/instant_controller.dart' show fetchServiceProvider;
import '../people/people_providers.dart' show peopleServiceProvider;
import 'settings_page.dart';

/// How a saved address answered the last time it was tried.
enum _Answer { unknown, testing, answered, silent }

/// Counts the person's requests to ask the addresses again (a pull on the Your server page).
class AddressRecheck extends Notifier<int> {
  @override
  int build() => 0;

  void ask() => state++;
}

final addressRecheckProvider =
    NotifierProvider<AddressRecheck, int>(AddressRecheck.new);

class _Check {
  const _Check(this.answer, [this.took]);

  final _Answer answer;
  final Duration? took;
}

/// The addresses the phone tries for the music server: home, and the one for
/// away from home (a Tailscale name or an HTTPS address). They can be added
/// and removed here, after sign-in, without signing out (ADR-059).
class ServerAddressesSection extends ConsumerStatefulWidget {
  const ServerAddressesSection({super.key});

  @override
  ConsumerState<ServerAddressesSection> createState() =>
      _ServerAddressesSectionState();
}

class _ServerAddressesSectionState
    extends ConsumerState<ServerAddressesSection> {
  final Map<String, _Check> _checks = {};

  /// The page asks its addresses once by itself when it opens (and once the phone has a network, if it had none).
  bool _autoChecked = false;

  static List<ServerEndpoint> _decode(ServerRow server) => [
        for (final e in jsonDecode(server.endpointsJson) as List)
          ServerEndpoint.fromJson((e as Map).cast<String, dynamic>()),
      ];

  static String _show(Uri url) {
    final text = url.toString();
    return text.endsWith('/') ? text.substring(0, text.length - 1) : text;
  }

  Future<void> _test(ServerRow server, List<ServerEndpoint> endpoints,
      {bool quiet = false}) async {
    // With no network at all every address would "not answer": that says nothing about the addresses.
    if (ref.read(networkKindProvider).value == NetworkKind.none) return;
    final password =
        await ref.read(credentialStoreProvider).readPassword(server.id);
    if (!mounted) return;
    if (password == null) {
      if (!quiet) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('Sign in again to check the addresses.'),
        ));
      }
      return;
    }
    final service = ref.read(serverSetupServiceProvider);
    setState(() {
      for (final e in endpoints) {
        _checks[e.url.toString()] = const _Check(_Answer.testing);
      }
    });
    await Future.wait([
      for (final e in endpoints)
        () async {
          Duration? took;
          try {
            took = await service
                .probe(e,
                    username: server.username,
                    password: password,
                    expectedId: ServerSetupService.pinnedKeyOf(server))
                .timeout(const Duration(seconds: 6));
          } on Object {
            took = null;
          }
          if (!mounted) return;
          setState(() {
            _checks[e.url.toString()] = took == null
                ? const _Check(_Answer.silent)
                : _Check(_Answer.answered, took);
          });
        }(),
    ]);
    if (!mounted) return;
    // An address that did not answer (or whose name did not resolve yet) when
    // the app started may answer now: friends, invitations and "play any song"
    // are looked for again instead of staying "not there" until the next start.
    ref
      ..invalidate(peopleServiceProvider)
      ..invalidate(fetchServiceProvider);
  }

  Future<void> _add(ServerRow server, List<ServerEndpoint> current) async {
    final added = await showDialog<ServerEndpoint>(
      context: context,
      builder: (_) => _AddAddressDialog(existing: current),
    );
    if (added == null || !mounted) return;
    await ref
        .read(serverSetupServiceProvider)
        .updateEndpoints(server.id, [...current, added]);
    if (mounted) unawaited(_test(server, [added]));
  }

  Future<void> _remove(ServerRow server, List<ServerEndpoint> current,
      ServerEndpoint endpoint) async {
    final sure = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('Remove "${endpoint.label}"?'),
        content: Text('${_show(endpoint.url)}\n\nEncore will stop trying this '
            'address. Your music and playlists stay.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('Remove'),
          ),
        ],
      ),
    );
    if (sure != true || !mounted) return;
    await ref.read(serverSetupServiceProvider).updateEndpoints(server.id, [
      for (final e in current)
        if (e != endpoint) e
    ]);
  }

  @override
  Widget build(BuildContext context) {
    final server = ref.watch(activeServerProvider).value;
    if (server == null) return const SizedBox.shrink();
    final session = ref.watch(sessionProvider).value;
    final endpoints = _decode(server);
    // Whether there is a network at all (a raw fact: with none, testing an address says nothing about it) and whether the server answers (the one state).
    final online = ref.watch(networkKindProvider).value != NetworkKind.none;
    final inUse = session != null &&
            ref.watch(serverReachabilityProvider) == ServerReachability.ok
        ? session.endpoints.current.url
        : null;
    final c = context.colors;

    ref.listen<int>(addressRecheckProvider, (_, __) {
      final current = ref.read(activeServerProvider).value;
      if (current != null && mounted) {
        unawaited(_test(current, _decode(current)));
      }
    });
    if (online && !_autoChecked) {
      _autoChecked = true;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) unawaited(_test(server, endpoints, quiet: true));
      });
    }

    Widget dotted(Color color, String text) => Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 8,
              height: 8,
              decoration: BoxDecoration(color: color, shape: BoxShape.circle),
            ),
            const SizedBox(width: Space.sm),
            Text(text, style: context.text.labelLarge?.copyWith(color: color)),
          ],
        );

    Widget status(ServerEndpoint e) {
      // An answer from before the phone lost its network says nothing now.
      if (!online) return const SizedBox.shrink();
      final check = _checks[e.url.toString()];
      switch (check?.answer) {
        case _Answer.testing:
          return const SizedBox.square(
            dimension: 18,
            child: CircularProgressIndicator(strokeWidth: 2),
          );
        case _Answer.answered:
          return dotted(c.accent, '${check!.took!.inMilliseconds} ms');
        case _Answer.silent:
          return dotted(c.onBgMuted, 'No answer');
        case _Answer.unknown:
        case null:
          return inUse == e.url
              ? Text('In use',
                  style: context.text.labelLarge?.copyWith(color: c.accent))
              : const SizedBox.shrink();
      }
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SettingsSection('Addresses'),
        for (final e in endpoints)
          ListTile(
            leading: Icon(
              inUse == e.url ? Icons.check_circle_rounded : Icons.link_rounded,
              color: inUse == e.url ? c.accent : c.onBgMuted,
            ),
            title: Text(e.label),
            subtitle: Text(_show(e.url)),
            trailing: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                status(e),
                if (endpoints.length > 1)
                  IconButton(
                    tooltip: 'Remove ${e.label}',
                    icon: const Icon(Icons.delete_outline_rounded),
                    onPressed: () => _remove(server, endpoints, e),
                  ),
              ],
            ),
          ),
        ListTile(
          leading: const Icon(Icons.add_link_rounded),
          title: const Text('Add an address'),
          subtitle: const Text('For example the name Tailscale gives your '
              'server, to reach it away from home.'),
          onTap: () => _add(server, endpoints),
        ),
      ],
    );
  }
}

class _AddAddressDialog extends StatefulWidget {
  const _AddAddressDialog({required this.existing});

  final List<ServerEndpoint> existing;

  @override
  State<_AddAddressDialog> createState() => _AddAddressDialogState();
}

class _AddAddressDialogState extends State<_AddAddressDialog> {
  final _address = TextEditingController();
  final _label = TextEditingController();
  String? _error;

  @override
  void dispose() {
    _address.dispose();
    _label.dispose();
    super.dispose();
  }

  void _submit() {
    final problem = ServerSetupService.validateAddress(_address.text);
    if (problem != null) {
      setState(() => _error = problem);
      return;
    }
    final url = ServerSetupService.normalizeUrl(_address.text)!;
    if (widget.existing.any((e) => e.url == url)) {
      setState(() => _error = 'That address is already in the list.');
      return;
    }
    final label = _label.text.trim();
    Navigator.of(context).pop(ServerEndpoint(
      label: label.isEmpty ? 'Away from home' : label,
      url: url,
    ));
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Add an address'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: _address,
              autofocus: true,
              keyboardType: TextInputType.url,
              decoration: InputDecoration(
                labelText: 'Address',
                hintText: '100.64.0.5:4533',
                errorText: _error,
                errorMaxLines: 3,
              ),
              onChanged: (_) {
                if (_error != null) setState(() => _error = null);
              },
              onSubmitted: (_) => _submit(),
            ),
            const SizedBox(height: Space.md),
            TextField(
              controller: _label,
              decoration: const InputDecoration(
                labelText: 'Name (optional)',
                hintText: 'Away from home',
              ),
              onSubmitted: (_) => _submit(),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancel'),
        ),
        FilledButton(onPressed: _submit, child: const Text('Add')),
      ],
    );
  }
}
