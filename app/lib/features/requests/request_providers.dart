import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../core/logger.dart';
import '../../core/result.dart';
import '../../data/catalogue/catalogue_models.dart';
import '../../data/catalogue/deezer_client.dart';
import '../../data/db/app_database.dart';
import '../../data/repos/cover_fallback_repository.dart';
import '../../data/repos/request_repository.dart';
import '../../data/requests/portal_client.dart';
import '../../data/requests/portal_discovery.dart';
import '../../data/requests/request_service.dart';
import '../../domain/text_match.dart';
import '../settings/settings_controller.dart';

/// Where the portal password is kept.
const String kPortalPasswordKey = 'request-portal.password';

/// Public catalogue lookup (overridden in tests).
final catalogueClientProvider =
    Provider<CatalogueClient>((ref) => DeezerClient());

/// Catalogue artwork for albums the server has no cover for.
final coverFallbackRepositoryProvider =
    Provider<CoverFallbackRepository?>((ref) {
  final id = ref.watch(activeServerIdProvider).value;
  if (id == null) return null;
  return CoverFallbackRepository(
    db: ref.watch(databaseProvider),
    serverId: id,
    catalogue: ref.watch(catalogueClientProvider),
    clock: ref.watch(clockProvider),
  );
});

/// `(artist, title)` -> cover URL or `null`.
final coverFallbackProvider = FutureProvider.autoDispose
    .family<String?, (String, String)>((ref, key) async {
  final network = ref.watch(networkKindProvider).value;
  if (network == NetworkKind.none) return null;
  final repo = ref.watch(coverFallbackRepositoryProvider);
  if (repo == null) return null;
  return repo.urlFor(key.$1, key.$2);
});

final requestRepositoryProvider = Provider<RequestRepository?>((ref) {
  final id = ref.watch(activeServerIdProvider).value;
  if (id == null) return null;
  return RequestRepository(
    ref.watch(databaseProvider),
    id,
    clock: ref.watch(clockProvider),
  );
});

/// One question to one address: is that the download service? (overridden in
/// tests)
final portalProbeProvider = Provider<PortalProbe>((ref) => PortalProbe());

/// Builds the client that signs in to a download service (overridden in
/// tests so no UI test reaches a network).
typedef PortalClientFactory = RequestBackend Function({
  required Uri baseUrl,
  required String username,
  required String password,
});

final portalClientFactoryProvider = Provider<PortalClientFactory>(
  (ref) => ({required baseUrl, required username, required password}) =>
      HomelabPortalClient(
        baseUrl: baseUrl,
        username: username,
        password: password,
      ),
);

/// Finds the download service near the music server (ADR-052).
final portalDiscoveryProvider = Provider<PortalDiscovery>(
    (ref) => PortalDiscovery(probe: ref.watch(portalProbeProvider)));

/// The configured request backend, `null` until the user connected one.
///
/// A service connected with the music server's own login has no password of
/// its own stored: it keeps using the music server's, so a changed server
/// password needs no second change.
final requestBackendProvider = FutureProvider<RequestBackend?>((ref) async {
  final settings = ref.watch(settingsProvider);
  final url = settings.requestPortalUrl;
  if (url == null || url.isEmpty) return null;
  final uri = Uri.tryParse(url);
  if (uri == null || uri.host.isEmpty) return null;
  final store = ref.watch(credentialStoreProvider);
  final server = await ref.watch(activeServerProvider.future);
  final own = await store.readSecret(kPortalPasswordKey);
  final password = (own != null && own.isNotEmpty)
      ? own
      : (server == null ? null : await store.readPassword(server.id));
  if (password == null || password.isEmpty) return null;
  final user = settings.requestPortalUser ?? server?.username;
  if (user == null || user.isEmpty) return null;
  return HomelabPortalClient(baseUrl: uri, username: user, password: password);
});

/// The same portal as an import backend; `null` when none is connected or
/// the backend cannot import.
final importBackendProvider = FutureProvider<ImportBackend?>((ref) async {
  final backend = await ref.watch(requestBackendProvider.future);
  return backend is ImportBackend ? backend as ImportBackend : null;
});

/// The portal's view of this account - imported playlists, artists, requests
/// - refreshed every 20 s while a screen watches it (the portal's own page
/// polls every 30 s). `null` when no portal is connected; invalidate to
/// refresh now.
final portalOverviewProvider =
    StreamProvider.autoDispose<PortalOverview?>((ref) {
  final controller = StreamController<PortalOverview?>();
  Timer? timer;
  var disposed = false;

  Future<void> poll(RequestBackend backend) async {
    final result = await backend.overview();
    if (disposed) return;
    switch (result) {
      case Ok(:final value):
        controller.add(value);
      case Err(:final failure):
        controller.addError(failure);
    }
    timer = Timer(const Duration(seconds: 20), () => unawaited(poll(backend)));
  }

  ref.onDispose(() {
    disposed = true;
    timer?.cancel();
    unawaited(controller.close());
  });
  unawaited(ref.watch(requestBackendProvider.future).then((backend) {
    if (disposed) return;
    if (backend == null) {
      controller.add(null);
      return;
    }
    unawaited(poll(backend));
  }));
  return controller.stream;
});

