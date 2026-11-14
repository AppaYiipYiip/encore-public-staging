import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/connection.dart' show serverReachabilityProvider;
import '../../app/navigation.dart';
import '../../app/providers.dart';
import '../../app/tab_reselect.dart';
import '../../data/db/app_database.dart';
import '../../data/repos/downloads_repository.dart' show PinTargetType;
import '../../data/repos/library_repository.dart' show OnPhone;
import '../../data/sync/sync_scheduler.dart';
import '../../design/tokens.dart';
import '../../domain/album_names.dart';
import '../../domain/household.dart';
import '../auth/login_problem.dart';
import '../common/cover_art.dart';
import '../common/format.dart';
import '../common/playability.dart';
import '../common/widgets.dart';
import '../downloads/download_providers.dart' show PinEntry, pinEntriesProvider;
import '../import/import_card.dart';
import '../instant/instant_controller.dart' show fetchServiceProvider;
import '../jam/jam_providers.dart' show jamEntryShownProvider;
import '../news/news_providers.dart';
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
    // A second tap on the Home tab (N-22): everything again, from the top.
    ref.onTabReselected(MainTab.home, () {
      if (_chip != null) setState(() => _chip = null);
      scrollPageToTop(context);
    });
    // The music server's catch-all "[Unknown Album]" is a bucket of songs, not a release: no shelf of releases shows it.
    final recent = withoutCatchAllAlbums<AlbumRow>(
        ref.watch(serverAlbumListProvider('server.recent')).value ?? const [],
        (a) => a.name);
    final frequent = withoutCatchAllAlbums<AlbumRow>(
        ref.watch(serverAlbumListProvider('server.frequent')).value ?? const [],
        (a) => a.name);
    final pool = withoutCatchAllAlbums<AlbumRow>(
        ref.watch(newAlbumPoolProvider).value ?? const [], (a) => a.name);
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
                  gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
                    crossAxisCount: 2,
                    mainAxisExtent: _quickTileHeight(context),
                    crossAxisSpacing: Space.sm,
                    mainAxisSpacing: Space.sm,
                  ),
                  itemCount: quick.length,
                  itemBuilder: (context, i) => _QuickTile(item: quick[i]),
                ),
              ),
            if (_chip == null)
              const SliverToBoxAdapter(child: _PlaysOfflineShelf()),
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

/// The height of a quick tile: 56 as always, and taller with a larger text size so that the title and, offline, "Not downloaded" under it both fit
/// (text at 200 % is a rule of every screen, ADR-R42).
double _quickTileHeight(BuildContext context) {
  final scale = MediaQuery.textScalerOf(context).scale(16) / 16;
  return scale <= 1 ? 56 : 56 + (scale - 1) * 44;
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
                label: 'Your account',
                excludeSemantics: true,
                child: InkWell(
                  customBorder: const CircleBorder(),
                  // The drawer of S-27 (D-34): who is listening, and one row per place. It was Settings (one person) or Who's listening (several).
                  onTap: () => Scaffold.of(context).openDrawer(),
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
              // The bell is there only where the server keeps news (an Encore server); a green dot says there is some.
              if (ref.watch(newsProvider.select((n) => n.available)))
                IconButton(
                  tooltip: ref.watch(newsProvider.select((n) => n.unread)) > 0
                      ? "What's new, unread"
                      : "What's new",
                  icon: Badge(
                    isLabelVisible:
                        ref.watch(newsProvider.select((n) => n.unread)) > 0,
                    smallSize: 8,
                    backgroundColor: context.colors.accent,
                    child: const Icon(Icons.notifications_none_rounded),
                  ),
                  onPressed: () => Nav.news(context),
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
            // Listening together: in sight on Home, but only where the server has Jam (AUDIT F50, D-33): a server without it gets no dead end.
            if (ref.watch(jamEntryShownProvider))
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
          albumDisplayName(album.name),
          CoverArt(
            coverArtId: album.coverArt,
            fallbackLabel: albumDisplayName(album.name),
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

    // While the server is away, a tile with nothing on the phone is grey and says so in words (S-10 offline). Liked Songs is never judged as a
    // whole, as drawn: some of those songs can be on the phone through another download, and its page greys them one by one (S-15 offline).
    final target = switch (item) {
      _LikedItem() => null,
      _AlbumItem(:final album) => (PinTargetType.album, album.id),
      _PlaylistItem(:final playlist) => (PinTargetType.playlist, playlist.id),
    };
    final gone = target != null && ref.watch(notDownloadedNowProvider(target));
    return Opacity(
      opacity: gone ? 0.45 : 1,
      child: Material(
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
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Flexible(
                      child: Text(
                        title,
                        maxLines: gone ? 1 : 2,
                        overflow: TextOverflow.ellipsis,
                        style: context.text.titleSmall,
                      ),
                    ),
                    if (gone)
                      Flexible(
                        child: Text(kNotDownloadedWords,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: context.text.bodySmall),
                      ),
                  ],
                ),
              ),
              const SizedBox(width: Space.sm),
            ],
          ),
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

class _AlbumCard extends ConsumerWidget {
  const _AlbumCard({required this.album});

  final AlbumRow album;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // While the server is away, an album with nothing on the phone is grey and says so in words (S-10 offline); it goes by itself.
    final gone =
        ref.watch(notDownloadedNowProvider((PinTargetType.album, album.id)));
    return Opacity(
      opacity: gone ? 0.45 : 1,
      child: MediaCard(
        title: albumDisplayName(album.name),
        subtitle: gone ? kNotDownloadedWords : albumSubtitle(album),
        coverArtId: album.coverArt,
        artistName: album.artist,
        onTap: () => Nav.album(context, album.id),
      ),
    );
  }
}

