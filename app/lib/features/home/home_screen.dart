import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/navigation.dart';
import '../../app/providers.dart';
import '../../data/db/app_database.dart';
import '../../data/sync/sync_scheduler.dart';
import '../../design/tokens.dart';
import '../../domain/household.dart';
import '../auth/login_problem.dart';
import '../common/cover_art.dart';
import '../common/format.dart';
import '../common/widgets.dart';
import '../import/import_card.dart';
import '../instant/instant_controller.dart' show fetchServiceProvider;
import '../people/friends_shelf.dart';
import '../people/people_providers.dart';
import '../providers.dart';
import '../settings/settings_controller.dart';

/// Home (docs/06-ux-spec.md 4.1): greeting, quick access grid, shelves.
/// Everything comes from the local database - no network on this path (R-03).
class HomeScreen extends ConsumerStatefulWidget {
  const HomeScreen({super.key});

  @override
  ConsumerState<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends ConsumerState<HomeScreen> {
  int? _chip;

  static const _chips = ['Playlists', 'Albums'];

  @override
  Widget build(BuildContext context) {
    final recent =
        ref.watch(serverAlbumListProvider('server.recent')).value ?? const [];
    final frequent =
        ref.watch(serverAlbumListProvider('server.frequent')).value ?? const [];
    final pool = ref.watch(newAlbumPoolProvider).value ?? const [];
    final myMusic = ref.watch(myMusicProvider).value ?? MyMusic.empty;
    final groups = ref.watch(playlistGroupsProvider);
    final showNew =
        ref.watch(settingsProvider.select((s) => s.showNewOnServer));
    final tracks = ref.watch(trackCountProvider).value ?? 0;
    final sync = ref.watch(syncStatusProvider).value ?? const SyncStatus();
    // Friends who chose to share (needs the network; absent when the server
    // has no such service). Never blocks the rest of Home.
    final friends = ref.watch(friendsProvider).value ?? const [];

    // Home is this person's: other accounts' playlists never appear here, and
    // what everybody added to the shared server is kept apart from what comes
    // from artists this account plays (ADR-049).
    final userPlaylists = groups.mine;
    final smart = groups.madeForMe;
    final fromMyArtists = [
      for (final a in pool)
        if (myMusic.hasArtist(a.artistId)) a,
    ].take(20).toList();
    final mineIds = {for (final a in fromMyArtists) a.id};
    final onServer = showNew
        ? [
            for (final a in pool)
              if (!mineIds.contains(a.id)) a,
          ].take(20).toList()
        : const <AlbumRow>[];

    final showPlaylists = _chip == null || _chip == 0;
    final showAlbums = _chip == null || _chip == 1;

    final quick = _quickAccess(recent, frequent, userPlaylists, smart);

    return SafeArea(
      bottom: false,
      child: CustomScrollView(
        slivers: [
          SliverToBoxAdapter(
              child: _Header(
                  chip: _chip,
                  chips: _chips,
                  onChip: (v) => setState(() => _chip = v))),
          const SliverToBoxAdapter(child: LoginProblemBanner()),
          const SliverToBoxAdapter(child: ImportsHomeCards()),
          if (tracks == 0)
            SliverFillRemaining(
              hasScrollBody: false,
              child: _EmptyLibrary(syncing: sync.isSyncing, status: sync),
            )
          else ...[
            if (_chip == null)
              SliverPadding(
                padding: const EdgeInsets.fromLTRB(
                    Space.gutter, Space.lg, Space.gutter, 0),
                sliver: SliverGrid.builder(
                  gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
                    crossAxisCount: 2,
                    mainAxisExtent: 56,
                    crossAxisSpacing: Space.sm,
                    mainAxisSpacing: Space.sm,
                  ),
                  itemCount: quick.length,
                  itemBuilder: (context, i) => _QuickTile(item: quick[i]),
                ),
              ),
            if (_chip == null) const SliverToBoxAdapter(child: _YearCard()),
            if (_chip == null) ...friendsShelf(context, friends),
            if (showAlbums && recent.isNotEmpty)
              ..._shelf(context, 'Jump back in', recent.length,
                  (c, i) => _AlbumCard(album: recent[i])),
            if (showPlaylists && smart.isNotEmpty)
              ..._shelf(context, 'Made for you', smart.length,
                  (c, i) => _PlaylistCard(playlist: smart[i])),
            if (showAlbums && fromMyArtists.isNotEmpty)
              ..._shelf(
                  context,
                  'New from artists you play',
                  fromMyArtists.length,
                  (c, i) => _AlbumCard(album: fromMyArtists[i])),
            if (showAlbums && frequent.isNotEmpty)
              ..._shelf(context, 'Most played', frequent.length,
                  (c, i) => _AlbumCard(album: frequent[i])),
            if (showPlaylists && userPlaylists.isNotEmpty)
              ..._shelf(context, 'Your playlists', userPlaylists.length,
                  (c, i) => _PlaylistCard(playlist: userPlaylists[i])),
            if (showAlbums && onServer.isNotEmpty)
              ..._shelf(context, 'New on the server', onServer.length,
                  (c, i) => _AlbumCard(album: onServer[i])),
            const SliverToBoxAdapter(child: SizedBox(height: Space.xxl)),
          ],
        ],
      ),
    );
  }

