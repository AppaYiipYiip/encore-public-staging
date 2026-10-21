import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/navigation.dart';
import '../../app/providers.dart';
import '../../data/db/app_database.dart';
import '../../data/repos/library_repository.dart';
import '../../data/sync/sync_scheduler.dart';
import '../../design/tokens.dart';
import '../../domain/household.dart';
import '../common/cover_art.dart';
import '../common/format.dart';
import '../common/playlist_actions.dart';
import '../common/widgets.dart';
import '../downloads/download_providers.dart';
import '../providers.dart';
import '../settings/settings_controller.dart';

enum LibraryFilter { playlists, artists, albums, liked, downloaded }

enum LibrarySort { recent, alphabetical }

class LibraryFilterNotifier extends Notifier<LibraryFilter?> {
  @override
  LibraryFilter? build() => null;
  void select(LibraryFilter? value) => state = value;
}

final libraryFilterProvider =
    NotifierProvider<LibraryFilterNotifier, LibraryFilter?>(
        LibraryFilterNotifier.new);

class LibrarySortNotifier extends Notifier<LibrarySort> {
  @override
  LibrarySort build() => LibrarySort.alphabetical;
  void select(LibrarySort value) => state = value;
}

final librarySortProvider =
    NotifierProvider<LibrarySortNotifier, LibrarySort>(LibrarySortNotifier.new);

class LibraryGridNotifier extends Notifier<bool> {
  @override
  bool build() => false;
  void toggle() => state = !state;
}

final libraryGridProvider =
    NotifierProvider<LibraryGridNotifier, bool>(LibraryGridNotifier.new);

/// Your Library (docs/06-ux-spec.md 4.3).
class LibraryScreen extends ConsumerWidget {
  const LibraryScreen({super.key});

  static const _labels = [
    'Playlists',
    'Artists',
    'Albums',
    'Liked',
    'Downloaded',
  ];

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final filter = ref.watch(libraryFilterProvider);
    final sort = ref.watch(librarySortProvider);
    final grid = ref.watch(libraryGridProvider);
    final sync = ref.watch(syncStatusProvider).value ?? const SyncStatus();

    // A server can be shared by a household: by default this list is the
    // signed-in account's own music, not everything on the server (ADR-049).
    final scope = ref.watch(libraryScopeProvider);
    final groups = ref.watch(playlistGroupsProvider);
    final playlists = scope == LibraryScope.everything
        ? [...groups.own, ...groups.shared]
        : groups.own;
    final artistsOrNull = ref.watch(scopedArtistsProvider);
    final albumsOrNull = ref.watch(scopedAlbumsProvider(
        sort == LibrarySort.recent
            ? AlbumSort.recentlyAdded
            : AlbumSort.alphabetical));
    final artists = artistsOrNull ?? const <ArtistRow>[];
    final albums = albumsOrNull ?? const <AlbumRow>[];
    final liked = ref.watch(likedTracksProvider).value ?? const [];
    final me = ref.watch(accountNameProvider);
    final nothingOfMine = scope == LibraryScope.mine &&
        artistsOrNull != null &&
        albumsOrNull != null &&
        artists.isEmpty &&
        albums.isEmpty &&
        groups.own.isEmpty;

    final storage = ref.watch(storageSummaryProvider).value;

    final entries = <_LibraryEntry>[
      if (filter == null || filter == LibraryFilter.liked)
        _LibraryEntry.liked(liked.length),
      if (filter == null || filter == LibraryFilter.downloaded)
        if (filter == LibraryFilter.downloaded || (storage?.tracks ?? 0) > 0)
          _LibraryEntry.downloaded(storage?.tracks ?? 0, storage?.bytes ?? 0),
      if (filter == null || filter == LibraryFilter.playlists)
        for (final p in _sortPlaylists(playlists, sort))
          _LibraryEntry.playlist(p, me),
      if (filter == null || filter == LibraryFilter.artists)
        for (final a in artists) _LibraryEntry.artist(a),
      if (filter == null || filter == LibraryFilter.albums)
        for (final a in albums) _LibraryEntry.album(a),
    ];
    if (filter == LibraryFilter.liked) {
      entries.removeWhere((e) => e.kind != _Kind.liked);
    }
    if (filter == LibraryFilter.downloaded) {
      entries.removeWhere((e) => e.kind != _Kind.downloaded);
    }