final requestServiceProvider = Provider<RequestService?>((ref) {
  final repo = ref.watch(requestRepositoryProvider);
  if (repo == null) return null;
  return RequestService(
    repository: repo,
    backend: () => ref.read(requestBackendProvider.future),
  );
});

/// Resolves open requests against the library after every successful sync
/// and publishes the ones whose music just arrived (the app shows them once).
///
/// Rebuilt when the server id becomes known, so it never has to wait for it.
final requestArrivalsProvider = StreamProvider<List<RequestRow>>((ref) {
  final repo = ref.watch(requestRepositoryProvider);
  final controller = StreamController<List<RequestRow>>();
  ref.onDispose(controller.close);
  if (repo == null) return controller.stream;

  ref.listen(syncStatusProvider, (previous, next) {
    final before = previous?.value?.lastSuccessAt;
    final after = next.value?.lastSuccessAt;
    if (after == null || after == before) return;
    unawaited(() async {
      try {
        final arrived = await repo.resolveAgainstLibrary();
        if (arrived.isNotEmpty && !controller.isClosed) {
          controller.add(arrived);
        }
      } on Object catch (error) {
        Log.warn('request', 'could not resolve requests', error);
      }
    }());
  });
  return controller.stream;
});

/// State of the request for one artist/album, `null` when never requested.
final requestStateProvider = StreamProvider.autoDispose
    .family<RequestRow?, (String, String?)>((ref, key) {
  final repo = ref.watch(requestRepositoryProvider);
  if (repo == null) return Stream.value(null);
  return repo.watchFor(key.$1, key.$2);
});

/// Catalogue results for [query]. Albums and songs the library already has
/// are left out (the library's own results show them); **artists are kept**
/// and marked, because an artist the library only partly has is exactly the
/// one whose missing releases a person is looking for. Debounced (350 ms) and
/// silent when offline or unreachable.
final catalogueSearchProvider = FutureProvider.autoDispose
    .family<CatalogueResults, String>((ref, query) async {
  final q = query.trim();
  if (q.length < 2) return CatalogueResults.empty;

  var disposed = false;
  ref.onDispose(() => disposed = true);
  await Future<void>.delayed(const Duration(milliseconds: 350));
  if (disposed) return CatalogueResults.empty;

  final network = ref.read(networkKindProvider).value;
  if (network == NetworkKind.none) return CatalogueResults.empty;

  final raw = await ref.read(catalogueClientProvider).search(q);
  if (disposed || raw.isEmpty) return raw;

  final serverId = await ref.watch(activeServerIdProvider.future);
  if (serverId == null) return raw;
  final matcher = LibraryMatcher(ref.read(databaseProvider), serverId);

  // The catalogue's search is fuzzy and pads the list with unrelated names;
  // its top hit is kept (it may be a typo correction), the rest must match
  // what was typed.
  final topHit = raw.artists.isEmpty ? null : raw.artists.first.id;
  final kept = <CatalogueArtist>[];
  // Which library artist, if any, each catalogue artist is. Several artists
  // may share a name: the best known one (most fans) is taken to be the
  // library's, the others stay unowned - the artist page shows the truth.
  final ownedBest = <String, (CatalogueArtist, String)>{};
  for (final a in raw.artists) {
    if (a.id != topHit && !matchesQueryWords(a.name, q)) continue;
    kept.add(a);
    final mine = await matcher.findArtist(a.name);
    if (mine == null) continue;
    final key = normalizeForMatch(a.name);
    final current = ownedBest[key];
    if (current == null || (a.fans ?? 0) > (current.$1.fans ?? 0)) {
      ownedBest[key] = (a, mine.id);
    }
  }
  final ownedArtists = {
    for (final entry in ownedBest.values) entry.$1.id: entry.$2,
  };
  final artists = rankNamesakes(q, kept);
  final albums = <CatalogueAlbum>[];
  for (final a in raw.albums) {
    if (!await matcher.hasAlbum(a.artistName, a.title)) albums.add(a);
  }
  final tracks = <CatalogueTrack>[];
  for (final t in raw.tracks) {
    if (!await matcher.hasTrack(t.artistName, t.title)) tracks.add(t);
  }
  return CatalogueResults(
    artists: artists,
    albums: albums,
    tracks: tracks,
    ownedArtists: ownedArtists,
  );
});