  List<Widget> _shelf(
    BuildContext context,
    String title,
    int count,
    Widget Function(BuildContext, int) builder,
  ) =>
      [
        SliverToBoxAdapter(child: SectionHeader(title: title)),
        SliverToBoxAdapter(
          child: MediaShelf(itemCount: count, itemBuilder: builder),
        ),
      ];

  /// Personal by construction: liked songs, this account's playlists, what
  /// it played last and most. Never "recently added" - on a shared server that
  /// is everybody else's music.
  List<_QuickItem> _quickAccess(
    List<AlbumRow> recent,
    List<AlbumRow> frequent,
    List<PlaylistRow> user,
    List<PlaylistRow> smart,
  ) {
    final items = <_QuickItem>[
      const _QuickItem.liked(),
      for (final p in user.take(2)) _QuickItem.playlist(p),
      for (final a in recent.take(3)) _QuickItem.album(a),
      for (final p in smart.take(2)) _QuickItem.playlist(p),
      for (final a in frequent.take(2)) _QuickItem.album(a),
    ];
    final seen = <String>{};
    final unique = [
      for (final i in items)
        if (seen.add(i.key)) i,
    ];
    return unique.take(8).toList();
  }
}

class _Header extends ConsumerWidget {
  const _Header(
      {required this.chip, required this.chips, required this.onChip});

  final int? chip;
  final List<String> chips;
  final ValueChanged<int?> onChip;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final server = ref.watch(activeServerProvider).value;
    final initial = (server?.username ?? '?').characters.first.toUpperCase();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(
              Space.gutter, Space.lg, Space.sm, Space.md),
          child: Row(
            children: [
              Semantics(
                button: true,
                label: 'Settings and profile',
                excludeSemantics: true,
                child: InkWell(
                  customBorder: const CircleBorder(),
                  // On a device with several people the avatar is how to change who is listening; otherwise it opens Settings.
                  onTap: () =>
                      (ref.read(profilesProvider).value?.length ?? 1) > 1
                          ? context.push('/profiles')
                          : Nav.settings(context),
                  // 48 dp target around the 36 dp avatar.
                  child: SizedBox.square(
                    dimension: 48,
                    child: Center(
                      child: CircleAvatar(
                        radius: 18,
                        backgroundColor: context.colors.accent,
                        child: Text(initial,
                            style: context.text.labelLarge
                                ?.copyWith(color: context.colors.onAccent)),
                      ),
                    ),
                  ),
                ),
              ),
              const SizedBox(width: Space.md),
              Expanded(
                child: Text(
                  greetingFor(ref.watch(clockProvider).now()),
                  style: context.text.headlineMedium,
                ),
              ),
              IconButton(
                tooltip: 'Settings',
                icon: const Icon(Icons.settings_outlined),
                onPressed: () => Nav.settings(context),
              ),
            ],
          ),
        ),
        Row(
          children: [
            Expanded(
                child:
                    ChipRow(labels: chips, selected: chip, onSelected: onChip)),
            // Listening together: always in sight on Home, where people look for it.
            Padding(
              padding: const EdgeInsets.only(right: Space.gutter),
              child: ActionChip(
                avatar: Icon(Icons.groups_2_rounded,
                    size: 18, color: context.colors.accent),
                label: const Text('Jam'),
                onPressed: () => Nav.jam(context),
              ),
            ),
          ],
        ),
      ],
    );
  }
}