    return SafeArea(
      bottom: false,
      child: CustomScrollView(
        slivers: [
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(
                  Space.gutter, Space.lg, Space.sm, Space.sm),
              child: Row(
                children: [
                  Expanded(
                      child: Text('Your Library',
                          style: context.text.headlineMedium)),
                  IconButton(
                    tooltip: 'Search',
                    icon: const Icon(Icons.search_rounded),
                    onPressed: () => context.go('/search'),
                  ),
                  IconButton(
                    tooltip: 'Create',
                    icon: const Icon(Icons.add_rounded),
                    onPressed: () => unawaited(_showCreateSheet(context)),
                  ),
                ],
              ),
            ),
          ),
          SliverToBoxAdapter(
            child: _ScopeBar(
              scope: scope,
              automatic: ref.watch(libraryScopeIsAutomaticProvider),
            ),
          ),
          SliverToBoxAdapter(
            child: ChipRow(
              labels: _labels,
              selected: filter?.index,
              onSelected: (i) => ref
                  .read(libraryFilterProvider.notifier)
                  .select(i == null ? null : LibraryFilter.values[i]),
            ),
          ),
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(
                  Space.gutter, Space.md, Space.sm, 0),
              child: Row(
                children: [
                  TextButton.icon(
                    onPressed: () =>
                        ref.read(librarySortProvider.notifier).select(
                              sort == LibrarySort.alphabetical
                                  ? LibrarySort.recent
                                  : LibrarySort.alphabetical,
                            ),
                    icon: const Icon(Icons.swap_vert_rounded, size: 20),
                    label: Text(sort == LibrarySort.alphabetical
                        ? 'A–Z'
                        : 'Recently added'),
                  ),
                  const Spacer(),
                  IconButton(
                    tooltip: grid ? 'Show as list' : 'Show as grid',
                    icon: Icon(grid
                        ? Icons.view_list_rounded
                        : Icons.grid_view_rounded),
                    onPressed: () =>
                        ref.read(libraryGridProvider.notifier).toggle(),
                  ),
                ],
              ),
            ),
          ),
          if (!sync.initialSyncDone && entries.length <= 1)
            const SliverToBoxAdapter(child: _FirstSyncCard())
          else if (nothingOfMine && filter == null)
            const SliverToBoxAdapter(child: _NothingYetCard()),
          if (grid)
            SliverPadding(
              padding: const EdgeInsets.all(Space.gutter),
              sliver: SliverGrid.builder(
                gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
                  maxCrossAxisExtent: 180,
                  mainAxisSpacing: Space.lg,
                  crossAxisSpacing: Space.md,
                  childAspectRatio: 0.78,
                ),
                itemCount: entries.length,
                itemBuilder: (context, i) => _GridEntry(entry: entries[i]),
              ),
            )
          else
            SliverList.builder(
              itemCount: entries.length,
              itemBuilder: (context, i) => _ListEntry(entry: entries[i]),
            ),
          const SliverToBoxAdapter(child: SizedBox(height: Space.xxl)),
        ],
      ),
    );
  }

  List<PlaylistRow> _sortPlaylists(List<PlaylistRow> p, LibrarySort sort) {
    final copy = [...p];
    if (sort == LibrarySort.recent) {
      copy.sort((a, b) => (b.changedAtMs ?? 0).compareTo(a.changedAtMs ?? 0));
    }
    return copy;
  }
}

/// "+" in Your Library: a new playlist, or bring music over from another
/// service.
Future<void> _showCreateSheet(BuildContext context) {
  return showModalBottomSheet<void>(
    context: context,
    showDragHandle: true,
    builder: (sheet) => SafeArea(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          ListTile(
            leading: const Icon(Icons.playlist_add_rounded),
            title: const Text('New playlist'),
            subtitle: const Text('Start empty and add songs as you go.'),
            onTap: () {
              Navigator.of(sheet).pop();
              unawaited(createPlaylistFlow(context, open: true));
            },
          ),
          ListTile(
            leading: const Icon(Icons.move_to_inbox_rounded),
            title: const Text('Import from Spotify or YouTube Music'),
            subtitle: const Text('Paste a playlist or artist link.'),
            onTap: () {
              Navigator.of(sheet).pop();
              unawaited(context.push('/settings/import'));
            },
          ),
          const SizedBox(height: Space.sm),
        ],
      ),
    ),
  );
}

