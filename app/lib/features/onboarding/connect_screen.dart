import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/branding.dart';
import '../../app/providers.dart';
import '../../core/result.dart';
import '../../data/auth/server_setup_service.dart';
import '../../data/sync/endpoint_resolver.dart';
import '../../design/tokens.dart';
import '../../domain/connect_link.dart';
import '../../domain/invite_link.dart';

/// What a music server is, for someone who has never run one and was just
/// handed an address (ADR-068). Folded away until they want it.
class _WhatIsAServer extends StatelessWidget {
  const _WhatIsAServer();

  @override
  Widget build(BuildContext context) {
    return Theme(
      data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
      child: ExpansionTile(
        tilePadding: EdgeInsets.zero,
        childrenPadding: EdgeInsets.zero,
        title: Text('New here? What is a music server?',
            style: context.text.titleSmall),
        children: [
          Align(
            alignment: Alignment.centerLeft,
            child: Text(
              'Encore plays music from a server: a small computer at home '
              '(or in the cloud) that keeps the music, like a private '
              'Spotify. You, or someone you know, runs it, and they will give '
              'you three things: an address, a username and a password.\n\n'
              'Your login stays on this phone. Encore only ever sends it to '
              'your own server.\n\n'
              'Want to run one yourself? It takes about fifteen minutes - '
              'Navidrome is the server Encore is tested with, and any server '
              'that speaks the Subsonic protocol works.',
              style: context.text.bodyMedium,
            ),
          ),
          const SizedBox(height: Space.sm),
        ],
      ),
    );
  }
}

/// One-screen connect flow (docs/06-ux-spec.md 4.10): address, user, password;
/// optional second address (e.g. Tailscale). Shows each verification step and
/// then drops the user into Home while the first sync runs in the background.
class ConnectScreen extends ConsumerStatefulWidget {
  const ConnectScreen({super.key});

  @override
  ConsumerState<ConnectScreen> createState() => _ConnectScreenState();
}

class _ConnectScreenState extends ConsumerState<ConnectScreen> {
  final _address = TextEditingController();
  final _address2 = TextEditingController();
  final _label2 = TextEditingController(text: 'Tailscale');
  final _user = TextEditingController();
  final _password = TextEditingController();
  final _passwordFocus = FocusNode();
  final _userFocus = FocusNode();
  final _formKey = GlobalKey<FormState>();

  bool _showSecond = false;
  bool _obscure = true;
  bool _busy = false;
  String? _step;
  String? _error;

  @override
  void dispose() {
    for (final c in [_address, _address2, _label2, _user, _password]) {
      c.dispose();
    }
    _passwordFocus.dispose();
    _userFocus.dispose();
    super.dispose();
  }

