import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/providers.dart';
import '../../core/result.dart';
import '../../data/auth/server_setup_service.dart';
import '../../data/encore/encore_device.dart';
import '../../data/people/people_join_client.dart';
import '../../data/sync/endpoint_resolver.dart';
import '../../design/tokens.dart';
import '../../domain/invite_link.dart';
import '../../domain/new_account_rules.dart';
import '../people/people_providers.dart';

/// Joining a server somebody invited the person to (docs/39 F3): the invitation
/// link is read by the app, the person chooses a username and a password once,
/// and is signed in. No browser, no second link, no second password screen.
class JoinScreen extends ConsumerStatefulWidget {
  const JoinScreen({super.key, required this.link});

  final InviteLink link;

  @override
  ConsumerState<JoinScreen> createState() => _JoinScreenState();
}

/// How long to wait between the automatic tries to reach the server for an invitation. A phone that has just changed from Wi-Fi to mobile
/// data (or back) often has no usable network for a few seconds when the link is tapped; trying again by itself spares the person a failure
/// screen on the very first minute. Only the look at the invitation is repeated: making the account is never retried by itself, because the
/// server may already have made it.
final joinRetryDelaysProvider = Provider<List<Duration>>(
  (ref) =>
      const [Duration(seconds: 2), Duration(seconds: 4), Duration(seconds: 8)],
);

/// Capital letters are made small as they are typed: the first letter of a
/// name is a capital on most keyboards, and the server takes lower case only.
final _lowerCase = TextInputFormatter.withFunction(
  (before, after) => after.copyWith(text: after.text.toLowerCase()),
);

class _JoinScreenState extends ConsumerState<JoinScreen> {
  final _user = TextEditingController();
  final _password = TextEditingController();
  final _formKey = GlobalKey<FormState>();

  InvitationInfo? _info;
  AppFailure? _problem;
  bool _checking = true;
  bool _reaching = false;
  bool _busy = false;
  bool _obscure = true;
  String? _step;
  String? _error;

  @override
  void initState() {
    super.initState();
    _check();
  }

