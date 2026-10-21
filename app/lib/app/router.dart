import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../data/catalogue/catalogue_models.dart';
import '../domain/invite_link.dart';
import '../features/catalogue/catalogue_screens.dart';
import '../features/catalogue/genre_screen.dart';
import '../features/detail/detail_screens.dart';
import '../features/home/home_screen.dart';
import '../features/import/import_screen.dart';
import '../features/import/imported_playlist_screen.dart';
import '../features/jam/jam_screen.dart';
import '../features/library/library_screen.dart';
import '../features/onboarding/connect_screen.dart';
import '../features/onboarding/join_screen.dart';
import '../features/people/people_screen.dart';
import '../features/player/lyrics_screen.dart';
import '../features/player/now_playing_screen.dart';
import '../features/providers.dart';
import '../features/search/search_screen.dart';
import '../features/settings/equalizer_screen.dart';
import '../features/settings/household_settings_screen.dart';
import '../features/settings/notifications_screen.dart';
import '../features/settings/playback_settings_screen.dart';
import '../features/settings/requests_screen.dart';
import '../features/settings/settings_screens.dart';
import '../features/settings/your_server_screen.dart';
import '../features/year/year_screen.dart';
import 'providers.dart';
import 'shell.dart';

/// Detail routes are repeated under each tab so the bottom bar and
/// mini-player stay on screen while drilling down (see `Nav`).
List<RouteBase> _detailRoutes() => [
      GoRoute(
        path: 'album/:id',
        builder: (_, s) => AlbumScreen(albumId: s.pathParameters['id']!),
      ),
      GoRoute(
        path: 'import/:id',
        builder: (_, s) =>
            ImportedPlaylistScreen(importId: s.pathParameters['id']!),
      ),
      GoRoute(
        path: 'playlist/:id',
        builder: (_, s) => _PlaylistRoute(playlistId: s.pathParameters['id']!),
      ),
      GoRoute(
        path: 'artist/:id',
        builder: (_, s) => ArtistScreen(artistId: s.pathParameters['id']!),
      ),
      GoRoute(
        path: 'catalogue/album/:id',
        builder: (_, s) {
          final extra = s.extra;
          return CatalogueAlbumScreen(
            albumId: s.pathParameters['id']!,
            preloaded: extra is CatalogueAlbum ? extra : null,
          );
        },
      ),
      GoRoute(
        path: 'catalogue/artist/:id',
        builder: (_, s) {
          final extra = s.extra;
          return CatalogueArtistScreen(
            artistId: s.pathParameters['id']!,
            preloaded: extra is CatalogueArtist ? extra : null,
          );
        },
      ),
      GoRoute(
        path: 'catalogue/genre/:id',
        builder: (_, s) => CatalogueGenreScreen(
          genreId: int.parse(s.pathParameters['id']!),
          name: s.extra is String ? s.extra! as String : null,
        ),
      ),
      GoRoute(
        path: 'genre/:name',
        builder: (_, s) => GenreScreen(genre: s.pathParameters['name']!),
      ),
      GoRoute(path: 'liked', builder: (_, __) => const LikedScreen()),
      GoRoute(path: 'jam', builder: (_, __) => const JamScreen()),
      GoRoute(path: 'year', builder: (_, __) => const YearInMusicScreen()),
      GoRoute(
        path: 'downloaded',
        builder: (_, __) => const DownloadedScreen(),
      ),
    ];

Page<void> _slideUp(GoRouterState state, Widget child) =>
    CustomTransitionPage<void>(
      key: state.pageKey,
      child: child,
      transitionDuration: const Duration(milliseconds: 320),
      reverseTransitionDuration: const Duration(milliseconds: 260),
      transitionsBuilder: (context, animation, secondary, child) {
        final curved =
            CurvedAnimation(parent: animation, curve: Curves.easeOutCubic);
        return SlideTransition(
          position: Tween(begin: const Offset(0, 1), end: Offset.zero)
              .animate(curved),
          child: child,
        );
      },
    );