  /// "Got a setup link?": fills in what the sender knew, so only the password
  /// is left to type.
  Future<void> _pasteLink() async {
    final messenger = ScaffoldMessenger.of(context);
    final data = await Clipboard.getData(Clipboard.kTextPlain);
    if (!mounted) return;
    // An invitation (a link to join, made by somebody who runs the server)
    // opens the app's own sign-up: no browser, no second link.
    final invite = findInviteLink(data?.text ?? '');
    if (invite != null) {
      context.go('/join', extra: invite);
      return;
    }
    final link = findConnectLink(data?.text ?? '');
    if (link == null) {
      messenger
        ..hideCurrentSnackBar()
        ..showSnackBar(const SnackBar(
          content: Text('No setup link found. Copy the message you were '
              'sent, then tap here again.'),
        ));
      return;
    }
    setState(() {
      _error = null;
      _address.text = link.server;
      if (link.away != null) {
        _showSecond = true;
        _address2.text = link.away!;
        _label2.text = 'Away from home';
      }
      if (link.user != null) _user.text = link.user!;
    });
    (link.user == null ? _userFocus : _passwordFocus).requestFocus();
    messenger
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(
        content: Text(link.user == null
            ? 'Got it. Now type your username and password.'
            : 'Got it. Now type your password.'),
      ));
  }

  Future<void> _connect() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _busy = true;
      _error = null;
      _step = 'Looking for your server…';
    });

    final service = ref.read(serverSetupServiceProvider);
    final primary = ServerSetupService.normalizeUrl(_address.text)!;
    final endpoints = [
      ServerEndpoint(
          label: ServerSetupService.firstAddressLabel(primary), url: primary),
      if (_showSecond && _address2.text.trim().isNotEmpty)
        if (ServerSetupService.normalizeUrl(_address2.text) case final u?)
          ServerEndpoint(
            label: _label2.text.trim().isEmpty ? 'Away' : _label2.text.trim(),
            url: u,
          ),
    ];

    final result = await service.check(
      endpoints: endpoints,
      username: _user.text.trim(),
      password: _password.text,
      onStep: (s) {
        if (mounted) setState(() => _step = s);
      },
    );

    if (!mounted) return;
    switch (result) {
      case Err(:final failure):
        setState(() {
          _busy = false;
          _step = null;
          _error = _explain(failure, primary);
        });
      case Ok(:final value):
        setState(() => _step = 'Saving…');
        // Only keep addresses that actually answered, plus the primary.
        final keep = [
          for (final e in endpoints)
            if (value.reachableEndpoints.contains(e) || e == endpoints.first) e,
        ];
        await service.save(
          name: 'My music server',
          endpoints: keep,
          username: _user.text.trim(),
          password: _password.text,
          ping: value.ping,
        );
      // activeServerProvider emits; the router leaves onboarding.
    }
  }

  String _explain(AppFailure failure, Uri url) {
    return switch (failure) {
      AuthFailure() => 'The server is there, but the username or password was '
          'not accepted.',
      NetworkFailure() => "Can't reach ${url.host}. Are you on the same "
          'network (or connected through Tailscale)?',
      _ => failure.message,
    };
  }

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(Space.xl),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Form(
                key: _formKey,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Icon(Icons.graphic_eq_rounded, size: 48, color: c.accent),
                    const SizedBox(height: Space.lg),
                    Text('Welcome to ${AppBranding.name}',
                        style: context.text.headlineMedium),
                    const SizedBox(height: Space.xs),
                    Text('Your music, from your own server.',
                        style: context.text.titleMedium),
                    const SizedBox(height: Space.xs),
                    Text(
                      'Ask whoever set it up for the address, your username '
                      'and your password.',
                      style: context.text.bodyMedium,
                    ),
                    const SizedBox(height: Space.sm),
                    Align(
                      alignment: Alignment.centerLeft,
                      child: TextButton.icon(
                        onPressed: _busy ? null : _pasteLink,
                        icon: const Icon(Icons.content_paste_rounded, size: 18),
                        label: const Text('Got a setup link? Paste it'),
                      ),
                    ),
                    const _WhatIsAServer(),
                    const SizedBox(height: Space.md),
                    TextFormField(
                      controller: _address,
                      enabled: !_busy,
                      keyboardType: TextInputType.url,
                      autocorrect: false,
                      decoration: const InputDecoration(
                        labelText: 'Server address',
                        helperText: 'For example 192.168.1.10:4533',
                      ),
                      validator: (v) =>
                          ServerSetupService.validateAddress(v ?? ''),
                    ),
                    const SizedBox(height: Space.md),
                    TextFormField(
                      controller: _user,
                      focusNode: _userFocus,
                      enabled: !_busy,
                      autocorrect: false,
                      autofillHints: const [AutofillHints.username],
                      decoration: const InputDecoration(labelText: 'Username'),
                      validator: (v) => (v ?? '').trim().isEmpty
                          ? 'Enter your username'
                          : null,
                    ),
                    const SizedBox(height: Space.md),
                    TextFormField(
                      controller: _password,
                      focusNode: _passwordFocus,
                      enabled: !_busy,
                      obscureText: _obscure,
                      autofillHints: const [AutofillHints.password],
                      decoration: InputDecoration(
                        labelText: 'Password',
                        suffixIcon: IconButton(
                          tooltip: _obscure ? 'Show password' : 'Hide password',
                          icon: Icon(_obscure
                              ? Icons.visibility_outlined
                              : Icons.visibility_off_outlined),
                          onPressed: () => setState(() => _obscure = !_obscure),
                        ),
                      ),
                      validator: (v) =>
                          (v ?? '').isEmpty ? 'Enter your password' : null,
                      onFieldSubmitted: (_) => _connect(),
                    ),
                    if (_showSecond) ...[
                      const SizedBox(height: Space.lg),
                      Text('Second address', style: context.text.titleSmall),
                      const SizedBox(height: Space.sm),
                      TextFormField(
                        controller: _address2,
                        enabled: !_busy,
                        keyboardType: TextInputType.url,
                        decoration: const InputDecoration(
                          labelText: 'Address when away from home',
                          hintText: '100.64.0.5:4533',
                        ),
                      ),
                      const SizedBox(height: Space.md),
                      TextFormField(
                        controller: _label2,
                        enabled: !_busy,
                        decoration:
                            const InputDecoration(labelText: 'Name (optional)'),
                      ),
                    ] else
                      Align(
                        alignment: Alignment.centerLeft,
                        child: TextButton(
                          onPressed: _busy
                              ? null
                              : () => setState(() => _showSecond = true),
                          child: const Text('Add another address (for when '
                              'you are away from home)'),
                        ),
                      ),
                    const SizedBox(height: Space.xl),
                    if (_error != null)
                      Padding(
                        padding: const EdgeInsets.only(bottom: Space.lg),
                        child: Text(_error!,
                            style: context.text.bodyMedium
                                ?.copyWith(color: c.danger)),
                      ),
                    FilledButton(
                      onPressed: _busy ? null : _connect,
                      style: FilledButton.styleFrom(
                        minimumSize: const Size.fromHeight(52),
                      ),
                      child: _busy
                          ? Row(
                              mainAxisAlignment: MainAxisAlignment.center,
                              children: [
                                const SizedBox.square(
                                  dimension: 18,
                                  child:
                                      CircularProgressIndicator(strokeWidth: 2),
                                ),
                                const SizedBox(width: Space.md),
                                Flexible(
                                  child: Text(_step ?? 'Connecting…',
                                      overflow: TextOverflow.ellipsis),
                                ),
                              ],
                            )
                          : const Text('Connect'),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
