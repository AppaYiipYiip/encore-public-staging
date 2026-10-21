import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/navigation.dart';
import '../../core/result.dart';
import '../../data/catalogue/catalogue_models.dart';
import '../../data/db/app_database.dart';
import '../../data/requests/portal_client.dart';
import '../../design/tokens.dart';
import '../../domain/import_link.dart';
import '../../domain/text_match.dart';
import '../common/format.dart';
import '../providers.dart';
import '../requests/download_service_sheet.dart';
import '../requests/request_providers.dart';
import 'settings_controller.dart';
import 'settings_page.dart';

/// Import music from Spotify / YouTube Music by link through the *download
/// portal* (ADR-050): the page of a server that has a portal and no "play any
/// song" service. A server with that service gets the page in
/// `features/import/` (ADR-100), which does not need a portal.
///
/// The download service does the work (your music server only plays what it
/// already has): an artist link requests the whole discography, a playlist link becomes a playlist in the account - songs the
/// server already has are in it at once, the rest are requested album by
/// album. This page sends the link, shows progress, and takes a link shared
/// from another app.
class PortalImportScreen extends ConsumerStatefulWidget {
  const PortalImportScreen({super.key, this.sharedText});

  /// Text handed over by the system "Share" sheet.
  final String? sharedText;

  @override
  ConsumerState<PortalImportScreen> createState() => _ImportScreenState();
}

class _ImportScreenState extends ConsumerState<PortalImportScreen> {
  final _link = TextEditingController();
  final _name = TextEditingController();
  List<ImportLink> _links = const [];
  bool _busy = false;
  String? _error;
  String? _done;

  /// The portal reads a new playlist for a few seconds; look again then.
  Timer? _lookAgain;

  @override
  void initState() {
    super.initState();
    final shared = widget.sharedText;
    if (shared != null && shared.trim().isNotEmpty) {
      _link.text = shared.trim();
      _links = ImportLink.parseAll(_link.text);
    }
  }

  /// The link the single-link path acts on (and describes).
  ImportLink? get _first => _links.isEmpty ? null : _links.first;

  List<ImportLink> get _supported => [
        for (final l in _links)
          if (l.isSupported) l,
      ];

  /// Several importable links were pasted together.
  bool get _batch => _supported.length > 1;

  @override
  void dispose() {
    _lookAgain?.cancel();
    _link.dispose();
    _name.dispose();
    super.dispose();
  }

  void _onLinkChanged(String text) {
    setState(() {
      _links = ImportLink.parseAll(text);
      _error = null;
      _done = null;
    });
  }

  Future<void> _paste() async {
    final data = await Clipboard.getData(Clipboard.kTextPlain);
    final text = data?.text;
    if (text == null || text.trim().isEmpty) return;
    _link.text = text.trim();
    _onLinkChanged(_link.text);
  }

  /// Sends every pasted link, one after the other, and says how it went.
  Future<void> _importAll(ImportBackend backend) async {
    final links = _supported;
    if (links.length < 2 || _busy) return;
    setState(() {
      _busy = true;
      _error = null;
      _done = null;
    });
    var sent = 0;
    final failures = <String>[];
    for (final link in links) {
      final result = await backend.importLink(url: link.url);
      if (!mounted) return;
      switch (result) {
        case Ok():
          sent++;
        case Err(:final failure):
          failures.add(failure.message);
      }
    }
    if (!mounted) return;
    setState(() {
      _busy = false;
      if (failures.isEmpty) {
        _done = 'Sent all ${links.length} links. Playlists fill up as the '
            'songs arrive; artists are fetched album by album.';
        _link.clear();
        _links = const [];
      } else {
        _done = sent == 0 ? null : 'Sent $sent of ${links.length} links.';
        _error = '${failures.length} could not be sent: ${failures.first}';
      }
    });
    if (sent > 0) {
      ref.invalidate(portalOverviewProvider);
      _lookAgain?.cancel();
      _lookAgain = Timer(const Duration(seconds: 4), () {
        if (mounted) ref.invalidate(portalOverviewProvider);
      });
    }
  }

  Future<void> _import(ImportBackend backend) async {
    if (_batch) return _importAll(backend);
    final link = _first;
    if (link == null || !link.isSupported || _busy) return;
    setState(() {
      _busy = true;
      _error = null;
      _done = null;
    });
    final name = _name.text.trim();
    final result = await backend.importLink(
      url: link.url,
      name: link.isPlaylist && name.isNotEmpty ? name : null,
    );
    if (!mounted) return;
    switch (result) {
      case Ok(:final value):
        setState(() {
          _busy = false;
          _done = value.kind == 'artist'
              ? 'Asked for everything by ${value.name}. The server is '
                  'looking the artist up now.'
              : 'Importing "${value.name}". Songs the server has are added '
                  'now, the rest arrive as they are fetched.';
          _link.clear();
          _name.clear();
          _links = const [];
        });
        ref.invalidate(portalOverviewProvider);
        _lookAgain?.cancel();
        _lookAgain = Timer(const Duration(seconds: 4), () {
          if (mounted) ref.invalidate(portalOverviewProvider);
        });
      case Err(:final failure):
        setState(() {
          _busy = false;
          _error = failure.message;
        });
    }
  }