class _PlaylistCard extends ConsumerWidget {
  const _PlaylistCard({required this.playlist});

  final PlaylistRow playlist;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ids =
        ref.watch(playlistCoverIdsProvider(playlist.id)).value ?? const [];
    final gone = ref
        .watch(notDownloadedNowProvider((PinTargetType.playlist, playlist.id)));
    return Opacity(
      opacity: gone ? 0.45 : 1,
      child: MediaCard(
        title: playlist.name,
        subtitle: gone
            ? kNotDownloadedWords
            : playlist.comment?.isNotEmpty == true
                ? playlist.comment
                : trackCountLabel(playlist.songCount),
        coverArtId: playlist.coverArt,
        mosaicIds: ids,
        onTap: () => Nav.playlist(context, playlist.id),
      ),
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
      // On an Encore server playing a song does not save it: the words say what really happens.
      final encore = ref.watch(onEncoreServerProvider).value ?? false;
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
                    ? (encore
                        ? 'You have no music of your own here yet. Search for '
                            'any song and tap it: it plays within seconds. Like '
                            'a song, or download it, to keep it. You can also '
                            'bring playlists over from Spotify or YouTube Music.'
                        : 'You have no music of your own here yet. Search for '
                            'any song and tap it: it plays within seconds and '
                            'is added to your library. You can also bring '
                            'playlists over from Spotify or YouTube Music.')
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
              // That page explains what a music server needs: nothing to explain on an Encore server.
              if (!encore)
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

/// "Downloaded - Plays offline" (S-10 offline): while the server is away, what is on the phone, so a person sees what they can listen to
/// without opening the Library. Not there while the server is; an album or playlist the phone holds, in part or whole.
class _PlaysOfflineShelf extends ConsumerWidget {
  const _PlaysOfflineShelf();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (!ref.watch(serverReachabilityProvider).isAway) {
      return const SizedBox.shrink();
    }
    // Only what has a song on the phone: a download that was pressed and has no file yet (a tunnel) is not "Plays offline".
    final held = ref.watch(onPhoneProvider).value ?? OnPhone.none;
    final entries = [
      for (final e in ref.watch(pinEntriesProvider).value ?? const <PinEntry>[])
        if (e.releaseId == null &&
            ((e.pin.targetType == 'playlist' &&
                    held.playlists.contains(e.pin.targetId)) ||
                (e.pin.targetType == 'album' &&
                    held.albums.contains(e.pin.targetId))))
          e,
    ];
    if (entries.isEmpty) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SectionHeader(title: 'Downloaded'),
        Padding(
          padding: const EdgeInsets.fromLTRB(
              Space.gutter, 0, Space.gutter, Space.sm),
          child: Text('Plays offline', style: context.text.bodySmall),
        ),
        MediaShelf(
          itemCount: entries.length,
          itemBuilder: (c, i) {
            final e = entries[i];
            final isPlaylist = e.pin.targetType == 'playlist';
            return MediaCard(
              title: e.title,
              subtitle: isPlaylist ? 'Playlist' : (e.artist ?? 'Album'),
              coverArtId: e.coverArt,
              artistName: e.artist,
              onTap: () => isPlaylist
                  ? Nav.playlist(c, e.pin.targetId)
                  : Nav.album(c, e.pin.targetId),
            );
          },
        ),
      ],
    );
  }
}