/// Router is rebuilt-free: redirects react to the configured server.
final routerProvider = Provider<GoRouter>((ref) {
  final refresh = ValueNotifier<int>(0);
  ref.onDispose(refresh.dispose);
  ref.listen(activeServerProvider, (_, __) => refresh.value++);

  final router = GoRouter(
    initialLocation: '/home',
    refreshListenable: refresh,
    redirect: (context, state) {
      final server = ref.read(activeServerProvider);
      // Still reading the (local) database: stay put for a few milliseconds.
      if (server.isLoading) return null;
      final configured = server.value != null;
      final onOnboarding = state.matchedLocation == '/onboarding';
      // An invitation is opened by the app itself (docs/39 F3); it needs the
      // link it came with, so without one the person starts at the usual
      // sign-in.
      final onJoin = state.matchedLocation == '/join';
      if (onJoin && state.extra is! InviteLink) return '/onboarding';
      if (!configured && !onOnboarding && !onJoin) return '/onboarding';
      if (configured && (onOnboarding || onJoin)) return '/home';
      return null;
    },
    routes: [
      GoRoute(
        path: '/onboarding',
        builder: (_, __) => const ConnectScreen(),
      ),
      GoRoute(
        path: '/join',
        builder: (_, state) => JoinScreen(link: state.extra! as InviteLink),
      ),
      StatefulShellRoute.indexedStack(
        builder: (context, state, shell) => AppShell(navigationShell: shell),
        branches: [
          StatefulShellBranch(routes: [
            GoRoute(
              path: '/home',
              builder: (_, __) => const HomeScreen(),
              routes: _detailRoutes(),
            ),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(
              path: '/search',
              builder: (_, __) => const SearchScreen(),
              routes: _detailRoutes(),
            ),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(
              path: '/library',
              builder: (_, __) => const LibraryScreen(),
              routes: _detailRoutes(),
            ),
          ]),
        ],
      ),
      GoRoute(
        path: '/player',
        pageBuilder: (_, s) => _slideUp(s, const NowPlayingScreen()),
      ),
      GoRoute(
        path: '/lyrics',
        pageBuilder: (_, s) => _slideUp(s, const LyricsScreen()),
      ),
      GoRoute(
        path: '/settings',
        builder: (_, __) => const SettingsScreen(),
        routes: [
          GoRoute(
            path: 'playback',
            builder: (_, __) => const PlaybackSettingsScreen(),
          ),
          GoRoute(
            path: 'equalizer',
            builder: (_, __) => const EqualizerScreen(),
          ),
          GoRoute(
            path: 'downloads',
            builder: (_, __) => const DownloadsSettingsScreen(),
          ),
          GoRoute(
            path: 'sync',
            builder: (_, __) => const SyncSettingsScreen(),
          ),
          GoRoute(
            path: 'home',
            builder: (_, __) => const HouseholdSettingsScreen(),
          ),
          GoRoute(
            path: 'import',
            builder: (_, state) =>
                ImportScreen(sharedText: state.extra as String?),
          ),
          GoRoute(
            path: 'requests',
            builder: (_, __) => const RequestsSettingsScreen(),
          ),
          GoRoute(
            path: 'notifications',
            builder: (_, __) => const NotificationsSettingsScreen(),
          ),
          GoRoute(
            path: 'server',
            builder: (_, __) => const YourServerScreen(),
          ),
          GoRoute(
            path: 'people',
            builder: (_, __) => const PeopleScreen(),
          ),
          GoRoute(
            path: 'lyrics',
            builder: (_, __) => const LyricsSettingsScreen(),
          ),
          GoRoute(
            path: 'appearance',
            builder: (_, __) => const AppearanceSettingsScreen(),
          ),
          GoRoute(
            path: 'about',
            builder: (_, __) => const AboutSettingsScreen(),
          ),
        ],
      ),
    ],
  );
  ref.onDispose(router.dispose);
  return router;
});

/// Opens a playlist under its current id (a playlist created on this phone
/// changes id when the server has accepted it).
class _PlaylistRoute extends ConsumerWidget {
  const _PlaylistRoute({required this.playlistId});

  final String playlistId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final id =
        ref.watch(resolvedPlaylistIdProvider(playlistId)).value ?? playlistId;
    return PlaylistScreen(key: ValueKey(id), playlistId: id);
  }
}