enum _Kind { liked, downloaded, playlist, artist, album }

/// "Made for you", "by Sara" or the song count.
String _playlistLine(PlaylistRow p, String? me) {
  switch (playlistOwnership(owner: p.owner, readonly: p.readonly, me: me)) {
    case PlaylistOwnership.madeForMe:
      return 'Made for you';
    case PlaylistOwnership.shared:
      return 'by ${p.owner}';
    case PlaylistOwnership.mine:
      return plural(p.songCount, 'song');
  }
}

class _LibraryEntry {
  _LibraryEntry.liked(this.count)
      : kind = _Kind.liked,
        id = 'liked',
        title = 'Liked Songs',
        subtitle = 'Playlist • ${plural(count, 'song')}',
        coverArt = null,
        playlist = null;

  _LibraryEntry.downloaded(this.count, int bytes)
      : kind = _Kind.downloaded,
        id = 'downloaded',
        title = 'Downloaded',
        subtitle = count == 0
            ? 'Nothing downloaded yet'
            : '${plural(count, 'song')} • ${formatBytes(bytes)}',
        coverArt = null,
        playlist = null;

  _LibraryEntry.playlist(PlaylistRow p, String? me)
      : kind = _Kind.playlist,
        id = p.id,
        title = p.name,
        subtitle = 'Playlist • ${_playlistLine(p, me)}',
        coverArt = p.coverArt,
        count = p.songCount,
        playlist = p;

  _LibraryEntry.artist(ArtistRow a)
      : kind = _Kind.artist,
        id = a.id,
        title = a.name,
        subtitle = 'Artist',
        coverArt = a.coverArt,
        count = a.albumCount,
        playlist = null;

  _LibraryEntry.album(AlbumRow a)
      : kind = _Kind.album,
        id = a.id,
        title = a.name,
        subtitle = 'Album • ${a.artist ?? ''}',
        coverArt = a.coverArt,
        count = a.songCount,
        artistName = a.artist,
        playlist = null;

  final _Kind kind;
  final String id;
  final String title;
  final String subtitle;
  final String? coverArt;
  final int count;
  final PlaylistRow? playlist;

  /// Album entries: artist, so a missing cover can come from the catalogue.
  String? artistName;

  void open(BuildContext context) {
    switch (kind) {
      case _Kind.liked:
        Nav.liked(context);
      case _Kind.downloaded:
        Nav.downloaded(context);
      case _Kind.playlist:
        Nav.playlist(context, id);
      case _Kind.artist:
        Nav.artist(context, id);
      case _Kind.album:
        Nav.album(context, id);
    }
  }
}

class _EntryArt extends ConsumerWidget {
  const _EntryArt({required this.entry, this.radius = Radii.art});

  final _LibraryEntry entry;
  final double radius;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.colors;
    if (entry.kind == _Kind.downloaded) {
      return ClipRRect(
        borderRadius: BorderRadius.circular(radius),
        child: ColoredBox(
          color: c.accent,
          child: Icon(Icons.arrow_downward_rounded, color: c.onAccent),
        ),
      );
    }
    if (entry.kind == _Kind.liked) {
      return ClipRRect(
        borderRadius: BorderRadius.circular(radius),
        child: DecoratedBox(
          decoration: BoxDecoration(
            gradient: LinearGradient(
              colors: [c.accent, c.accent.withValues(alpha: 0.4)],
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
            ),
          ),
          child: Icon(Icons.favorite_rounded, color: c.onAccent),
        ),
      );
    }
    final mosaic = entry.kind == _Kind.playlist
        ? (ref.watch(playlistCoverIdsProvider(entry.id)).value ??
            const <String>[])
        : const <String>[];
    return CoverArt(
      coverArtId: entry.coverArt,
      mosaicIds: mosaic,
      fallbackLabel: entry.title,
      fallbackArtist: entry.artistName,
      radius: radius,
      circular: entry.kind == _Kind.artist,
    );
  }
}

class _ListEntry extends StatelessWidget {
  const _ListEntry({required this.entry});

