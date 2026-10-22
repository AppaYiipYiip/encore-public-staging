import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/file_intake.dart';
import '../../app/navigation.dart';
import '../../app/providers.dart' show sessionProvider;
import '../../core/result.dart';
import '../../data/fetch/import_models.dart';
import '../../design/tokens.dart';
import '../../domain/import_file.dart';
import '../../domain/import_link.dart';
import '../common/format.dart';
import '../instant/instant_controller.dart';
import '../settings/import_screen.dart';
import '../settings/settings_page.dart';
import 'encore_import_screen.dart';
import 'import_card.dart';
import 'import_providers.dart';

/// "Import music": bring a Spotify or YouTube Music playlist over.
///
/// Which page this is depends on the server: one whose "play any song" service
/// can take an import (ADR-100) gets [PlaylistImportScreen]; one with the old
/// download portal keeps its page; a server with an out-of-date song service is
/// told so; the sheet "Connect your download service" is never offered where
/// songs can already be played on request.
class ImportScreen extends ConsumerWidget {
  const ImportScreen({super.key, this.sharedText});

  /// Text handed over by the system "Share" sheet.
  final String? sharedText;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // An Encore server takes an import itself: no separate service to find, no review page, no special playlist page.
    if (ref.watch(sessionProvider).value?.encoreMode ?? false) {
      return EncoreImportScreen(sharedText: sharedText);
    }
    if (ref.watch(playlistImportBackendProvider) != null) {
      return PlaylistImportScreen(sharedText: sharedText);
    }
    final searching = ref.watch(fetchServiceProvider).isLoading ||
        ref.watch(fetchInfoProvider).isLoading;
    if (searching) {
      return Scaffold(
        appBar: AppBar(title: const Text('Import music')),
        body: const Center(child: CircularProgressIndicator()),
      );
    }
    if (ref.watch(instantAvailableProvider)) {
      return SettingsPage(
        title: 'Import music',
        children: const [
          ListTile(
            leading: Icon(Icons.system_update_alt_rounded),
            title: Text("Your server's song service needs an update"),
            subtitle: Text('Importing a playlist needs a newer version of '
                'it. Ask whoever runs the server to update it, then come '
                'back here.'),
          ),
        ],
      );
    }
    return PortalImportScreen(sharedText: sharedText);
  }
}

enum _Phase { link, reading, review, starting, chooseFromFile }

class PlaylistImportScreen extends ConsumerStatefulWidget {
  const PlaylistImportScreen({super.key, this.sharedText});

  final String? sharedText;

  @override
  ConsumerState<PlaylistImportScreen> createState() =>
      _PlaylistImportScreenState();
}

class _PlaylistImportScreenState extends ConsumerState<PlaylistImportScreen> {
  final _link = TextEditingController();
  final _name = TextEditingController();
  _Phase _phase = _Phase.link;
  ImportedPlaylist? _list;
  String? _error;
  String? _started;
  bool _liked = false;

  /// What a chosen file held, when it held more than one list.
  List<ImportFileEntry> _fileEntries = const [];
  Set<int> _chosen = {};
  bool _picking = false;

