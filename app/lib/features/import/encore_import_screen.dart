import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/file_intake.dart';
import '../../app/navigation.dart';
import '../../app/providers.dart';
import '../../core/client_id.dart';
import '../../core/logger.dart';
import '../../core/result.dart';
import '../../data/encore/encore_models.dart';
import '../../data/fetch/import_models.dart';
import '../../design/tokens.dart';
import '../../domain/import_file.dart';
import '../../domain/import_link.dart';
import '../common/format.dart';
import '../settings/settings_page.dart';

/// The person's imports as the Encore server counts them, kept fresh while somebody looks: quickly while one runs, slowly otherwise.
final encoreImportsProvider =
    StreamProvider.autoDispose<List<EncoreImport>>((ref) async* {
  final session = await ref.watch(sessionProvider.future);
  if (session == null || !session.encoreMode) return;
  while (true) {
    final list = (await session.encore.imports()).valueOrNull;
    if (list != null) yield list;
    final running = list?.any((i) => i.isRunning) ?? false;
    await Future<void>.delayed(Duration(seconds: running ? 3 : 20));
  }
});

/// One song as the server wants a list of them described.
Map<String, Object?> describeImported(ImportedTrack t) => {
      'title': t.title,
      'artists': [t.artist],
      if (t.album != null && t.album!.isNotEmpty) 'album': t.album,
      if (t.durationSec != null && t.durationSec! >= 5)
        'durationMs': t.durationSec! * 1000,
      if (t.videoId != null && t.official) 'videoId': t.videoId,
    };

/// "Import music" on an Encore server: paste a link, and the playlist is there, with its picture and every song, the moment the server has
/// read the list (a second or two): it is an ordinary playlist, with the ordinary play and download buttons. Finding and keeping the songs
/// carries on in the server, which this page only reports.
class EncoreImportScreen extends ConsumerStatefulWidget {
  const EncoreImportScreen({super.key, this.sharedText});

  final String? sharedText;

  @override
  ConsumerState<EncoreImportScreen> createState() => _EncoreImportState();
}

class _EncoreImportState extends ConsumerState<EncoreImportScreen> {
  final _link = TextEditingController();
  bool _busy = false;
  bool _picking = false;
  String? _error;
  String? _started;