  final _LibraryEntry entry;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      label: '${entry.title}, ${entry.subtitle}',
      excludeSemantics: true,
      child: InkWell(
        onTap: () => entry.open(context),
        child: Padding(
          padding: const EdgeInsets.symmetric(
              horizontal: Space.gutter, vertical: Space.xs + 2),
          child: Row(
            children: [
              SizedBox.square(
                dimension: 56,
                child: _EntryArt(entry: entry),
              ),
              const SizedBox(width: Space.md),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(entry.title,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: context.text.bodyLarge),
                    Text(entry.subtitle,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: context.text.bodyMedium),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _GridEntry extends StatelessWidget {
  const _GridEntry({required this.entry});

  final _LibraryEntry entry;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      label: '${entry.title}, ${entry.subtitle}',
      excludeSemantics: true,
      child: InkWell(
        onTap: () => entry.open(context),
        borderRadius: BorderRadius.circular(Radii.card),
        child: Column(
          crossAxisAlignment: entry.kind == _Kind.artist
              ? CrossAxisAlignment.center
              : CrossAxisAlignment.start,
          children: [
            Expanded(
              child: AspectRatio(
                aspectRatio: 1,
                child: _EntryArt(entry: entry, radius: Radii.card),
              ),
            ),
            const SizedBox(height: Space.sm),
            Text(entry.title,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: context.text.titleSmall),
            Text(entry.subtitle,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: context.text.bodySmall),
          ],
        ),
      ),
    );
  }
}

/// Which part of the server the list shows, and the switch to change it.
class _ScopeBar extends ConsumerWidget {
  const _ScopeBar({required this.scope, required this.automatic});

  final LibraryScope scope;

  /// The scope was chosen by the app (few plays yet), not by the person.
  final bool automatic;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final mine = scope == LibraryScope.mine;
    return Padding(
      padding: const EdgeInsets.fromLTRB(Space.gutter, 0, Space.sm, 0),
      child: Row(
        children: [
          Expanded(
            child: Text(
              mine
                  ? 'Only your music'
                  : (automatic
                      ? 'Everything you can listen to. It narrows to your own '
                          'music as you listen.'
                      : 'Everything you can listen to'),
              style: context.text.bodySmall,
            ),
          ),
          TextButton(
            onPressed: () => ref
                .read(settingsProvider.notifier)
                .setLibraryScope(
                    mine ? LibraryScope.everything : LibraryScope.mine),
            child: Text(mine ? 'Show everything' : 'Only my music'),
          ),
        ],
      ),
    );
  }
}

/// Shown when "Your music" has nothing in it yet (a new account on a shared
/// server): says why and offers the whole catalogue.
class _NothingYetCard extends ConsumerWidget {
  const _NothingYetCard();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Container(
      margin: const EdgeInsets.all(Space.gutter),
      padding: const EdgeInsets.all(Space.lg),
      decoration: BoxDecoration(
        color: context.colors.surface,
        borderRadius: BorderRadius.circular(Radii.card),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Nothing of yours yet', style: context.text.titleMedium),
          const SizedBox(height: Space.xs),
          Text(
            'Music you play, like or download shows up here. The server has '
            'more - everyone\'s music is one tap away.',
            style: context.text.bodyMedium,
          ),
          const SizedBox(height: Space.md),
          FilledButton(
            onPressed: () => ref
                .read(settingsProvider.notifier)
                .setLibraryScope(LibraryScope.everything),
            child: const Text('Show everything on this server'),
          ),
        ],
      ),
    );
  }
}

class _FirstSyncCard extends ConsumerWidget {
  const _FirstSyncCard();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final status = ref.watch(syncStatusProvider).value ?? const SyncStatus();
    final p = status.progress;
    final syncing = status.isSyncing;
    return Container(
      margin: const EdgeInsets.all(Space.gutter),
      padding: const EdgeInsets.all(Space.lg),
      decoration: BoxDecoration(
        color: context.colors.surface,
        borderRadius: BorderRadius.circular(Radii.card),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            syncing ? 'Getting your music ready' : 'Waiting for your server',
            style: context.text.titleMedium,
          ),
          const SizedBox(height: Space.xs),
          Text(
            syncing
                ? (p?.total != null && p!.total! > 0
                    ? '${p.done} of ${p.total} songs — you can already browse.'
                    : 'You can already browse while this finishes.')
                : "We'll keep trying in the background.",
            style: context.text.bodyMedium,
          ),
          if (syncing) ...[
            const SizedBox(height: Space.md),
            LinearProgressIndicator(
              value: p?.fraction,
              borderRadius: BorderRadius.circular(Radii.pill),
            ),
          ],
        ],
      ),
    );
  }
}
