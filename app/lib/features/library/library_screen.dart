import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/navigation.dart';
import '../../app/providers.dart';
import '../../data/db/app_database.dart';
import '../../data/repos/downloads_repository.dart';
import '../../data/repos/library_repository.dart';
import '../../data/sync/sync_scheduler.dart';
import '../../design/tokens.dart';
import '../../domain/household.dart';
import '../common/cover_art.dart';
import '../common/encore_sheet.dart';
import '../common/format.dart';
import '../common/playlist_actions.dart';
import '../common/widgets.dart';
import '../downloads/download_providers.dart';
import '../providers.dart';
import '../settings/settings_controller.dart';

enum LibraryFilter { playlists, artists, albums, liked, downloaded }

enum LibrarySort { recent, alphabetical }

class LibraryFilterNotifier extends Notifier<LibraryFilter?> {
  /// The person picked a chip (or put it back to "all"): the app does not move them again.
  bool chosenByPerson = false;

  @override
  LibraryFilter? build() => null;

  void select(LibraryFilter? value, {bool byPerson = true}) {
    if (byPerson) chosenByPerson = true;
    state = value;
  }
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
    // Without a connection only what is on the phone can be played: the Library opens on that, once, unless the person already chose.
    final offline = ref
        .watch(networkKindProvider.select((k) => k.value == NetworkKind.none));
    final filterNotifier = ref.read(libraryFilterProvider.notifier);
    if (offline && filter == null && !filterNotifier.chosenByPerson) {
      // Not while this widget is being built.
      scheduleMicrotask(() =>
          filterNotifier.select(LibraryFilter.downloaded, byPerson: false));
    }
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
    final pinned = ref.watch(pinEntriesProvider).value ?? const <PinEntry>[];