  @override
  void initState() {
    super.initState();
    final shared = widget.sharedText;
    if (shared != null && shared.trim().isNotEmpty) {
      _link.text = shared.trim();
      // A link that was shared to the app is read at once: the person has
      // already said what they want.
      if (_readable != null) {
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (mounted) unawaited(_read());
        });
      }
    }
  }

  @override
  void dispose() {
    _link.dispose();
    _name.dispose();
    super.dispose();
  }

  List<ImportLink> get _links => ImportLink.parseAll(_link.text);

  /// The first link that can be read (a playlist or an album).
  ImportLink? get _readable {
    for (final l in _links) {
      if (l.isReadable) return l;
    }
    return null;
  }

  Future<void> _paste() async {
    final data = await Clipboard.getData(Clipboard.kTextPlain);
    final text = data?.text;
    if (text == null || text.trim().isEmpty) return;
    setState(() {
      _link.text = text.trim();
      _error = null;
      _started = null;
    });
  }

  Future<void> _read() async {
    final link = _readable;
    final backend = ref.read(playlistImportBackendProvider);
    if (link == null || backend == null || _phase == _Phase.reading) return;
    setState(() {
      _phase = _Phase.reading;
      _error = null;
      _started = null;
    });
    final result = await backend.readPlaylist(link.url);
    if (!mounted) return;
    switch (result) {
      case Ok(:final value):
        setState(() {
          _list = value;
          _name.text = value.name;
          _liked = false;
          _phase = _Phase.review;
        });
      case Err(:final failure):
        setState(() {
          _phase = _Phase.link;
          _error = failure.message;
        });
    }
  }

  Future<void> _start() async {
    final list = _list;
    if (list == null || _phase == _Phase.starting) return;
    setState(() {
      _phase = _Phase.starting;
      _error = null;
    });
    final name = _name.text.trim().isEmpty ? list.name : _name.text.trim();
    final result = await ref.read(importsProvider.notifier).start(
          name: name,
          source: list.source,
          tracks: list.tracks,
          liked: _liked,
        );
    if (!mounted) return;
    switch (result) {
      case Ok(:final value):
        setState(() {
          _phase = _Phase.link;
          _list = null;
          _link.clear();
          _name.clear();
          _started = _liked
              ? 'Started. Your songs are being fetched and liked. You can '
                  'leave this page, or close the app: the server carries on.'
              : 'Started. "$name" appears in your library with the first '
                  'songs and fills up. You can leave this page, or close '
                  'the app: the server carries on.';
        });
        // Straight to the playlist, every song on it at once and playable now
        // (ADR-102): nobody should sit and watch a progress bar.
        Nav.importedPlaylist(context, value.id);
      case Err(:final failure):
        setState(() {
          _phase = _Phase.review;
          _error = failure.message;
        });
    }
  }

  void _again() => setState(() {
        _phase = _Phase.link;
        _list = null;
        _fileEntries = const [];
        _error = null;
      });

  /// "Choose a file": the system file chooser, then whatever the file holds.
  Future<void> _chooseFile() async {
    if (_picking) return;
    setState(() {
      _picking = true;
      _error = null;
      _started = null;
    });
    List<PickedFile>? files;
    try {
      files = await ref.read(songFilePickerProvider).pick();
    } on FilePickProblem catch (problem) {
      if (!mounted) return;
      setState(() {
        _picking = false;
        _error = problem.message;
      });
      return;
    }
    if (!mounted) return;
    if (files == null) {
      setState(() => _picking = false);
      return;
    }
    final entries = <ImportFileEntry>[];
    String? problem;
    for (final file in files) {
      final result = parseImportFile(file.text, fileName: file.name);
      entries.addAll(result.entries);
      problem ??= result.problem;
    }
    // The liked songs are what a person most wants first, whichever file of
    // the download they were in.
    entries.setAll(0, [
      ...entries.where((e) => e.liked),
      ...entries.where((e) => !e.liked),
    ]);
    setState(() {
      _picking = false;
      if (entries.isEmpty) {
        _error = problem ?? 'That file has no songs in it.';
        return;
      }
      if (entries.length == 1) {
        final only = entries.single;
        _list = ImportedPlaylist(
          name: only.name,
          source: 'file',
          kind: 'playlist',
          tracks: only.tracks,
        );
        _name.text = only.name;
        _liked = only.liked;
        _phase = _Phase.review;
      } else {
        _fileEntries = entries;
        _chosen = {for (var i = 0; i < entries.length; i++) i};
        _phase = _Phase.chooseFromFile;
      }
    });
  }

  /// One import for each list the person ticked, in the order of the file.
  Future<void> _startChosen() async {
    if (_chosen.isEmpty || _phase == _Phase.starting) return;
    setState(() {
      _phase = _Phase.starting;
      _error = null;
    });
    final controller = ref.read(importsProvider.notifier);
    var started = 0;
    String? failure;
    String? firstId;
    for (final i in _chosen.toList()..sort()) {
      final entry = _fileEntries[i];
      final result = await controller.start(
        name: entry.name,
        source: 'file',
        tracks: entry.tracks,
        liked: entry.liked,
      );
      switch (result) {
        case Ok(:final value):
          started++;
          firstId ??= value.id;
        case Err(failure: final problem):
          failure = problem.message;
      }
      if (!mounted) return;
    }
    setState(() {
      _phase =
          failure != null && started == 0 ? _Phase.chooseFromFile : _Phase.link;
      if (started > 0) {
        _fileEntries = const [];
        _started = 'Started ${plural(started, 'import')}, one after the '
            'other. You can leave this page, or close the app: the server '
            'carries on.';
      }
      _error = failure;
    });
    if (firstId != null) Nav.importedPlaylist(context, firstId);
  }

  @override
  Widget build(BuildContext context) {
    final jobs = ref.watch(importsProvider.select((s) => s.jobs));
    final running = [
      for (final j in jobs)
        if (j.isRunning) j,
    ];
    final finished = [
      for (final j in jobs)
        if (j.isFinished) j,
    ];
    final c = context.colors;
    final phase = _phase;
    final list = _list;

    return SettingsPage(
      title: 'Import music',
      description: 'Bring a playlist over from Spotify or YouTube Music. '
          'Paste its link here, or share it to Encore from the other app. '
          'The server fetches the songs in the background, so you can '
          'listen meanwhile and close the app.',
      children: [
        // What is running comes first: the person has just tapped Import and
        // wants to see it move, not to scroll for it.
        if (running.isNotEmpty) ...[
          const SettingsSection('Importing now'),
          for (final job in running) ImportCard(job: job),
        ],
        if (phase == _Phase.chooseFromFile ||
            (phase == _Phase.starting && list == null))
          _fileChooser(context)
        else if (phase == _Phase.review || phase == _Phase.starting)
          if (list != null) _review(context, list) else const SizedBox.shrink()
        else ...[
          const SettingsSection('Playlist link'),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: Space.gutter),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                TextField(
                  key: const Key('import-link'),
                  controller: _link,
                  onChanged: (_) => setState(() {
                    _error = null;
                    _started = null;
                  }),
                  keyboardType: TextInputType.url,
                  autocorrect: false,
                  maxLines: 3,
                  minLines: 1,
                  enabled: phase == _Phase.link,
                  decoration: InputDecoration(
                    labelText: 'Spotify or YouTube Music playlist link',
                    suffixIcon: IconButton(
                      tooltip: 'Paste from clipboard',
                      icon: const Icon(Icons.content_paste_rounded),
                      onPressed: phase == _Phase.link ? _paste : null,
                    ),
                  ),
                ),
                const SizedBox(height: Space.sm),
                _hint(context),
                if (_error != null) ...[
                  const SizedBox(height: Space.sm),
                  Text(_error!,
                      key: const Key('import-error'),
                      style: context.text.bodyMedium?.copyWith(
                          color: Theme.of(context).colorScheme.error)),
                ],
                if (_started != null) ...[
                  const SizedBox(height: Space.sm),
                  Text(_started!,
                      key: const Key('import-started'),
                      style:
                          context.text.bodyMedium?.copyWith(color: c.accent)),
                ],
                const SizedBox(height: Space.md),
                Align(
                  alignment: Alignment.centerLeft,
                  child: FilledButton.icon(
                    key: const Key('import-read'),
                    onPressed: phase == _Phase.link && _readable != null
                        ? _read
                        : null,
                    icon: phase == _Phase.reading
                        ? const SizedBox.square(
                            dimension: 18,
                            child: CircularProgressIndicator(strokeWidth: 2))
                        : const Icon(Icons.playlist_add_check_rounded),
                    label: Text(phase == _Phase.reading
                        ? 'Reading the playlist...'
                        : 'Read the playlist'),
                  ),
                ),
              ],
            ),
          ),
          const SettingsSection('Or from a file'),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: Space.gutter),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'For a long playlist, or all your liked songs: choose the '
                  'file Spotify sends you ("Download your data", the .zip '
                  'works as it is), a CSV from Exportify, or the songs file '
                  'from Google Takeout.',
                  style: context.text.bodyMedium
                      ?.copyWith(color: context.colors.onBgMuted),
                ),
                const SizedBox(height: Space.md),
                OutlinedButton.icon(
                  key: const Key('import-file'),
                  onPressed:
                      phase == _Phase.link && !_picking ? _chooseFile : null,
                  icon: _picking
                      ? const SizedBox.square(
                          dimension: 18,
                          child: CircularProgressIndicator(strokeWidth: 2))
                      : const Icon(Icons.upload_file_rounded),
                  label: const Text('Choose a file'),
                ),
              ],
            ),
          ),
          const SettingsSection('How to get a link'),
          const _Step(
            icon: Icons.ios_share_rounded,
            text: 'In Spotify or YouTube Music open the playlist, tap the '
                'three dots, then Share. Choose Encore, or Copy link and '
                'paste it here.',
          ),
          const _Step(
            icon: Icons.lock_open_rounded,
            text: 'The playlist must be public (or unlisted). A private one '
                'cannot be read: make it public for the import, then private '
                'again.',
          ),
          const _Step(
            icon: Icons.schedule_rounded,
            text: 'The playlist is there at once and every song plays when you '
                'tap it (a few seconds for one your server does not have yet). '
                'Saving them all to your server takes longer and carries on '
                'in the background.',
          ),
        ],
        if (finished.isNotEmpty) ...[
          const SettingsSection('Earlier imports'),
          for (final job in finished) ImportCard(job: job),
        ],
      ],
    );
  }

  Widget _fileChooser(BuildContext context) {
    final c = context.colors;
    final starting = _phase == _Phase.starting;
    final songs =
        _chosen.fold<int>(0, (n, i) => n + _fileEntries[i].tracks.length);
    return Padding(
      padding: const EdgeInsets.fromLTRB(
          Space.gutter, Space.xl, Space.gutter, Space.md),
      child: Column(
        key: const Key('import-file-choose'),
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text('${plural(_fileEntries.length, 'list')} in your file',
              style: context.text.titleMedium),
          const SizedBox(height: Space.xs),
          Text(
            'Tick what to bring over. Each one is fetched in turn, the '
            'first one first.',
            style: context.text.bodyMedium?.copyWith(color: c.onBgMuted),
          ),
          const SizedBox(height: Space.sm),
          for (var i = 0; i < _fileEntries.length; i++)
            CheckboxListTile(
              key: Key('import-entry-$i'),
              contentPadding: EdgeInsets.zero,
              value: _chosen.contains(i),
              onChanged: starting
                  ? null
                  : (on) => setState(() {
                        if (on ?? false) {
                          _chosen = {..._chosen, i};
                        } else {
                          _chosen = {..._chosen}..remove(i);
                        }
                      }),
              title: Text(_fileEntries[i].name,
                  maxLines: 1, overflow: TextOverflow.ellipsis),
              subtitle: Text('${plural(_fileEntries[i].tracks.length, 'song')}'
                  '${_fileEntries[i].liked ? ' - liked, no playlist' : ''}'),
            ),
          if (_error != null) ...[
            const SizedBox(height: Space.sm),
            Text(_error!,
                key: const Key('import-error'),
                style: context.text.bodyMedium
                    ?.copyWith(color: Theme.of(context).colorScheme.error)),
          ],
          const SizedBox(height: Space.md),
          FilledButton.icon(
            key: const Key('import-start-chosen'),
            onPressed: starting || _chosen.isEmpty ? null : _startChosen,
            icon: starting
                ? const SizedBox.square(
                    dimension: 18,
                    child: CircularProgressIndicator(strokeWidth: 2))
                : const Icon(Icons.download_rounded),
            label: Text(starting
                ? 'Starting...'
                : 'Import ${plural(_chosen.length, 'list')} '
                    '(${plural(songs, 'song')})'),
          ),
          TextButton(
            onPressed: starting ? null : _again,
            child: const Text('Choose another file'),
          ),
        ],
      ),
    );
  }

  Widget _hint(BuildContext context) {
    final style =
        context.text.bodySmall?.copyWith(color: context.colors.onBgMuted);
    if (_link.text.trim().isEmpty) return const SizedBox.shrink();
    final links = _links;
    final readable = _readable;
    if (readable != null) {
      return Text(
        '${readable.sourceName} ${readable.kind == ImportKind.spotifyAlbum ? 'album' : 'playlist'}',
        style: style,
      );
    }
    final first = links.isEmpty ? null : links.first;
    final text = switch (first?.kind) {
      null ||
      ImportKind.unknown =>
        'That does not look like a link to a Spotify or YouTube Music '
            'playlist.',
      ImportKind.spotifyArtist ||
      ImportKind.youtubeMusicArtist =>
        'That is an artist. Open one of their playlists and share that, or '
            'search for the artist and tap their songs.',
      _ => 'That is one song. Search for it by name, or paste a playlist.',
    };
    return Text(text, style: style);
  }

  Widget _review(BuildContext context, ImportedPlaylist list) {
    final c = context.colors;
    final starting = _phase == _Phase.starting;
    final count = list.tracks.length;
    final preview = list.tracks.take(8).toList();
    return Padding(
      padding: const EdgeInsets.fromLTRB(
          Space.gutter, Space.xl, Space.gutter, Space.md),
      child: Column(
        key: const Key('import-review'),
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text('${plural(count, 'song')} from ${list.sourceName}',
              style: context.text.titleMedium),
          const SizedBox(height: Space.xs),
          Text(
            importPromise(count),
            style: context.text.bodyMedium?.copyWith(color: c.onBgMuted),
          ),
          if (list.truncated) ...[
            const SizedBox(height: Space.sm),
            Text(
              key: const Key('import-truncated'),
              list.source == 'spotify'
                  ? 'Spotify shows only the first 100 songs of a playlist '
                      'through its link. If this playlist is longer, the '
                      'rest are not included. To bring all of it, go back '
                      'and choose a file instead.'
                  : 'Only the first ${plural(count, 'song')} are read.',
              style: context.text.bodyMedium
                  ?.copyWith(color: Theme.of(context).colorScheme.error),
            ),
          ],
          const SizedBox(height: Space.lg),
          TextField(
            key: const Key('import-name'),
            controller: _name,
            enabled: !starting && !_liked,
            decoration: const InputDecoration(labelText: 'Playlist name'),
          ),
          const SizedBox(height: Space.md),
          SegmentedButton<bool>(
            key: const Key('import-kind'),
            segments: const [
              ButtonSegment(value: false, label: Text('Make a playlist')),
              ButtonSegment(value: true, label: Text('Like every song')),
            ],
            selected: {_liked},
            onSelectionChanged:
                starting ? null : (s) => setState(() => _liked = s.first),
          ),
          const SizedBox(height: Space.md),
          for (final t in preview)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: Space.xxs),
              child: Text('${t.title} - ${t.artist}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: context.text.bodySmall),
            ),
          if (count > preview.length)
            Padding(
              padding: const EdgeInsets.only(top: Space.xxs),
              child: Text('and ${count - preview.length} more',
                  style: context.text.bodySmall?.copyWith(color: c.onBgMuted)),
            ),
          if (_error != null) ...[
            const SizedBox(height: Space.md),
            Text(_error!,
                key: const Key('import-error'),
                style: context.text.bodyMedium
                    ?.copyWith(color: Theme.of(context).colorScheme.error)),
          ],
          const SizedBox(height: Space.lg),
          FilledButton.icon(
            key: const Key('import-start'),
            onPressed: starting ? null : _start,
            icon: starting
                ? const SizedBox.square(
                    dimension: 18,
                    child: CircularProgressIndicator(strokeWidth: 2))
                : const Icon(Icons.download_rounded),
            label: Text(starting
                ? 'Starting...'
                : (_liked
                    ? 'Like ${plural(count, 'song')}'
                    : 'Import ${plural(count, 'song')}')),
          ),
          TextButton(
            key: const Key('import-another'),
            onPressed: starting ? null : _again,
            child: const Text('Choose another link'),
          ),
        ],
      ),
    );
  }
}

class _Step extends StatelessWidget {
  const _Step({required this.icon, required this.text});

  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      dense: true,
      leading: Icon(icon, color: context.colors.onBgMuted),
      title: Text(text, style: context.text.bodyMedium),
    );
  }
}
