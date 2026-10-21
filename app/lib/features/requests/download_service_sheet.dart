import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../core/network_policy.dart';
import '../../core/result.dart';
import '../../data/db/app_database.dart';
import '../../data/requests/portal_discovery.dart';
import '../../data/sync/endpoint_resolver.dart';
import '../../design/tokens.dart';
import '../settings/settings_controller.dart';
import 'request_providers.dart';

/// Opens the connection sheet; completes with `true` once a download service
/// is connected (ADR-052).
Future<bool> showDownloadServiceSheet(BuildContext context) async {
  final done = await showModalBottomSheet<bool>(
    context: context,
    isScrollControlled: true,
    builder: (_) => const DownloadServiceSheet(),
  );
  return done ?? false;
}

enum _Phase { looking, found, none, searching, typing, connecting, login }

/// Finds the download service and signs in to it with as little typing as
/// possible: look next to the music server first, offer a network search, sign
/// in with the music server's own login, and only ask for another login when
/// the service refuses that one.
class DownloadServiceSheet extends ConsumerStatefulWidget {
  const DownloadServiceSheet({super.key});

  @override
  ConsumerState<DownloadServiceSheet> createState() =>
      _DownloadServiceSheetState();
}

class _DownloadServiceSheetState extends ConsumerState<DownloadServiceSheet> {
  final _address = TextEditingController();
  final _user = TextEditingController();
  final _password = TextEditingController();

  _Phase _phase = _Phase.looking;
  List<Uri> _asked = const [];
  List<Uri> _found = const [];
  Uri? _chosen;
  String? _message;
  ({int done, int total})? _progress;
  bool _searchCancelled = false;
  bool _searched = false;
  ServerRow? _server;
  List<Uri> _endpoints = const [];

  @override
  void initState() {
    super.initState();
    unawaited(_look());
  }

  @override
  void dispose() {
    _searchCancelled = true;
    _address.dispose();
    _user.dispose();
    _password.dispose();
    super.dispose();
  }

  // ------------------------------------------------------------- steps

  Future<void> _loadServer() async {
    final server = await ref.read(activeServerProvider.future);
    _server = server;
    _endpoints = _endpointsOf(server);
    _user.text =
        ref.read(settingsProvider).requestPortalUser ?? server?.username ?? '';
  }

  static List<Uri> _endpointsOf(ServerRow? server) {
    if (server == null) return const [];
    try {
      return [
        for (final e in jsonDecode(server.endpointsJson) as List)
          ServerEndpoint.fromJson((e as Map).cast<String, dynamic>()).url,
      ];
    } on Object {
      return const [];
    }
  }

  Future<void> _look() async {
    await _loadServer();
    final saved =
        Uri.tryParse(ref.read(settingsProvider).requestPortalUrl ?? '');
    final candidates = PortalDiscovery.nearbyAddresses(
      _endpoints,
      saved: saved != null && saved.host.isNotEmpty ? saved : null,
    );
    _asked = candidates;
    final found = candidates.isEmpty
        ? const <Uri>[]
        : await ref.read(portalDiscoveryProvider).findNearby(candidates);
    if (!mounted) return;
    setState(() {
      _found = found;
      _chosen = found.isEmpty ? null : found.first;
      _phase = found.isEmpty ? _Phase.none : _Phase.found;
    });
  }

  Future<void> _search() async {
    final around = _endpoints.isEmpty ? null : _endpoints.first;
    if (around == null) {
      setState(() => _phase = _Phase.typing);
      return;
    }
    _searchCancelled = false;
    setState(() {
      _phase = _Phase.searching;
      _progress = (done: 0, total: 253);
      _message = null;
    });
    final found = await ref.read(portalDiscoveryProvider).searchNetwork(
          around,
          alreadyAsked: {for (final u in _asked) u.host},
          isCancelled: () => _searchCancelled || !mounted,
          onProgress: (done, total) {
            if (mounted && done % 8 == 0) {
              setState(() => _progress = (done: done, total: total));
            }
          },
        );
    if (!mounted || _searchCancelled) return;
    setState(() {
      _searched = true;
      _found = found;
      _chosen = found.isEmpty ? null : found.first;
      _phase = found.isEmpty ? _Phase.none : _Phase.found;
      _message = found.isEmpty
          ? 'Nothing that looks like a download service answered on your '
              'network.'
          : null;
    });
  }

  Future<void> _checkTyped() async {
    final uri = parseServiceAddress(_address.text);
    if (uri == null) {
      setState(
          () => _message = 'Enter the address, for example 192.168.1.10:8700');
      return;
    }
    final problem = cleartextProblem(uri);
    if (problem != null) {
      setState(() => _message = problem);
      return;
    }
    setState(() {
      _phase = _Phase.connecting;
      _message = null;
    });
    final result = await ref.read(portalProbeProvider).probe(uri);
    if (!mounted) return;
    if (result.isService) {
      _chosen = uri;
      _found = [uri];
      await _connect();
      return;
    }
    setState(() {
      _phase = _Phase.typing;
      _message = describeProbe(uri, result);
    });
  }