/// The way in to Year in Music: always on Home, as Spotify keeps its Wrapped
/// (the owner asked for one and then could not have found it).
class _YearCard extends StatelessWidget {
  const _YearCard();

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    return Padding(
      padding:
          const EdgeInsets.fromLTRB(Space.gutter, Space.lg, Space.gutter, 0),
      child: Material(
        color: Colors.transparent,
        borderRadius: BorderRadius.circular(Radii.hero),
        child: Ink(
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(Radii.hero),
            gradient: LinearGradient(
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
              colors: [c.accent.withValues(alpha: 0.4), c.surface],
            ),
          ),
          child: InkWell(
            borderRadius: BorderRadius.circular(Radii.hero),
            onTap: () => Nav.yearInMusic(context),
            child: Padding(
              padding: const EdgeInsets.all(Space.lg),
              child: Row(
                children: [
                  Icon(Icons.insights_rounded, color: c.accent, size: 32),
                  const SizedBox(width: Space.md),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('Your Year in Music',
                            style: context.text.titleMedium),
                        Text(
                          'Your minutes, favourites and listener type',
                          style: context.text.bodySmall
                              ?.copyWith(color: c.onBgMuted),
                        ),
                      ],
                    ),
                  ),
                  Icon(Icons.chevron_right_rounded, color: c.onBgMuted),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

sealed class _QuickItem {
  const _QuickItem();
  const factory _QuickItem.liked() = _LikedItem;
  factory _QuickItem.album(AlbumRow a) = _AlbumItem;
  factory _QuickItem.playlist(PlaylistRow p) = _PlaylistItem;

  String get key;
}

class _LikedItem extends _QuickItem {
  const _LikedItem();
  @override
  String get key => 'liked';
}

class _AlbumItem extends _QuickItem {
  _AlbumItem(this.album);
  final AlbumRow album;
  @override
  String get key => 'album:${album.id}';
}

class _PlaylistItem extends _QuickItem {
  _PlaylistItem(this.playlist);
  final PlaylistRow playlist;
  @override
  String get key => 'playlist:${playlist.id}';
}

class _QuickTile extends ConsumerWidget {
  const _QuickTile({required this.item});

  final _QuickItem item;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.colors;
    final (String title, Widget art, VoidCallback onTap) = switch (item) {
      _LikedItem() => (
          'Liked Songs',
          DecoratedBox(
            decoration: BoxDecoration(
              gradient: LinearGradient(
                colors: [c.accent, c.accent.withValues(alpha: 0.45)],
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
              ),
            ),
            child: Icon(Icons.favorite_rounded, color: c.onAccent),
          ),
          () => Nav.liked(context),
        ),
      _AlbumItem(:final album) => (
          album.name,
          CoverArt(
            coverArtId: album.coverArt,
            fallbackLabel: album.name,
            fallbackArtist: album.artist,
            radius: 0,
          ),
          () => Nav.album(context, album.id),
        ),
      _PlaylistItem(:final playlist) => (
          playlist.name,
          _PlaylistArt(playlist: playlist, radius: 0),
          () => Nav.playlist(context, playlist.id),
        ),
    };

    return Material(
      color: c.surfaceHigh,
      borderRadius: BorderRadius.circular(Radii.card),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Row(
          children: [
            SizedBox.square(dimension: 56, child: art),
            const SizedBox(width: Space.md),
            Expanded(
              child: Text(
                title,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: context.text.titleSmall,
              ),
            ),
            const SizedBox(width: Space.sm),
          ],
        ),
      ),
    );
  }
}

/// Playlist artwork: the server's picture, or a collage of its albums.
class _PlaylistArt extends ConsumerWidget {
  const _PlaylistArt({required this.playlist, this.radius = Radii.card});

  final PlaylistRow playlist;
  final double radius;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ids =
        ref.watch(playlistCoverIdsProvider(playlist.id)).value ?? const [];
    return CoverArt(
      coverArtId: playlist.coverArt,
      mosaicIds: ids,
      fallbackLabel: playlist.name,
      radius: radius,
    );
  }
}

class _AlbumCard extends StatelessWidget {
  const _AlbumCard({required this.album});

