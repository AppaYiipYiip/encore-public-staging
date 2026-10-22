import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/navigation.dart';
import '../../design/tokens.dart';
import '../common/cover_art.dart';
import '../common/widgets.dart';
import '../instant/instant_controller.dart';
import '../providers.dart';
import 'catalogue_providers.dart';
import 'catalogue_widgets.dart';

/// One genre of the catalogue, from the Browse grid of the Search tab: what is
/// on top in it. Songs play the way they do on an artist's page (the whole
/// song with the instant-play service, the 30-second sample without).
class CatalogueGenreScreen extends ConsumerWidget {
  const CatalogueGenreScreen({super.key, required this.genreId, this.name});

  final int genreId;
  final String? name;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final chart = ref.watch(catalogueGenreChartProvider(genreId));
    final instant = ref.watch(instantAvailableProvider);
    final facade = ref.watch(playbackFacadeProvider);
    final snapshot = ref.watch(playbackSnapshotProvider).value;
    final sourceId = 'catalogue-genre:$genreId';
    final title = name ?? 'Genre';
    return Scaffold(
      appBar: AppBar(title: Text(title)),
      body: chart.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (_, __) => _Retry(
            onRetry: () =>
                ref.invalidate(catalogueGenreChartProvider(genreId))),
        data: (c) {
          if (c.isEmpty) {
            return _Retry(
                onRetry: () =>
                    ref.invalidate(catalogueGenreChartProvider(genreId)));
          }
          return CustomScrollView(
            slivers: [
              if (c.tracks.isNotEmpty) ...[
                const SliverToBoxAdapter(
                    child: SectionHeader(title: 'Top songs')),
                SliverList.builder(
                  itemCount: c.tracks.length,
                  itemBuilder: (context, i) {
                    final t = c.tracks[i];
                    final status = ref.watch(instantStatusProvider(t.id));
                    final current = snapshot?.track?.id == t.id ||
                        (status?.track != null &&
                            snapshot?.track?.id == status!.track!.id);
                    return PreviewTrackTile(
                      track: t,
                      showCover: true,
                      isCurrent: current,
                      isPlaying: current && (snapshot?.isPlaying ?? false),
                      instant: instant,
                      status: status,
                      onTap: instant
                          ? () => unawaited(ref
                              .read(instantControllerProvider.notifier)
                              .playRun(c.tracks,
                                  startIndex: i,
                                  sourceName: title,
                                  sourceId: sourceId))
                          : () => playPreviewRun(facade, c.tracks,
                              index: i, sourceName: title, sourceId: sourceId),
                    );
                  },
                ),
              ],
              if (c.artists.isNotEmpty) ...[
                const SliverToBoxAdapter(
                    child: SectionHeader(title: 'Top artists')),
                SliverList.builder(
                  itemCount: c.artists.length,
                  itemBuilder: (context, i) {
                    final a = c.artists[i];
                    return ListTile(
                      leading: SizedBox.square(
                        dimension: 48,
                        child: CoverArt(
                          imageUrl: a.imageUrl,
                          circular: true,
                          fallbackLabel: a.name,
                        ),
                      ),
                      title: Text(a.name,
                          maxLines: 1, overflow: TextOverflow.ellipsis),
                      subtitle: const Text('Artist'),
                      onTap: () =>
                          Nav.catalogueArtist(context, a.id, preloaded: a),
                    );
                  },
                ),
              ],
              if (c.albums.isNotEmpty) ...[
                const SliverToBoxAdapter(
                    child: SectionHeader(title: 'Top albums')),
                SliverList.builder(
                  itemCount: c.albums.length,
                  itemBuilder: (context, i) =>
                      ReleaseTile(release: ArtistRelease(c.albums[i])),
                ),
              ],
              const SliverToBoxAdapter(child: SizedBox(height: Space.xxl)),
            ],
          );
        },
      ),
    );
  }
}

class _Retry extends StatelessWidget {
  const _Retry({required this.onRetry});

  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) => EmptyState(
        icon: Icons.cloud_off_rounded,
        title: 'Could not load this genre',
        message: 'It needs the internet. Check your connection and try again.',
        actionLabel: 'Try again',
        onAction: onRetry,
      );
}