  /// Signs in. Without [user] the music server's own login is tried (when the
  /// policy allows it); with [user] and [password] those are used.
  Future<void> _connect({String? user, String? password}) async {
    final target = _chosen;
    if (target == null) return;
    final server = _server;
    final reuse = user == null;
    final store = ref.read(credentialStoreProvider);
    String? login = user;
    String? secret = password;
    if (reuse) {
      if (server == null || !mayReuseServerLogin(target, _endpoints)) {
        setState(() {
          _phase = _Phase.login;
          _message = 'This address is not on your music server\'s network, '
              'so enter the login of the download service.';
        });
        return;
      }
      login = server.username;
      secret = await store.readPassword(server.id);
    }
    if (login == null || login.isEmpty || secret == null || secret.isEmpty) {
      setState(() => _phase = _Phase.login);
      return;
    }
    setState(() {
      _phase = _Phase.connecting;
      _message = null;
    });
    final client = ref.read(portalClientFactoryProvider)(
      baseUrl: target,
      username: login,
      password: secret,
    );
    final result = await client.check();
    if (!mounted) return;
    switch (result) {
      case Ok():
        final settings = ref.read(settingsProvider.notifier);
        settings
          ..setRequestPortalUrl(target.toString())
          ..setRequestPortalUser(login)
          ..setRequestsEnabled(true);
        if (reuse) {
          // No password of its own: the service keeps taking the music
          // server's login, including after that one changes.
          await store.deleteSecret(kPortalPasswordKey);
        } else {
          await store.writeSecret(kPortalPasswordKey, secret);
        }
        ref.invalidate(requestBackendProvider);
        if (mounted) Navigator.of(context).pop(true);
      case Err(:final failure):
        setState(() {
          if (failure is AuthFailure) {
            _phase = _Phase.login;
            _message = reuse
                ? 'The download service is there, but it does not accept your '
                    'music server login. It may have its own accounts - enter '
                    'it here.'
                : 'The download service did not accept that login.';
          } else {
            _phase = _Phase.typing;
            _address.text = _hostPort(target);
            _message = describeFailure(target, failure);
          }
        });
    }
  }

  void _noService() {
    ref.read(settingsProvider.notifier).setRequestsEnabled(false);
    Navigator.of(context).pop(false);
  }

  // ---------------------------------------------------------------- UI

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.fromLTRB(
        Space.gutter,
        Space.lg,
        Space.gutter,
        MediaQuery.viewInsetsOf(context).bottom + Space.lg,
      ),
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Connect your download service',
                style: context.text.titleLarge),
            const SizedBox(height: Space.xs),
            Text(
              'Your music server plays what it already has. The download '
              'service is the part of your server that finds and downloads '
              'new music, so Request and Import can bring it in.',
              style: context.text.bodyMedium,
            ),
            const SizedBox(height: Space.lg),
            ..._body(context),
            const SizedBox(height: Space.md),
            Align(
              alignment: Alignment.centerLeft,
              child: TextButton(
                onPressed: _noService,
                child: const Text("I don't have one"),
              ),
            ),
          ],
        ),
      ),
    );
  }

  List<Widget> _body(BuildContext context) {
    final c = context.colors;
    Widget problem() => _message == null
        ? const SizedBox.shrink()
        : Padding(
            padding: const EdgeInsets.only(bottom: Space.md),
            child: Text(_message!,
                style: context.text.bodyMedium?.copyWith(color: c.danger)),
          );

    switch (_phase) {
      case _Phase.looking:
        return [
          Row(children: [
            const SizedBox.square(
                dimension: 20,
                child: CircularProgressIndicator(strokeWidth: 2)),
            const SizedBox(width: Space.md),
            Expanded(
              child: Text('Looking for it next to your music server...',
                  style: context.text.bodyLarge),
            ),
          ]),
        ];

      case _Phase.found:
        return [
          problem(),
          for (final uri in _found)
            RadioListTile<Uri>(
              contentPadding: EdgeInsets.zero,
              value: uri,
              // ignore: deprecated_member_use
              groupValue: _chosen,
              // ignore: deprecated_member_use
              onChanged: (v) => setState(() => _chosen = v),
              title: Text(_found.length == 1
                  ? 'Found your download service'
                  : _hostPort(uri)),
              subtitle: Text(_hostPort(uri)),
            ),
          const SizedBox(height: Space.sm),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              onPressed: _chosen == null ? null : () => _connect(),
              child: const Text('Connect'),
            ),
          ),
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton(
              onPressed: () => setState(() => _phase = _Phase.typing),
              child: const Text('Use another address'),
            ),
          ),
        ];

      case _Phase.none:
        return [
          problem(),
          Text(
            _searched
                ? 'You can still type its address.'
                : 'Nothing is answering at '
                    '${_asked.map(_hostPort).join(', ')}. The download '
                    'service is often on another machine than your music '
                    'server.',
            style: context.text.bodyLarge,
          ),
          const SizedBox(height: Space.md),
          Wrap(spacing: Space.sm, children: [
            if (!_searched &&
                PortalDiscovery.subnetHosts(
                        _endpoints.isEmpty ? '' : _endpoints.first.host)
                    .isNotEmpty)
              FilledButton.icon(
                onPressed: _search,
                icon: const Icon(Icons.travel_explore_rounded),
                label: const Text('Search my network'),
              ),
            OutlinedButton(
              onPressed: () => setState(() => _phase = _Phase.typing),
              child: const Text('Type the address'),
            ),
          ]),
        ];

      case _Phase.searching:
        final p = _progress;
        return [
          LinearProgressIndicator(
            value: p == null || p.total == 0 ? null : p.done / p.total,
            borderRadius: BorderRadius.circular(Radii.pill),
          ),
          const SizedBox(height: Space.sm),
          Text(
            p == null
                ? 'Looking on your network...'
                : 'Looking on your network... ${p.done} of ${p.total}',
            style: context.text.bodyMedium,
          ),
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton(
              onPressed: () {
                _searchCancelled = true;
                setState(() => _phase = _Phase.none);
              },
              child: const Text('Cancel'),
            ),
          ),
        ];

      case _Phase.typing:
        return [
          TextField(
            controller: _address,
            keyboardType: TextInputType.url,
            autocorrect: false,
            autofocus: true,
            decoration: const InputDecoration(
              labelText: 'Address',
              hintText: '192.168.1.10:8700',
            ),
            onSubmitted: (_) => _checkTyped(),
          ),
          const SizedBox(height: Space.sm),
          problem(),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              onPressed: _checkTyped,
              child: const Text('Check and connect'),
            ),
          ),
        ];

      case _Phase.connecting:
        return [
          Row(children: [
            const SizedBox.square(
                dimension: 20,
                child: CircularProgressIndicator(strokeWidth: 2)),
            const SizedBox(width: Space.md),
            Text('Signing in...', style: context.text.bodyLarge),
          ]),
        ];

      case _Phase.login:
        return [
          problem(),
          TextField(
            controller: _user,
            autocorrect: false,
            decoration: const InputDecoration(labelText: 'Username'),
          ),
          TextField(
            controller: _password,
            obscureText: true,
            decoration: const InputDecoration(labelText: 'Password'),
            onSubmitted: (_) =>
                _connect(user: _user.text.trim(), password: _password.text),
          ),
          const SizedBox(height: Space.md),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              onPressed: () =>
                  _connect(user: _user.text.trim(), password: _password.text),
              child: const Text('Sign in'),
            ),
          ),
        ];
    }
  }
}

