import 'dart:async';

import 'package:encore_session/encore_session.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/catalogue/catalogue_models.dart';
import '../../data/db/app_database.dart';
import '../../design/tokens.dart';
import '../../domain/album_names.dart';
import '../common/encore_sheet.dart';
import '../providers.dart';
import '../requests/request_providers.dart';
import 'jam_providers.dart';

/// "Add songs": a search of this person's library and of what the catalogue
/// knows, from which a tap puts a song in the Jam. The song carries its title and
/// artist, because the phone that plays finds it in its own library (or has the
/// server fetch it): the id in one person's library means nothing in another's.
Future<void> showAddSongsSheet(BuildContext context) => showEncoreSheet<void>(
      context: context,
      builder: (_) => const _AddSongsSheet(),
    );

class _AddSongsSheet extends ConsumerStatefulWidget {
  const _AddSongsSheet();

  @override
  ConsumerState<_AddSongsSheet> createState() => _AddSongsSheetState();
}

class _AddSongsSheetState extends ConsumerState<_AddSongsSheet> {
  final _field = TextEditingController();
  Timer? _typing;
  String _query = '';
  final Set<String> _added = {};

  @override
  void dispose() {
    _typing?.cancel();
    _field.dispose();
    super.dispose();
  }

  void _typed(String text) {
    _typing?.cancel();
    _typing = Timer(const Duration(milliseconds: 300), () {
      if (mounted) setState(() => _query = text.trim());
    });
  }

  Future<void> _add(String key, Add command) async {
    setState(() => _added.add(key));
    final ok = await ref.read(jamControllerProvider.notifier).send(command);
    if (!ok && mounted) setState(() => _added.remove(key));
  }

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final library = _query.isEmpty
        ? const <TrackRow>[]
        : ref.watch(searchResultsProvider(_query)).value?.tracks ?? const [];
    final catalogue = _query.isEmpty
        ? const <CatalogueTrack>[]
        : ref.watch(catalogueSearchProvider(_query)).value?.tracks ?? const [];
    final inset = MediaQuery.viewInsetsOf(context).bottom;
    return Padding(
      padding: EdgeInsets.only(bottom: inset),
      child: SizedBox(
        height: MediaQuery.sizeOf(context).height * 0.8,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(
                  Space.gutter, Space.lg, Space.gutter, Space.sm),
              child:
                  Text('Add songs to the Jam', style: context.text.titleLarge),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: Space.gutter),
              child: TextField(
                controller: _field,
                autofocus: true,
                onChanged: _typed,
                decoration: const InputDecoration(
                  labelText: 'Search songs',
                  prefixIcon: Icon(Icons.search_rounded),
                ),
              ),
            ),
            Expanded(
              child: ListView(
                padding: const EdgeInsets.only(bottom: Space.xxl),
                children: [
                  if (_query.isNotEmpty && library.isEmpty && catalogue.isEmpty)
                    Padding(
                      padding: const EdgeInsets.all(Space.gutter),
                      child: Text('No songs found for "$_query".',
                          style: context.text.bodyMedium
                              ?.copyWith(color: c.onBgMuted)),
                    ),
                  if (library.isNotEmpty) ...[
                    _heading(context, 'In your library'),
                    for (final t in library.take(8))
                      _SongRow(
                        title: t.title,
                        artist: t.artist,
                        added: _added.contains('lib:${t.id}'),
                        onAdd: () => _add(
                          'lib:${t.id}',
                          Add(t.id,
                              title: t.title,
                              artist: t.artist,
                              album: realAlbumName(t.album),
                              durationSec: t.durationSec),
                        ),
                      ),
                  ],
                  if (catalogue.isNotEmpty) ...[
                    _heading(context, 'Not in your library yet'),
                    for (final t in catalogue.take(6))
                      _SongRow(
                        title: t.title,
                        artist: t.artistName,
                        added: _added.contains('cat:${t.id}'),
                        onAdd: () => _add(
                          'cat:${t.id}',
                          Add('cat:${t.id}',
                              title: t.title,
                              artist: t.artistName,
                              album: t.albumTitle,
                              durationSec: t.duration?.inSeconds,
                              imageUrl: t.coverUrl,
                              artistRef: t.artistId),
                        ),
                      ),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _heading(BuildContext context, String text) => Padding(
        padding: const EdgeInsets.fromLTRB(
            Space.gutter, Space.lg, Space.gutter, Space.xs),
        child: Text(text, style: context.text.titleSmall),
      );
}

class _SongRow extends StatelessWidget {
  const _SongRow({
    required this.title,
    required this.artist,
    required this.added,
    required this.onAdd,
  });

  final String title;
  final String? artist;
  final bool added;
  final VoidCallback onAdd;

  @override
  Widget build(BuildContext context) => ListTile(
        title: Text(title, maxLines: 1, overflow: TextOverflow.ellipsis),
        subtitle: artist == null ? null : Text(artist!),
        trailing: added
            ? Icon(Icons.check_rounded, color: context.colors.accent)
            : const Icon(Icons.add_circle_outline_rounded),
        onTap: added ? null : onAdd,
      );
}
