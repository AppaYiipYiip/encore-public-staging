import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/providers.dart';
import '../../core/logger.dart';
import '../../data/sync/pending_intent.dart';
import '../common/cover_art.dart';
import '../common/format.dart';
import '../downloads/download_providers.dart';
import '../providers.dart';
import '../requests/request_providers.dart';
import 'settings_controller.dart';

/// Empties the cover cache; a provider so tests (which have no platform
/// folders) can replace it.
final coverCacheClearerProvider =
    Provider<Future<void> Function()>((ref) => coverCacheManager.emptyCache);

/// Signs out: this phone forgets the account (ADR-068).
///
/// Removed: the login, the phone's copy of the library, everything downloaded
/// for offline listening, the queue that was waiting to resume, the cover
/// cache and the settings that belong to the account (download service, request
/// portal). Not touched: the music server - the music, the playlists, the
/// likes. Signing in again brings the library back on the next sync.
///
/// Every step is best effort except the last: a step that fails must not leave
/// the person unable to sign out. The server is removed last because the app
/// returns to the sign-in screen the moment it is gone.
Future<void> signOut(WidgetRef ref) async {
  final server = await ref.read(activeServerProvider.future);
  if (server == null) return;

  Future<void> step(String name, Future<void> Function() body) async {
    try {
      await body();
    } on Object catch (error) {
      Log.warn('signout', '$name failed: $error');
    }
  }

  final facade = ref.read(playbackFacadeProvider);
  final downloads = ref.read(downloadActionsProvider);
  final credentials = ref.read(credentialStoreProvider);
  final settings = ref.read(settingsProvider.notifier);
  final setup = ref.read(serverSetupServiceProvider);

  await step('stop playback', facade.stopAndClear);
  // This phone's device on the server ends (DV-2): its token stops working and it leaves the person's list of devices.
  await step(
      "end this phone's sign-in on the server",
      () async =>
          ref.read(sessionProvider).value?.endDevice() ?? Future<void>.value());
  await step('delete downloads', downloads.removeAll);
  await step('forget the request portal login',
      () => credentials.deleteSecret(kPortalPasswordKey));
  await step('clear the cover cache', ref.read(coverCacheClearerProvider));
  settings.forgetServer();
  await setup.remove(server.id);
}

/// Asks first, in words that say what happens to what (the music stays on the
/// server; only this phone's copy goes), then signs out.
Future<void> confirmAndSignOut(BuildContext context, WidgetRef ref) async {
  final server = ref.read(activeServerProvider).value;
  if (server == null) return;
  final used = await ref.read(downloadsRepositoryProvider)?.usedBytes() ?? 0;
  final unsent = await unsentEditCount(ref.read(databaseProvider), server.id);
  if (!context.mounted) return;

  final sure = await showDialog<bool>(
    context: context,
    builder: (dialog) => AlertDialog(
      title: Text('Sign out of ${server.name}?'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('Your music and playlists stay on your server.'),
          const SizedBox(height: 12),
          const Text('This phone forgets your login and removes its copy of '
              'your library.'),
          if (used > 0) ...[
            const SizedBox(height: 12),
            Text('The ${formatBytes(used)} of music you downloaded for '
                'offline listening is deleted from this phone.'),
          ],
          const SizedBox(height: 12),
          if (unsent > 0) ...[
            const SizedBox(height: 12),
            Text('$unsent ${unsent == 1 ? 'change has' : 'changes have'} not '
                'reached your server yet and ${unsent == 1 ? 'is' : 'are'} '
                'lost if you sign out.'),
          ],
          const Text('You can sign in again any time.'),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(dialog).pop(false),
          child: const Text('Cancel'),
        ),
        FilledButton(
          onPressed: () => Navigator.of(dialog).pop(true),
          child: const Text('Sign out'),
        ),
      ],
    ),
  );
  if (sure != true || !context.mounted) return;
  // Others on this device: afterwards the picker asks who listens now, instead of quietly carrying on as somebody else.
  final others = (ref.read(profilesProvider).value?.length ?? 1) > 1;
  final router = GoRouter.maybeOf(context);
  unawaited(signOut(ref).then((_) {
    if (others) router?.go('/profiles');
  }));
}