    // "Downloaded" lists what is downloaded as the things a person chose to take along - the gym playlist, the driving playlist, an album
    // - not as one heap of every song (owner, 2026-10-22). The songs of all of them are one tap further, under the list.
    final entries = filter == LibraryFilter.downloaded
        ? <_LibraryEntry>[
            for (final p in pinned.where((p) => p.pin.targetType != 'track'))
              _LibraryEntry.pinned(p),
            for (final p in pinned.where((p) => p.pin.targetType == 'track'))
              _LibraryEntry.pinned(p),
          ]
        : <_LibraryEntry>[
            if (filter == null || filter == LibraryFilter.liked)
              _LibraryEntry.liked(liked.length),
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
            child: _ScopeBar(scope: scope),
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
          if (filter == LibraryFilter.downloaded && entries.isEmpty)
            const SliverToBoxAdapter(child: _NothingDownloadedCard())
          else if (!sync.initialSyncDone && entries.length <= 1)
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
          if (filter == LibraryFilter.downloaded && (storage?.tracks ?? 0) > 0)
            SliverToBoxAdapter(
              child: _DownloadedFooter(
                  songs: storage!.tracks, bytes: storage.bytes),
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
  return showEncoreSheet<void>(
    context: context,
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

enum _Kind { liked, playlist, artist, album, song }

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

  /// Something the person chose to download: a playlist, an album, an artist, Liked Songs, a song.
  _LibraryEntry.pinned(PinEntry p)
      : kind = switch (p.pin.targetType) {
          'liked' => _Kind.liked,
          'playlist' => _Kind.playlist,
          'artist' => _Kind.artist,
          'album' => _Kind.album,
          _ => _Kind.song,
        },
        id = p.pin.targetType == 'liked' ? 'liked' : p.pin.targetId,
        title = p.title,
        subtitle = p.artist == null ? p.kind : '${p.kind} • ${p.artist}',
        coverArt = p.coverArt,
        count = 0,
        artistName = p.artist,
        playlist = p.playlist,
        pin = p.pin;

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

  /// Set when the entry is a download the person chose (Library > Downloaded): the tile shows how far it is.
  PinRow? pin;

  /// Album entries: artist, so a missing cover can come from the catalogue.
  String? artistName;

  void open(BuildContext context) {
    switch (kind) {
      case _Kind.liked:
        Nav.liked(context);
      case _Kind.song:
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

/// How far a download the person chose has got, and whether it can be used now (a phone without a connection plays only what is on it).
class _EntryState {
  const _EntryState(this.line, {this.complete = false, this.usable = true});

  /// "Downloaded - 40 songs", "Downloading 12 of 40", ...
  final String? line;
  final bool complete;
  final bool usable;
}

_EntryState _stateOf(PinState s, {required bool offline, String? waiting}) {
  switch (s.phase) {
    case PinPhase.complete:
      return _EntryState('Downloaded • ${plural(s.total, 'song')}',
          complete: true);
    case PinPhase.downloading:
      return _EntryState(
          waiting == null
              ? 'Downloading ${s.done} of ${s.total}'
              : '$waiting • ${s.done} of ${s.total}',
          usable: !offline || s.done > 0);
    case PinPhase.attention:
      return _EntryState(
          '${s.done} of ${s.total} downloaded • some did not come',
          usable: !offline || s.done > 0);
    case PinPhase.preparing:
    case PinPhase.off:
      return _EntryState('Getting ready to download', usable: !offline);
  }
}

/// The entry's own line, or - for a download the person chose - how far it is.
({String subtitle, bool complete, bool usable}) _lineFor(
    WidgetRef ref, _LibraryEntry entry) {
  final pin = entry.pin;
  if (pin == null) {
    return (subtitle: entry.subtitle, complete: false, usable: true);
  }
  final type = PinTargetType.values.byName(pin.targetType);
  final state = ref
          .watch(pinStateProvider(
              (type, type == PinTargetType.liked ? kLikedPinId : pin.targetId)))
          .value ??
      PinState.none;
  final offline =
      ref.watch(networkKindProvider.select((k) => k.value == NetworkKind.none));
  final s = _stateOf(state,
      offline: offline, waiting: ref.watch(downloadsWaitProvider));
  return (
    subtitle: '${entry.subtitle} • ${s.line}',
    complete: s.complete,
    usable: s.usable,
  );
}

class _ListEntry extends ConsumerWidget {
  const _ListEntry({required this.entry});

  final _LibraryEntry entry;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final line = _lineFor(ref, entry);
    return Semantics(
      button: true,
      label: '${entry.title}, ${line.subtitle}',
      excludeSemantics: true,
      child: Opacity(
        opacity: line.usable ? 1 : 0.45,
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
                      Row(
                        children: [
                          if (line.complete)
                            Padding(
                              padding: const EdgeInsets.only(right: 4),
                              child: Icon(Icons.arrow_circle_down_rounded,
                                  size: 16, color: context.colors.accent),
                            ),
                          Expanded(
                            child: Text(line.subtitle,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: context.text.bodyMedium),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _GridEntry extends ConsumerWidget {
  const _GridEntry({required this.entry});

  final _LibraryEntry entry;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final line = _lineFor(ref, entry);
    return Semantics(
      button: true,
      label: '${entry.title}, ${line.subtitle}',
      excludeSemantics: true,
      child: Opacity(
        opacity: line.usable ? 1 : 0.45,
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
              Text(line.subtitle,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: context.text.bodySmall),
            ],
          ),
        ),
      ),
    );
  }
}

/// Which part of the server the list shows, and the switch to change it.
class _ScopeBar extends ConsumerWidget {
  const _ScopeBar({required this.scope});

  final LibraryScope scope;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final mine = scope == LibraryScope.mine;
    return Padding(
      padding: const EdgeInsets.fromLTRB(Space.gutter, 0, Space.sm, 0),
      child: Row(
        children: [
          Expanded(
            child: Text(
              mine ? 'Only your music' : 'Everything on the server',
              style: context.text.bodySmall,
            ),
          ),
          TextButton(
            onPressed: () => ref
                .read(settingsProvider.notifier)
                .setLibraryScope(
                    mine ? LibraryScope.everything : LibraryScope.mine),
            child: Text(mine ? 'Show the whole server' : 'Only your music'),
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
            'Search for a song and tap it, like it, or bring a playlist over '
            'from Spotify or YouTube Music: it shows up here. The server has '
            'more music of other people, one tap away.',
            style: context.text.bodyMedium,
          ),
          const SizedBox(height: Space.md),
          Wrap(
            spacing: Space.sm,
            children: [
              FilledButton(
                onPressed: () => context.go('/search'),
                child: const Text('Search for a song'),
              ),
              OutlinedButton(
                onPressed: () => ref
                    .read(settingsProvider.notifier)
                    .setLibraryScope(LibraryScope.everything),
                child: const Text('Browse the whole server'),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

/// Library > Downloaded with nothing chosen yet.
class _NothingDownloadedCard extends StatelessWidget {
  const _NothingDownloadedCard();

  @override
  Widget build(BuildContext context) {
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
          Text('Nothing downloaded yet', style: context.text.titleMedium),
          const SizedBox(height: Space.xs),
          Text(
            'Open a playlist or an album and tap the download arrow: it is kept '
            'on this phone, so it plays on the road, at the gym, anywhere '
            'without a connection.',
            style: context.text.bodyMedium,
          ),
        ],
      ),
    );
  }
}

/// Under the downloaded collections: what they add up to, and the way to the songs themselves.
class _DownloadedFooter extends StatelessWidget {
  const _DownloadedFooter({required this.songs, required this.bytes});

  final int songs;
  final int bytes;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      leading: const Icon(Icons.storage_rounded),
      title: Text('${plural(songs, 'song')} on this phone'),
      subtitle: Text(formatBytes(bytes)),
      trailing: const Icon(Icons.chevron_right_rounded),
      onTap: () => Nav.downloaded(context),
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