  final AlbumRow album;

  @override
  Widget build(BuildContext context) => MediaCard(
        title: album.name,
        subtitle: albumSubtitle(album),
        coverArtId: album.coverArt,
        artistName: album.artist,
        onTap: () => Nav.album(context, album.id),
      );
}

class _PlaylistCard extends ConsumerWidget {
  const _PlaylistCard({required this.playlist});

  final PlaylistRow playlist;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ids =
        ref.watch(playlistCoverIdsProvider(playlist.id)).value ?? const [];
    return MediaCard(
      title: playlist.name,
      subtitle: playlist.comment?.isNotEmpty == true
          ? playlist.comment
          : trackCountLabel(playlist.songCount),
      coverArtId: playlist.coverArt,
      mosaicIds: ids,
      onTap: () => Nav.playlist(context, playlist.id),
    );
  }
}

class _EmptyLibrary extends ConsumerWidget {
  const _EmptyLibrary({required this.syncing, required this.status});

  final bool syncing;
  final SyncStatus status;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (syncing) {
      final p = status.progress;
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(Space.xxl),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              SizedBox(
                width: 160,
                child: LinearProgressIndicator(
                  value: p?.fraction,
                  borderRadius: BorderRadius.circular(Radii.pill),
                ),
              ),
              const SizedBox(height: Space.xl),
              Text('Getting your music ready',
                  style: context.text.titleLarge, textAlign: TextAlign.center),
              const SizedBox(height: Space.sm),
              Text(
                p != null && p.total != null && p.total! > 0
                    ? '${p.done} of ${p.total} songs'
                    : 'This only happens once.',
                style: context.text.bodyMedium,
              ),
            ],
          ),
        ),
      );
    }
    // The server answered and holds nothing: say so, and offer the two real
    // ways in. "We keep trying to reach your server" would be false here.
    if (status.lastSuccessAt != null) {
      // A server with the instant-play service: the way in is to search for a
      // song and tap it (it plays at once and becomes theirs), not to "request".
      final instant = ref.watch(fetchServiceProvider).value != null;
      return Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(Space.xxl),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.library_add_outlined,
                  size: 48, color: context.colors.onBgFaint),
              const SizedBox(height: Space.lg),
              Text(
                  instant
                      ? 'Search for a song to start'
                      : 'Add your first music',
                  style: context.text.titleLarge,
                  textAlign: TextAlign.center),
              const SizedBox(height: Space.sm),
              Text(
                instant
                    ? 'You have no music of your own here yet. Search for any '
                        'song and tap it: it plays within seconds and is added '
                        'to your library. You can also bring playlists over from '
                        'Spotify or YouTube Music.'
                    : 'Your server is connected but has no music yet. Bring '
                        'some over from Spotify or YouTube Music, or search for '
                        'what you want and request it. You can also put files '
                        "in the server's music folder and pull down to refresh.",
                style: context.text.bodyMedium,
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: Space.xl),
              if (instant) ...[
                FilledButton.icon(
                  onPressed: () => context.go('/search'),
                  icon: const Icon(Icons.search_rounded),
                  label: const Text('Search for a song'),
                ),
                const SizedBox(height: Space.sm),
                OutlinedButton.icon(
                  onPressed: () => context.push('/settings/import'),
                  icon: const Icon(Icons.move_to_inbox_rounded),
                  label: const Text('Import a playlist or artist'),
                ),
              ] else ...[
                FilledButton.icon(
                  onPressed: () => context.push('/settings/import'),
                  icon: const Icon(Icons.move_to_inbox_rounded),
                  label: const Text('Import a playlist or artist'),
                ),
                const SizedBox(height: Space.sm),
                OutlinedButton.icon(
                  onPressed: () => context.go('/search'),
                  icon: const Icon(Icons.search_rounded),
                  label: const Text('Search and request'),
                ),
              ],
              TextButton(
                onPressed: () => context.push('/settings/server'),
                child: const Text('What does my server need?'),
              ),
            ],
          ),
        ),
      );
    }
    return const EmptyState(
      icon: Icons.library_music_outlined,
      title: 'Your library will show up here',
      message: "We'll keep trying to reach your server. You can check what "
          'it provides under Settings > Your server.',
    );
  }
}
