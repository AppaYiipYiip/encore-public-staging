import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/navigation.dart';
import '../../design/tokens.dart';
import '../common/away_words.dart';
import '../common/cover_art.dart';
import '../common/playability.dart';
import '../common/widgets.dart';
import '../instant/instant_controller.dart';
import '../instant/song_marks.dart';
import '../instant/tap_play.dart';
import '../providers.dart';
import 'catalogue_providers.dart';
import 'catalogue_widgets.dart';

/// One genre of the catalogue, from the Browse grid of the Search tab: what is
/// on top in it. Songs play the way they do on an artist's page (the whole
/// song with the instant-play service, the 30-second sample without).
///
/// While the server is away (P1-16, S-13 offline) the page says what cannot be done, in the words of its cause, and the catalogue is not
/// asked: the chart is only watched (and so only fetched) when the page can have it. It follows the connection both ways by itself.
class CatalogueGenreScreen extends ConsumerWidget {
  const CatalogueGenreScreen({super.key, required this.genreId, this.name});

  final int genreId;
  final String? name;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final title = name ?? 'Genre';
    final cause = ref.watch(awayCauseProvider);
    return Scaffold(
      appBar: AppBar(title: Text(title)),
      body: cause != null
          ? EmptyState(
              icon: Icons.cloud_off_rounded,
              title: kGenreUnavailableTitle,
              message: browsingNeeds(cause),
              actionLabel: kGenreBack,
              // Normally the Browse grid pushed this page; opened any other way, Search is the page to go back to.
              onAction: () =>
                  context.canPop() ? context.pop() : context.go('/search'),
            )
          : _GenreChart(genreId: genreId, title: title),
    );
  }
}

class _GenreChart extends ConsumerWidget {
  const _GenreChart({required this.genreId, required this.title});

  final int genreId;
  final String title;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final chart = ref.watch(catalogueGenreChartProvider(genreId));
    final snapshot = ref.watch(playbackSnapshotProvider).value;
    final sourceId = 'catalogue-genre:$genreId';
    return chart.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (_, __) => _Retry(
          onRetry: () => ref.invalidate(catalogueGenreChartProvider(genreId))),
      data: (c) {
        if (c.isEmpty) {
          return _Retry(
              onRetry: () =>
                  ref.invalidate(catalogueGenreChartProvider(genreId)));
        }
        // The songs the server already knows it cannot get are marked (N-13): one question for the whole chart.
        ref.watch(songMarksCheckProvider(TrackList(c.tracks)));
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
                  return CatalogueTrackTile(
                    track: t,
                    showCover: true,
                    isCurrent: current,
                    isPlaying: current && (snapshot?.isPlaying ?? false),
                    status: status,
                    mark: ref.watch(songMarkProvider(t.id)),
                    onTap: () => unawaited(tapPlayRun(ref, c.tracks,
                        startIndex: i, sourceName: title, sourceId: sourceId)),
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
