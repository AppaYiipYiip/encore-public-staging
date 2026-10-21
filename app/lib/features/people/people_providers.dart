import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../core/logger.dart';
import '../../core/result.dart';
import '../../data/people/activity_publisher.dart';
import '../../data/people/people_client.dart';
import '../../data/people/people_join_client.dart';
import '../instant/instant_controller.dart' show jsonDecodeEndpoints;
import '../player/playback_facade.dart';
import '../player/streamed_song.dart';
import '../providers.dart';
import '../settings/settings_controller.dart';
import 'listening.dart';

/// The friend's side of an invitation: makes the account from inside the app
/// (docs/39 F3).
final peopleJoinClientProvider =
    Provider<PeopleJoinClient>((ref) => PeopleJoinClient());

/// The addresses this person's server is known by (home, away...). The people
/// service answers on some of them (the public one), not on all.
final peopleCandidatesProvider = FutureProvider<List<Uri>>((ref) async {
  final server = await ref.watch(activeServerProvider.future);
  if (server == null) return const [];
  try {
    return [for (final e in jsonDecodeEndpoints(server.endpointsJson)) e.url];
  } on FormatException {
    return const [];
  } on TypeError {
    return const [];
  }
});

/// The music login as the token query (`u`, `t`, `s`), or `null` when nobody
/// is signed in: nothing is asked of the network before that.
final peopleAuthProvider = FutureProvider<Map<String, String> Function()?>(
  (ref) async => (await ref.watch(sessionProvider.future))?.client.authQuery,
);

/// "Is the people service at this address?" (tests replace it).
final peopleProbeProvider = Provider<Future<bool> Function(Uri)>(
  (ref) => PeopleClient.probe,
);

/// Where the people service answers, or `null` (not set up on this server, or
/// not reachable from this network). A phone that moves between networks
/// asks again.
final peopleServiceProvider = FutureProvider<Uri?>((ref) async {
  ref.watch(networkKindProvider);
  final auth = await ref.watch(peopleAuthProvider.future);
  if (auth == null) return null;
  final candidates = await ref.watch(peopleCandidatesProvider.future);
  if (candidates.isEmpty) return null;
  final probe = ref.watch(peopleProbeProvider);
  final answers = await Future.wait([for (final u in candidates) probe(u)]);
  for (var i = 0; i < candidates.length; i++) {
    if (answers[i]) {
      Log.info(
          'people', 'friends and invitations are at ${candidates[i].host}');
      return candidates[i];
    }
  }
  // Written down so a missing People page can be explained from the Diagnostics report.
  Log.info('people',
      'no friends and invitations service at ${candidates.map((u) => u.host).join(', ')}');
  return null;
});

/// The client of the people service, once it is found and somebody is signed in.
final peopleApiProvider = FutureProvider<PeopleApi?>((ref) async {
  final uri = await ref.watch(peopleServiceProvider.future);
  final auth = await ref.watch(peopleAuthProvider.future);
  if (uri == null || auth == null) return null;
  return PeopleClient(baseUrl: uri, auth: auth);
});

/// Who the service says I am, whether I administer the server and whether I
/// share what I am listening to. `null` value: there is no service.
class PeopleNotifier extends AsyncNotifier<PeopleMe?> {
  @override
  Future<PeopleMe?> build() async {
    final api = await ref.watch(peopleApiProvider.future);
    if (api == null) return null;
    final result = await api.me();
    final me = result.valueOrNull;
    Log.info(
        'people',
        me == null
            ? 'could not ask who I am: ${result.failureOrNull?.message}'
            : 'I am ${me.user}, ${me.role.wire}');
    return me;
  }