  Future<void> _connect() async {
    final done = await showDownloadServiceSheet(context);
    if (done) ref.invalidate(requestBackendProvider);
  }

  @override
  Widget build(BuildContext context) {
    final backend = ref.watch(importBackendProvider).value;
    final url = ref.watch(settingsProvider.select((s) => s.requestPortalUrl));
    final enabled =
        ref.watch(settingsProvider.select((s) => s.requestsEnabled));
    final connected = url != null && url.isNotEmpty;
    final overview = ref.watch(portalOverviewProvider).value;
    final c = context.colors;
    final link = _first;
    final batch = _batch;
    final supported = _supported;

    return SettingsPage(
      title: 'Import music',
      description: 'Bring your playlists and artists over from Spotify or '
          'YouTube Music. Paste a link here, or share it to Encore from the '
          'other app. Your server fetches what it does not have, including '
          'the lyrics that come with the songs.',
      children: [
        if (!enabled)
          ListTile(
            leading: Icon(Icons.cloud_off_outlined, color: c.onBgMuted),
            title: const Text('Adding music is switched off'),
            subtitle: const Text(
                'You said your server has no download service. Switch it '
                'back on if that changed.'),
            trailing: TextButton(
              onPressed: () {
                ref.read(settingsProvider.notifier).setRequestsEnabled(true);
                _connect();
              },
              child: const Text('Switch on'),
            ),
          )
        else if (!connected || backend == null)
          ListTile(
            leading: Icon(Icons.cloud_off_outlined, color: c.onBgMuted),
            title: const Text('Your server needs its download service'),
            subtitle: const Text(
                'Your music server only plays what it already has. The '
                'download service is the part that finds and downloads new '
                'music - Encore sends it your links. Connect it once; '
                'Encore looks for it for you.'),
            trailing: TextButton(
              onPressed: _connect,
              child: const Text('Connect'),
            ),
          ),
        const SettingsSection('Add a link'),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: Space.gutter),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              TextField(
                controller: _link,
                onChanged: _onLinkChanged,
                keyboardType: TextInputType.url,
                autocorrect: false,
                maxLines: 4,
                minLines: 1,
                decoration: InputDecoration(
                  labelText: 'Spotify or YouTube Music link(s)',
                  suffixIcon: IconButton(
                    tooltip: 'Paste from clipboard',
                    icon: const Icon(Icons.content_paste_rounded),
                    onPressed: _paste,
                  ),
                ),
              ),
              const SizedBox(height: Space.sm),
              if (batch)
                _BatchHint(
                    links: supported, skipped: _links.length - supported.length)
              else if (link != null)
                _LinkHint(link: link),
              if (!batch && link != null && link.isPlaylist) ...[
                const SizedBox(height: Space.sm),
                TextField(
                  controller: _name,
                  decoration: const InputDecoration(
                    labelText: 'Playlist name (optional)',
                    helperText: 'Leave empty to keep the original name.',
                  ),
                ),
              ],
              if (_error != null) ...[
                const SizedBox(height: Space.sm),
                Text(_error!,
                    style: context.text.bodyMedium
                        ?.copyWith(color: Theme.of(context).colorScheme.error)),
              ],
              if (_done != null) ...[
                const SizedBox(height: Space.sm),
                Text(_done!,
                    style: context.text.bodyMedium?.copyWith(color: c.accent)),
              ],
              const SizedBox(height: Space.md),
              Align(
                alignment: Alignment.centerLeft,
                child: FilledButton.icon(
                  onPressed: backend != null &&
                          link != null &&
                          link.isSupported &&
                          !_busy
                      ? () => _import(backend)
                      : null,
                  icon: _busy
                      ? const SizedBox.square(
                          dimension: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.download_rounded),
                  label: Text(batch
                      ? 'Import ${supported.length} links'
                      : (link != null && link.isArtist
                          ? 'Get everything by this artist'
                          : 'Import playlist')),
                ),
              ),
            ],
          ),
        ),
        const SettingsSection('How to get a link'),
        const _Step(
          icon: Icons.ios_share_rounded,
          text: 'In Spotify or YouTube Music open a playlist or an artist, '
              'tap the three dots, then Share (or Copy link).',
        ),
        const _Step(
          icon: Icons.paste_rounded,
          text: 'Choose Encore in the share sheet, or come back here and '
              'tap paste.',
        ),
        const _Step(
          icon: Icons.library_add_rounded,
          text: 'Many at once: in the Spotify desktop app select several '
              'playlists (Ctrl+click) and copy - one link per line - then '
              'paste them all here.',
        ),
        const _Step(
          icon: Icons.schedule_rounded,
          text: 'Songs your server already has appear in the playlist at '
              'once. The rest are requested album by album and can take '
              'days; the playlist fills itself in.',
        ),
        if (overview != null) ...[
          const SettingsSection('Your imports'),
          if (overview.imports.isEmpty)
            const ListTile(
              title: Text('Nothing imported yet'),
              subtitle: Text('Playlists you import show up here with their '
                  'progress.'),
            )
          else
            for (final i in overview.imports)
              _ImportTile(
                item: i,
                onRemove: backend == null
                    ? null
                    : () async {
                        final ok = await _confirmRemove(context, i.name);
                        if (ok != true) return;
                        await backend.removeImport(i.name);
                        ref.invalidate(portalOverviewProvider);
                      },
              ),
          if (overview.artists.isNotEmpty) ...[
            const SettingsSection('Artists you asked for'),
            for (final a in overview.artists)
              _ArtistTile(
                artist: a,
                backend: backend,
                onChanged: () => ref.invalidate(portalOverviewProvider),
              ),
          ],
        ],
      ],
    );
  }

  Future<bool?> _confirmRemove(BuildContext context, String name) {
    return showDialog<bool>(
      context: context,
      builder: (dialog) => AlertDialog(
        title: const Text('Remove this import?'),
        content: Text('"$name" stops being tracked. Songs already on your '
            'server stay.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialog).pop(false),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.of(dialog).pop(true),
            child: const Text('Remove'),
          ),
        ],
      ),
    );
  }
}