  @override
  void initState() {
    super.initState();
    final shared = widget.sharedText;
    if (shared != null && shared.trim().isNotEmpty) {
      _link.text = shared.trim();
      // A link shared to the app is imported at once: the person has already said what they want.
      if (_readable != null) {
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (mounted) unawaited(_importLink());
        });
      }
    }
  }

  @override
  void dispose() {
    _link.dispose();
    super.dispose();
  }

  ImportLink? get _readable {
    for (final l in ImportLink.parseAll(_link.text)) {
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

  /// The playlist is on the phone: pulled from the server's change feed, so it is there before the page opens.
  Future<void> _show(String playlistId) async {
    await ref.read(sessionProvider).value?.sync.refreshPlaylist(playlistId);
    if (!mounted) return;
    Nav.playlist(context, playlistId);
  }

  Future<void> _importLink() async {
    final link = _readable;
    final session = ref.read(sessionProvider).value;
    if (link == null || session == null || _busy) return;
    setState(() {
      _busy = true;
      _error = null;
      _started = null;
    });
    final result =
        await session.encore.createImport(id: newClientId('im'), url: link.url);
    if (!mounted) return;
    switch (result) {
      case Ok(:final value):
        setState(() {
          _busy = false;
          _link.clear();
        });
        ref.invalidate(encoreImportsProvider);
        final id = value.playlistId;
        if (id != null) await _show(id);
      case Err(:final failure):
        setState(() {
          _busy = false;
          _error = failure.message;
        });
    }
  }

  Future<void> _chooseFile() async {
    final session = ref.read(sessionProvider).value;
    if (session == null || _picking || _busy) return;
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
    if (entries.isEmpty) {
      setState(() {
        _picking = false;
        _error = problem ?? 'That file has no songs in it.';
      });
      return;
    }
    // The liked songs are what a person most wants first, whichever file of the download they were in.
    entries.setAll(0, [
      ...entries.where((e) => e.liked),
      ...entries.where((e) => !e.liked),
    ]);
    setState(() {
      _picking = false;
      _busy = true;
    });
    String? firstPlaylist;
    String? failure;
    var made = 0;
    for (final entry in entries) {
      final result = await session.encore.createImport(
        id: newClientId('im'),
        name: entry.name,
        source: 'file',
        songs: [for (final t in entry.tracks) describeImported(t)],
        liked: entry.liked,
      );
      if (!mounted) return;
      switch (result) {
        case Ok(:final value):
          made++;
          firstPlaylist ??= value.playlistId;
        case Err(failure: final problem):
          failure = problem.message;
      }
    }
    setState(() {
      _busy = false;
      _error = failure;
      if (made > 0) {
        _started = 'Started ${plural(made, 'import')}. The server fetches the '
            'songs in the background: you can leave this page, or close the app.';
      }
    });
    ref.invalidate(encoreImportsProvider);
    if (firstPlaylist != null) await _show(firstPlaylist);
  }

  Future<void> _stop(EncoreImport job) async {
    final session = ref.read(sessionProvider).value;
    if (session == null) return;
    final stopped = await session.encore.stopImport(job.id);
    if (stopped.isErr) {
      Log.debug('import', 'could not stop ${job.id}: ${stopped.failureOrNull}');
    }
    ref.invalidate(encoreImportsProvider);
  }

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final imports = ref.watch(encoreImportsProvider).value ?? const [];
    final readable = _readable;
    return SettingsPage(
      title: 'Import music',
      description: 'Bring a playlist over from Spotify or YouTube Music. Paste '
          'its link here, or share it to Encore from the other app. The '
          'playlist is there in a moment and every song plays when you tap it; '
          'the server saves them in the background.',
      children: [
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
                enabled: !_busy,
                decoration: InputDecoration(
                  labelText: 'Spotify or YouTube Music playlist link',
                  suffixIcon: IconButton(
                    tooltip: 'Paste from clipboard',
                    icon: const Icon(Icons.content_paste_rounded),
                    onPressed: _busy ? null : _paste,
                  ),
                ),
              ),
              const SizedBox(height: Space.sm),
              if (_link.text.trim().isNotEmpty)
                Text(
                  readable == null
                      ? 'That does not look like a link to a Spotify or '
                          'YouTube Music playlist.'
                      : '${readable.sourceName} '
                          '${readable.kind == ImportKind.spotifyAlbum ? 'album' : 'playlist'}',
                  style: context.text.bodySmall
                      ?.copyWith(color: context.colors.onBgMuted),
                ),
              if (_error != null) ...[
                const SizedBox(height: Space.sm),
                Text(_error!,
                    key: const Key('import-error'),
                    style: context.text.bodyMedium
                        ?.copyWith(color: Theme.of(context).colorScheme.error)),
              ],
              if (_started != null) ...[
                const SizedBox(height: Space.sm),
                Text(_started!,
                    key: const Key('import-started'),
                    style: context.text.bodyMedium?.copyWith(color: c.accent)),
              ],
              const SizedBox(height: Space.md),
              FilledButton.icon(
                key: const Key('import-start'),
                onPressed: !_busy && readable != null ? _importLink : null,
                icon: _busy
                    ? const SizedBox.square(
                        dimension: 18,
                        child: CircularProgressIndicator(strokeWidth: 2))
                    : const Icon(Icons.download_rounded),
                label: Text(_busy ? 'Reading the playlist...' : 'Import'),
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
                'For a long playlist, or all your liked songs: choose the file '
                'Spotify sends you ("Download your data", the .zip works as it '
                'is), a CSV from Exportify, or the songs file from Google '
                'Takeout.',
                style: context.text.bodyMedium
                    ?.copyWith(color: context.colors.onBgMuted),
              ),
              const SizedBox(height: Space.md),
              OutlinedButton.icon(
                key: const Key('import-file'),
                onPressed: _busy || _picking ? null : _chooseFile,
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
        if (imports.isNotEmpty) ...[
          const SettingsSection('Your imports'),
          for (final job in imports)
            _ImportTile(
              job: job,
              onOpen: job.playlistId == null
                  ? null
                  : () => Nav.playlist(context, job.playlistId!),
              onStop: job.isRunning ? () => unawaited(_stop(job)) : null,
            ),
        ],
      ],
    );
  }
}

/// What the server says of one import, in words.
String importSummary(EncoreImport job) {
  final songs = plural(job.total, 'song');
  final notFound = job.unmatched > 0 ? ', ${job.unmatched} not found' : '';
  switch (job.state) {
    case 'running':
      final looked = job.matched + job.unmatched;
      return 'Finding songs: $looked of ${job.total}$notFound';
    case 'stopped':
      return 'Stopped. $songs$notFound';
    case 'failed':
      return 'Could not finish. $songs';
    default:
      return '$songs, ${job.kept} saved on your server$notFound';
  }
}

class _ImportTile extends StatelessWidget {
  const _ImportTile({required this.job, this.onOpen, this.onStop});

  final EncoreImport job;
  final VoidCallback? onOpen;
  final VoidCallback? onStop;

  @override
  Widget build(BuildContext context) {
    final total = job.total <= 0 ? 1 : job.total;
    final fraction = job.isRunning
        ? ((job.matched + job.unmatched) / total).clamp(0.0, 1.0)
        : 1.0;
    return ListTile(
      key: Key('import-${job.id}'),
      onTap: onOpen,
      leading: Icon(
        job.playlistId == null
            ? Icons.favorite_rounded
            : Icons.queue_music_rounded,
        color: context.colors.onBgMuted,
      ),
      title: Text(job.name, maxLines: 1, overflow: TextOverflow.ellipsis),
      subtitle: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(importSummary(job)),
          if (job.isRunning) ...[
            const SizedBox(height: Space.xs),
            LinearProgressIndicator(value: fraction),
          ],
        ],
      ),
      trailing: onStop == null
          ? null
          : TextButton(onPressed: onStop, child: const Text('Stop')),
    );
  }
}
