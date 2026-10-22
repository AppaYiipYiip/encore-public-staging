import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/providers.dart';
import '../../core/result.dart';
import '../../design/tokens.dart';
import '../settings/sign_out.dart';

/// Whether the server refuses this phone's login, and whether the person has just tried to do something because of it.
class LoginState {
  const LoginState({this.rejected = false, this.prompts = 0});

  /// The server did not accept the saved password (it was changed, or the account is gone).
  final bool rejected;

  /// Counts the times an action the person took failed for that reason: each one opens the sign-in prompt once.
  final int prompts;

  LoginState copyWith({bool? rejected, int? prompts}) => LoginState(
      rejected: rejected ?? this.rejected, prompts: prompts ?? this.prompts);
}

/// The one place that knows the login stopped working (P2-18, E23). Before it, a changed password showed Home with "Synced 3 d
/// ago" and no prompt, a song row said "the instant-play service did not accept ...", and the only way out was Sign out, which
/// deleted every download. Now every part of the app that is refused says so here, and the person sees one state: sign in again.
class LoginProblem extends Notifier<LoginState> {
  @override
  LoginState build() {
    ref.listen(syncStatusProvider, (previous, next) {
      final status = next.value;
      if (status == null) return;
      if (status.lastFailure is AuthFailure) {
        state = state.copyWith(rejected: true);
      } else if (status.lastSuccessAt != null &&
          status.lastSuccessAt != previous?.value?.lastSuccessAt) {
        state = state.copyWith(rejected: false);
      }
    });
    final now = ref.read(syncStatusProvider).value;
    return LoginState(rejected: now?.lastFailure is AuthFailure);
  }

  /// Something was refused for this reason. [fromAction]: the person was doing it (a song they tapped), so the prompt opens.
  void rejected({bool fromAction = false}) {
    state = state.copyWith(
      rejected: true,
      prompts: fromAction ? state.prompts + 1 : state.prompts,
    );
  }

  /// A new password was accepted.
  void accepted() => state = state.copyWith(rejected: false);
}

final loginProblemProvider =
    NotifierProvider<LoginProblem, LoginState>(LoginProblem.new);

/// A quiet card on Home while the login is refused (never a sentence on a row).
class LoginProblemBanner extends ConsumerWidget {
  const LoginProblemBanner({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (!ref.watch(loginProblemProvider.select((s) => s.rejected))) {
      return const SizedBox.shrink();
    }
    final c = context.colors;
    return Padding(
      padding: const EdgeInsets.fromLTRB(
          Space.gutter, Space.sm, Space.gutter, Space.sm),
      child: Material(
        key: const Key('login-problem-banner'),
        color: c.surfaceHigh,
        borderRadius: BorderRadius.circular(Radii.card),
        child: InkWell(
          borderRadius: BorderRadius.circular(Radii.card),
          onTap: () => context.push('/sign-in-again'),
          child: Padding(
            padding: const EdgeInsets.all(Space.md),
            child: Row(
              children: [
                Icon(Icons.lock_outline_rounded, color: c.accent),
                const SizedBox(width: Space.md),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('Sign in again',
                          style: context.text.titleMedium
                              ?.copyWith(fontWeight: FontWeight.w700)),
                      Text(
                        'Your server did not accept the saved password. '
                        'Your music, downloads and playlists on this phone are kept.',
                        style: context.text.bodyMedium
                            ?.copyWith(color: c.onBgMuted),
                      ),
                    ],
                  ),
                ),
                const Icon(Icons.chevron_right_rounded),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// The new password, nothing else: the account, the library, the downloads and the queue stay as they are.
class SignInAgainScreen extends ConsumerStatefulWidget {
  const SignInAgainScreen({super.key});

  @override
  ConsumerState<SignInAgainScreen> createState() => _SignInAgainScreenState();
}

class _SignInAgainScreenState extends ConsumerState<SignInAgainScreen> {
  final _password = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _password.dispose();
    super.dispose();
  }

  Future<void> _signIn() async {
    final server = ref.read(activeServerProvider).value;
    if (server == null || _password.text.isEmpty) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    final result = await ref
        .read(serverSetupServiceProvider)
        .replacePassword(server, _password.text);
    if (!mounted) return;
    switch (result) {
      case Err(:final failure):
        setState(() {
          _busy = false;
          _error = switch (failure) {
            AuthFailure() =>
              'That password was not accepted. Check it and try again.',
            NetworkFailure() =>
              'Cannot reach your server right now. Check your connection and try again.',
            _ => failure.message,
          };
        });
      case Ok():
        // A new session with the new password; the old data is untouched and syncs again at once.
        ref.invalidate(sessionProvider);
        ref.read(loginProblemProvider.notifier).accepted();
        context.pop();
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final server = ref.watch(activeServerProvider).value;
    return Scaffold(
      appBar: AppBar(title: const Text('Sign in again')),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(Space.xl),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                server == null
                    ? 'Your server did not accept the saved password.'
                    : '${server.name} did not accept the saved password. '
                        'It was probably changed.',
                style: context.text.bodyLarge,
              ),
              const SizedBox(height: Space.sm),
              Text(
                'Sign in with the new one. Your music, playlists, downloads and the song you were listening to stay as they are.',
                style: context.text.bodyMedium?.copyWith(color: c.onBgMuted),
              ),
              const SizedBox(height: Space.xl),
              if (server != null)
                InputDecorator(
                  decoration: const InputDecoration(labelText: 'Username'),
                  child: Text(server.username, style: context.text.bodyLarge),
                ),
              const SizedBox(height: Space.md),
              TextField(
                key: const Key('sign-in-again-password'),
                controller: _password,
                obscureText: true,
                autofocus: true,
                enabled: !_busy,
                textInputAction: TextInputAction.done,
                onSubmitted: (_) => _signIn(),
                decoration: InputDecoration(
                  labelText: 'Password',
                  errorText: _error,
                  errorMaxLines: 3,
                ),
              ),
              const SizedBox(height: Space.lg),
              FilledButton(
                onPressed: _busy ? null : _signIn,
                child: _busy
                    ? const SizedBox.square(
                        dimension: 20,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Text('Sign in'),
              ),
              const SizedBox(height: Space.xl),
              TextButton(
                onPressed: _busy ? null : () => confirmAndSignOut(context, ref),
                child: const Text('Use a different account'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