/// What the typed link was recognised as, or why it cannot be imported.
class _LinkHint extends StatelessWidget {
  const _LinkHint({required this.link});

  final ImportLink link;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final problem = link.problem;
    final label = switch (link.kind) {
      ImportKind.spotifyArtist ||
      ImportKind.youtubeMusicArtist =>
        '${link.sourceName} artist - everything they released',
      ImportKind.spotifyPlaylist ||
      ImportKind.youtubeMusicPlaylist ||
      ImportKind.youtubePlaylist =>
        '${link.sourceName} playlist',
      _ => problem ?? '',
    };
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(
          problem == null
              ? Icons.check_circle_rounded
              : Icons.info_outline_rounded,
          size: 18,
          color: problem == null ? c.accent : c.onBgMuted,
        ),
        const SizedBox(width: Space.xs),
        Expanded(child: Text(label, style: context.text.bodyMedium)),
      ],
    );
  }
}

/// Several links were pasted at once: say what they add up to.
class _BatchHint extends StatelessWidget {
  const _BatchHint({required this.links, required this.skipped});

  final List<ImportLink> links;
  final int skipped;

  @override
  Widget build(BuildContext context) {
    final playlists = links.where((l) => l.isPlaylist).length;
    final artists = links.where((l) => l.isArtist).length;
    final parts = [
      if (playlists > 0) '$playlists playlist${playlists == 1 ? '' : 's'}',
      if (artists > 0) '$artists artist${artists == 1 ? '' : 's'}',
    ];
    final text = '${parts.join(' and ')} found'
        '${skipped > 0 ? ' ($skipped other link${skipped == 1 ? '' : 's'} skipped)' : ''}.';
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(Icons.check_circle_rounded,
            size: 18, color: context.colors.accent),
        const SizedBox(width: Space.xs),
        Expanded(child: Text(text, style: context.text.bodyMedium)),
      ],
    );
  }
}

class _Step extends StatelessWidget {
  const _Step({required this.icon, required this.text});

  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(
          horizontal: Space.gutter, vertical: Space.xs),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 20, color: context.colors.onBgMuted),
          const SizedBox(width: Space.md),
          Expanded(child: Text(text, style: context.text.bodyMedium)),
        ],
      ),
    );
  }
}

String _capitalise(String s) =>
    s.isEmpty ? s : s[0].toUpperCase() + s.substring(1);

class _ImportTile extends ConsumerWidget {
  const _ImportTile({required this.item, required this.onRemove});