/// `host:port`, leaving out the scheme and the default ports.
String _hostPort(Uri uri) {
  final defaultPort = uri.scheme == 'https' ? 443 : 80;
  return uri.hasPort && uri.port != defaultPort
      ? '${uri.host}:${uri.port}'
      : uri.host;
}

/// What people type: `192.168.1.10`, `192.168.1.10:8700`,
/// `http://nas.local:8700/`. A bare host gets the usual port. `null` when it
/// cannot be an address.
Uri? parseServiceAddress(String input) {
  final typed = input.trim();
  if (typed.isEmpty) return null;
  final withScheme = typed.contains('://');
  final uri = Uri.tryParse(withScheme ? typed : 'http://$typed');
  if (uri == null || uri.host.isEmpty) return null;
  if (uri.scheme != 'http' && uri.scheme != 'https') return null;
  // A scheme typed without a port means that scheme's own port (a reverse
  // proxy in front of the service); a bare host gets the usual port.
  final port = withScheme ? uri.port : (uri.hasPort ? uri.port : 8700);
  return Uri(
    scheme: uri.scheme,
    host: uri.host,
    port: port,
    path: uri.path.replaceAll(RegExp(r'/+$'), ''),
  );
}

/// The sentence for "this address is not the download service".
String describeProbe(Uri uri, ProbeResult result) {
  final where = _hostPort(uri);
  switch (result.verdict) {
    case ProbeVerdict.service:
      return '$where is the download service.';
    case ProbeVerdict.other:
      return result.reason == 'page'
          ? '$where answers, but it is not a download service (it returned '
              'a web page).'
          : '$where answers, but it is not a download service.';
    case ProbeVerdict.silent:
      return switch (result.reason) {
        'refused' => 'Nothing is listening at $where.',
        'timeout' => '$where did not answer in time. Is it switched on, and '
            'are you on your home network or Tailscale?',
        _ => 'Cannot reach $where. Are you on your home network or '
            'Tailscale?',
      };
  }
}

/// The sentence for a failure after the address was accepted.
String describeFailure(Uri uri, AppFailure failure) {
  final where = _hostPort(uri);
  if (failure is NetworkFailure) {
    return 'Cannot reach $where right now. Are you on your home network or '
        'Tailscale?';
  }
  if (failure is ServerFailure) {
    final code = failure.statusCode;
    if (code == 429) {
      return 'The download service says there were too many sign-in '
          'attempts. Wait ten minutes and try again.';
    }
    return 'The download service reported a problem'
        '${code == null ? '' : ' ($code)'}. Try again in a minute.';
  }
  return failure.message;
}