  /// Switches sharing on or off. The switch moves at once and goes back, with
  /// the reason returned, if the service did not take it: what is shown is
  /// what the server holds. `null` means it worked.
  Future<AppFailure?> setSharing(bool on) async {
    final api = await ref.read(peopleApiProvider.future);
    final before = state.value;
    if (api == null || before == null) {
      return const NotFoundFailure('This server has no friend activity.');
    }
    state = AsyncData(before.copyWith(sharing: on));
    final result = await api.setSharing(on);
    if (result.isOk) return null;
    state = AsyncData(before);
    return result.failureOrNull;
  }
}

final peopleProvider =
    AsyncNotifierProvider<PeopleNotifier, PeopleMe?>(PeopleNotifier.new);

/// Everybody on the server, as an owner sees them (Your server > People). A
/// refresh keeps the list on screen until the new one is there.
final peopleDirectoryProvider =
    FutureProvider.autoDispose<Result<List<PersonOnServer>>>((ref) async {
  final api = await ref.watch(peopleApiProvider.future);
  if (api == null) {
    return const Result.err(
        NotFoundFailure('This server has no list of people.'));
  }
  return api.people();
});

/// Whether the music server itself says this person is an administrator
/// (`getUser`). It decides who gets the old "make an account by hand" invite on
/// a server without the people service; nobody else is shown it. `false` while
/// signed out or when the server does not say.
final isMusicServerAdminProvider = FutureProvider<bool>((ref) async {
  final server = await ref.watch(activeServerProvider.future);
  final session = await ref.watch(sessionProvider.future);
  if (server == null || session == null) return false;
  return (await session.client.isAdministrator(server.username)).valueOrNull ??
      false;
});

/// How often the friends' list is looked at while somebody watches it.
final friendsPollEveryProvider =
    Provider<Duration>((ref) => const Duration(seconds: 30));

/// What the friends who share are listening to. Looked at again every
/// [friendsPollEveryProvider] while a screen shows it; one failed look keeps
/// the last list instead of blanking it.
final friendsProvider =
    StreamProvider.autoDispose<List<FriendActivity>>((ref) async* {
  final api = await ref.watch(peopleApiProvider.future);
  if (api == null) {
    yield const [];
    return;
  }
  final every = ref.watch(friendsPollEveryProvider);
  var watched = true;
  Timer? wake;
  var asleep = Completer<void>()..complete();
  // Nobody is watching any more: end the wait at once (no timer left behind).
  ref.onDispose(() {
    watched = false;
    wake?.cancel();
    if (!asleep.isCompleted) asleep.complete();
  });
  while (watched) {
    final result = await api.friends();
    if (!watched) return;
    final list = result.valueOrNull;
    if (list != null) yield list;
    if (!watched) return;
    asleep = Completer<void>();
    wake = Timer(every, asleep.complete);
    await asleep.future;
  }
});

/// Tells the service what is playing, when the person chose to share it.
/// Watched once by the app widget. `null` while there is no service.
final activityPublisherProvider = Provider<ActivityPublisher?>((ref) {
  final api = ref.watch(peopleApiProvider).value;
  if (api == null) return null;
  final facade = ref.watch(playbackFacadeProvider);

  ListeningState? listeningNow(PlaybackSnapshot snapshot) => listeningFrom(
        snapshot,
        isFetchedSong: (track) => ref.read(isServiceSongProvider(track)),
      );

  Stream<ListeningState?> listening() async* {
    yield listeningNow(facade.snapshot);
    yield* facade.snapshots.map(listeningNow);
  }

  bool sharing() =>
      (ref.read(peopleProvider).value?.sharing ?? false) &&
      !ref.read(settingsProvider).privateListening;

  final publisher = ActivityPublisher(
    listening: listening(),
    sink: () => api,
    sharing: sharing,
  );
  // The choice changed here or in the privacy settings.
  ref.listen(
    peopleProvider.select((m) => m.value?.sharing ?? false),
    (_, __) => publisher.refresh(),
  );
  ref.listen(
    settingsProvider.select((s) => s.privateListening),
    (_, __) => publisher.refresh(),
  );
  ref.onDispose(publisher.dispose);
  return publisher;
});
