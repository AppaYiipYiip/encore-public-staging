import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'providers.dart';

/// Which kind of server the phone is talking to (P1-17, AUDIT B-17): the ONE answer every screen and provider that words itself or offers
/// something by kind reads, instead of asking the session, the instant-play backend or the old request portal.
enum ServerKind {
  /// Not known yet: the session is still being built, or the phone has not yet found out whether the server is an Encore server (the first
  /// minutes after a sign-in, or a server that did not answer definitely, AUDIT B-78). A tap on a catalogue song WAITS for this to end
  /// instead of giving up (D-24); nothing that is only for one kind is offered.
  detecting,

  /// A plain music server (the phone KNOWS it is not an Encore server), or no server at all: nothing that needs an Encore server is offered.
  plain,

  /// An Encore server and this phone has been moved over to it: songs are references the server plays itself, playing does not save, there is
  /// no helper service to find.
  encore,
}

/// The kind of the signed-in server, from the session (`ServerSession.encoreMode` is the session's own construction fact: it decides which
/// clients the session builds, and code that already holds the session and needs `session.encore` may read it; everything else reads this).
/// A session that failed to build is not known either. Tests replace it with `serverKindProvider.overrideWithValue(ServerKind.encore)`.
final serverKindProvider = Provider<ServerKind>((ref) {
  final async = ref.watch(sessionProvider);
  if (async.isLoading || async.hasError) return ServerKind.detecting;
  final session = async.value;
  if (session == null) return ServerKind.plain;
  if (session.encoreMode) return ServerKind.encore;
  // `detecting` turns false when the phone has found out; the provider follows it.
  void changed() => ref.invalidateSelf();
  session.detecting.addListener(changed);
  ref.onDispose(() => session.detecting.removeListener(changed));
  return session.detecting.value ? ServerKind.detecting : ServerKind.plain;
});
