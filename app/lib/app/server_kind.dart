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

/// The kind of the signed-in server, from the session (`ServerSession.encoreApi` is the one fact it is made of: non-null exactly when the kind is
/// [ServerKind.encore]; the mode behind it is private to the session).
/// A session that has never been built, or failed to build, is not known. **While the session is being REBUILT (the addresses were edited, the phone
/// was just moved onto an Encore server) the kind of the session it holds is kept**: the words of Home, the catalogue and Your server must not
/// flicker to "not an Encore server" for the moment of a reload. Tests replace it with `serverKindProvider.overrideWithValue(ServerKind.encore)`.
final serverKindProvider = Provider<ServerKind>((ref) {
  final async = ref.watch(sessionProvider);
  if (!async.hasValue) return ServerKind.detecting;
  final session = async.value;
  if (session == null) return ServerKind.plain;
  if (session.encoreApi != null) return ServerKind.encore;
  // `detecting` turns false when the phone has found out; the provider follows it.
  void changed() => ref.invalidateSelf();
  session.detecting.addListener(changed);
  ref.onDispose(() => session.detecting.removeListener(changed));
  return session.detecting.value ? ServerKind.detecting : ServerKind.plain;
});