  final PortalImport item;
  final VoidCallback? onRemove;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // The playlist itself may already be in the library (it is created as
    // soon as the first songs match): say so, and let it be opened, rather
    // than a status that only says "waiting".
    final wanted = normalizeForMatch(item.name);
    final playlist = [
      for (final p
          in ref.watch(playlistsProvider).value ?? const <PlaylistRow>[])
        if (normalizeForMatch(p.name) == wanted) p,
    ].firstOrNull;
    final progress = item.hasProgress
        ? '${item.inLibrary ?? 0} of ${item.tracks} songs on your server'
            '${item.albums != null ? ' - ${item.albumsRequested ?? 0} of '
                '${item.albums} albums asked for' : ''}'
        : null;
    final waiting = item.state.toLowerCase().contains('waiting for the first');
    final state = item.isComplete
        ? 'Complete'
        : playlist != null && !item.hasProgress
            ? 'Your playlist has ${plural(playlist.songCount, 'song')} so far'
            : (item.state.isEmpty
                ? 'Working on it'
                : waiting
                    ? 'Starting - your server picks it up within half an hour'
                    : _capitalise(item.state));
    return ListTile(
      onTap: playlist == null ? null : () => Nav.playlist(context, playlist.id),
      leading: Icon(
        item.isComplete
            ? Icons.check_circle_rounded
            : Icons.playlist_add_rounded,
        color: item.isComplete ? context.colors.accent : null,
      ),
      title: Text(item.name),
      subtitle: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text([state, if (progress != null) progress].join(' - ')),
          if (playlist != null)
            Text('Tap to open it',
                style: context.text.bodySmall
                    ?.copyWith(color: context.colors.accent)),
          if (item.fraction != null && !item.isComplete) ...[
            const SizedBox(height: Space.xs),
            LinearProgressIndicator(
              value: item.fraction,
              borderRadius: BorderRadius.circular(Radii.pill),
            ),
          ],
        ],
      ),
      trailing: onRemove == null
          ? null
          : IconButton(
              tooltip: 'Remove import',
              icon: const Icon(Icons.close_rounded),
              onPressed: onRemove,
            ),
    );
  }
}

class _ArtistTile extends ConsumerWidget {
  const _ArtistTile({
    required this.artist,
    required this.backend,
    required this.onChanged,
  });

  final PortalArtist artist;
  final ImportBackend? backend;
  final VoidCallback onChanged;

  static String _state(String s) => switch (s) {
        'waiting' => 'Waiting',
        'added' => 'Asked for',
        'already' => 'Asked for (your server already knew them)',
        'pick' => 'Which one is yours?',
        'not found' => 'Not found',
        'error' => 'Problem',
        _ => _capitalise(s),
      };

  /// Opens the artist's page in the catalogue, where every song can be played
  /// now (the full-quality files are still on their way).
  Future<void> _playNow(BuildContext context, WidgetRef ref) async {
    final messenger = ScaffoldMessenger.of(context);
    final found = await ref
        .read(catalogueClientProvider)
        .search(artist.name, limit: 6)
        .then((r) => r.artists, onError: (_) => const <CatalogueArtist>[]);
    final want = normalizeForMatch(artist.name);
    final same = [
      for (final a in found)
        if (normalizeForMatch(a.name) == want) a,
    ]..sort((a, b) => (b.fans ?? 0).compareTo(a.fans ?? 0));
    if (!context.mounted) return;
    if (same.isEmpty) {
      messenger.showSnackBar(const SnackBar(
          content: Text('Could not find them in the music catalogue.')));
      return;
    }
    Nav.catalogueArtist(context, same.first.id, preloaded: same.first);
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final have = artist.tracksHave ?? 0;
    final songs = artist.tracksAll != null && artist.tracksAll! > 0
        ? '$have of ${artist.tracksAll} full-quality songs have arrived'
        : null;
    final pick = artist.state == 'pick' && artist.candidates.isNotEmpty;
    final asked = artist.state == 'added' || artist.state == 'already';
    return ListTile(
      onTap: asked ? () => unawaited(_playNow(context, ref)) : null,
      title: Text(artist.name),
      subtitle: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text([
            _state(artist.state),
            if (artist.albums != null) '${artist.albums} albums',
            if (songs != null) songs,
          ].join(' - ')),
          if (asked)
            Text('You can already play them: tap here',
                style: context.text.bodySmall
                    ?.copyWith(color: context.colors.accent)),
          if (pick && backend != null)
            Padding(
              padding: const EdgeInsets.only(top: Space.xs),
              child: Wrap(
                spacing: Space.xs,
                children: [
                  for (final c in artist.candidates)
                    ActionChip(
                      label: Text(c.label),
                      onPressed: () async {
                        await backend!.pickArtist(id: artist.id, mbid: c.mbid);
                        onChanged();
                      },
                    ),
                ],
              ),
            ),
        ],
      ),
      trailing: backend == null
          ? null
          : IconButton(
              tooltip: 'Stop tracking ${artist.name}',
              icon: const Icon(Icons.close_rounded),
              onPressed: () async {
                await backend!.removeArtist(artist.id);
                onChanged();
              },
            ),
    );
  }
}