  @override
  void dispose() {
    _user.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _check() async {
    setState(() {
      _checking = true;
      _reaching = false;
      _problem = null;
    });
    final delays = ref.read(joinRetryDelaysProvider);
    var result = await ref.read(peopleJoinClientProvider).info(widget.link);
    for (final pause in delays) {
      if (!mounted) return;
      if (result case Err(:final failure) when failure is NetworkFailure) {
        setState(() => _reaching = true);
        await Future<void>.delayed(pause);
        if (!mounted) return;
        result = await ref.read(peopleJoinClientProvider).info(widget.link);
      } else {
        break;
      }
    }
    if (!mounted) return;
    setState(() {
      _checking = false;
      _reaching = false;
      switch (result) {
        case Ok(:final value):
          _info = value;
        case Err(:final failure):
          _problem = failure;
      }
    });
  }

  Future<void> _join() async {
    if (!_formKey.currentState!.validate()) return;
    final name = suggestUsername(_user.text);
    final password = _password.text;
    setState(() {
      _busy = true;
      _error = null;
      _step = 'Making your account…';
    });

    final joined = await ref
        .read(peopleJoinClientProvider)
        .redeem(widget.link, username: name, password: password);
    if (!mounted) return;
    if (joined case Err(:final failure)) {
      setState(() {
        _busy = false;
        _step = null;
        _error = failure.message;
      });
      return;
    }
    final account = (joined as Ok<JoinedAccount>).value;

    setState(() => _step = 'Signing you in…');
    final address = ServerSetupService.normalizeUrl(
          '${account.address ?? _info?.address ?? widget.link.server}',
        ) ??
        widget.link.server;
    final endpoints = [
      ServerEndpoint(
          label: ServerSetupService.firstAddressLabel(address), url: address),
    ];
    final service = ref.read(serverSetupServiceProvider);
    final checked = await service.check(
      endpoints: endpoints,
      username: account.username,
      password: password,
    );
    if (!mounted) return;
    switch (checked) {
      case Err():
        // The account exists (the invitation is used): say how to go on.
        setState(() {
          _busy = false;
          _step = null;
          _error = 'Your account "${account.username}" is made, but signing '
              'in did not work just now. Tap "I already have an account" and '
              'sign in with the name and password you just chose.';
        });
      case Ok(:final value):
        final serverId = await service.save(
          name: _info?.serverName.isNotEmpty == true
              ? _info!.serverName
              : 'My music server',
          endpoints: endpoints,
          username: account.username,
          password: password,
          ping: value.ping,
        );
        // The device the server made while it made the account is this phone's: keep it, so the live channel does not sign in again.
        final token = account.deviceToken;
        if (token != null) {
          await ref.read(credentialStoreProvider).writeSecret(
              EncoreDevice.secretKey(serverId),
              EncoreDevice.encode(token, account.deviceId));
        }
        // On a device that already had somebody, the new person is the one listening now.
        if (mounted) context.go('/home');
    }
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
              child: _checking
                  ? _Waiting(
                      text: _reaching
                          ? 'Reaching the server…'
                          : 'Checking your invitation…',
                      color: c.accent)
                  : _info == null
                      ? _Unusable(
                          failure: _problem,
                          onRetry: _problem is NetworkFailure ? _check : null,
                        )
                      : _form(context),
            ),
          ),
        ),
      ),
    );
  }

  Widget _form(BuildContext context) {
    final c = context.colors;
    final info = _info!;
    final who = info.inviter.isEmpty ? 'Somebody' : info.inviter;
    final where = info.serverName.isEmpty ? 'this server' : info.serverName;
    return Form(
      key: _formKey,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Icon(Icons.graphic_eq_rounded, size: 48, color: c.accent),
          const SizedBox(height: Space.lg),
          Text('Join $where', style: context.text.headlineMedium),
          const SizedBox(height: Space.xs),
          Text(
            '$who invited you. Choose a username and a password: that is all.',
            style: context.text.titleMedium,
          ),
          const SizedBox(height: Space.xl),
          TextFormField(
            controller: _user,
            enabled: !_busy,
            autocorrect: false,
            enableSuggestions: false,
            textInputAction: TextInputAction.next,
            inputFormatters: [_lowerCase],
            autofillHints: const [AutofillHints.newUsername],
            decoration: const InputDecoration(
              labelText: 'Username',
              helperText: 'Letters and digits, no capitals or spaces',
            ),
            validator: (v) => checkNewUsername(suggestUsername(v ?? '')),
          ),
          const SizedBox(height: Space.md),
          TextFormField(
            controller: _password,
            enabled: !_busy,
            obscureText: _obscure,
            autofillHints: const [AutofillHints.newPassword],
            decoration: InputDecoration(
              labelText: 'Password',
              helperText: 'At least 8 characters',
              suffixIcon: IconButton(
                tooltip: _obscure ? 'Show password' : 'Hide password',
                icon: Icon(_obscure
                    ? Icons.visibility_outlined
                    : Icons.visibility_off_outlined),
                onPressed: () => setState(() => _obscure = !_obscure),
              ),
            ),
            validator: (v) => checkNewPassword(v ?? ''),
            onFieldSubmitted: (_) => _join(),
          ),
          const SizedBox(height: Space.xl),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.only(bottom: Space.lg),
              child: Text(_error!,
                  style: context.text.bodyMedium?.copyWith(color: c.danger)),
            ),
          FilledButton(
            onPressed: _busy ? null : _join,
            style:
                FilledButton.styleFrom(minimumSize: const Size.fromHeight(52)),
            child: _busy
                ? Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      const SizedBox.square(
                        dimension: 18,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      ),
                      const SizedBox(width: Space.md),
                      Flexible(
                        child: Text(_step ?? 'Joining…',
                            overflow: TextOverflow.ellipsis),
                      ),
                    ],
                  )
                : const Text('Join'),
          ),
          const SizedBox(height: Space.sm),
          TextButton(
            onPressed: _busy ? null : () => context.go('/onboarding'),
            child: const Text('I already have an account'),
          ),
        ],
      ),
    );
  }
}

class _Waiting extends StatelessWidget {
  const _Waiting({required this.text, required this.color});

  final String text;
  final Color color;

  @override
  Widget build(BuildContext context) => Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.graphic_eq_rounded, size: 48, color: color),
          const SizedBox(height: Space.lg),
          const SizedBox.square(
            dimension: 22,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
          const SizedBox(height: Space.md),
          Text(text, style: context.text.bodyMedium),
        ],
      );
}

/// The invitation cannot be used: said in the words of whoever knows why, with
/// the way on.
class _Unusable extends StatelessWidget {
  const _Unusable({required this.failure, required this.onRetry});

  final AppFailure? failure;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Icon(Icons.link_off_rounded, size: 48, color: c.accent),
        const SizedBox(height: Space.lg),
        Text('This invitation did not open',
            style: context.text.headlineMedium),
        const SizedBox(height: Space.md),
        Text(failure?.message ?? 'Something went wrong.',
            style: context.text.bodyLarge),
        const SizedBox(height: Space.xl),
        if (onRetry != null)
          FilledButton(
            onPressed: onRetry,
            style:
                FilledButton.styleFrom(minimumSize: const Size.fromHeight(52)),
            child: const Text('Try again'),
          ),
        TextButton(
          onPressed: () => context.go('/onboarding'),
          child: const Text('I already have an account'),
        ),
      ],
    );
  }
}
