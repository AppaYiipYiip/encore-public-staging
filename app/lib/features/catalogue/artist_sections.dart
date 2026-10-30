import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/catalogue/catalogue_models.dart';
import '../../design/tokens.dart';
import '../common/widgets.dart';
import '../instant/instant_controller.dart';
import '../providers.dart';
import 'catalogue_providers.dart';
import 'catalogue_widgets.dart';

/// The sections of an artist's page, the way streaming apps lay them out: **Popular** songs first, then **Albums**, **Singles and EPs**
/// and **Compilations** each on their own. Used by the page of an artist the library has and by the page of one it does not, so an
/// artist looks the same whichever way the person arrived.

SliverToBoxAdapter loadingSliver() => const SliverToBoxAdapter(
      child: Padding(
        padding: EdgeInsets.all(Space.xl),
        child: Center(child: CircularProgressIndicator()),
      ),
    );

SliverToBoxAdapter retrySliver(VoidCallback onRetry) => SliverToBoxAdapter(
      child: EmptyState(
        icon: Icons.cloud_off_rounded,
        title: 'Nothing to show right now',
        message: 'The music catalogue could not be reached.',
        actionLabel: 'Try again',
        onAction: onRetry,
      ),
    );

/// "Popular": the artist's most played songs. Five at first, ten after "Show more". Tapping one plays it and the rest of the list
/// follows.
class ArtistPopularSection extends ConsumerStatefulWidget {
  const ArtistPopularSection({
    super.key,
    required this.artist,
    required this.sourceId,
    this.collapsedCount = 5,
  });

  final CatalogueArtist artist;

  /// What the player calls the list these songs are played from.
  final String sourceId;

  final int collapsedCount;

  @override
  ConsumerState<ArtistPopularSection> createState() =>
      _ArtistPopularSectionState();
}

class _ArtistPopularSectionState extends ConsumerState<ArtistPopularSection> {
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    final artist = widget.artist;
    final top = ref.watch(catalogueArtistTopProvider(artist.id));
    final facade = ref.watch(playbackFacadeProvider);
    final snapshot = ref.watch(playbackSnapshotProvider).value;
    final instant = ref.watch(instantAvailableProvider);
    final all = top.value ?? const <CatalogueTrack>[];
    final collapsible = all.length > widget.collapsedCount;

    return SliverMainAxisGroup(
      slivers: [
        SliverToBoxAdapter(
          child: SectionHeader(
            title: 'Popular',
            seeAllLabel: _expanded ? 'Show less' : 'Show more',
            onSeeAll: collapsible
                ? () => setState(() => _expanded = !_expanded)
                : null,
          ),
        ),
        top.when(
          loading: loadingSliver,
          error: (_, __) => retrySliver(
              () => ref.invalidate(catalogueArtistTopProvider(artist.id))),
          data: (items) {
            if (items.isEmpty) {
              // The catalogue answered and has no popular songs for this artist (a small or new one): that is not "could not be reached"
              // (AUDIT F25). Its releases are listed below.
              return const SliverToBoxAdapter(
                child: EmptyState(
                  icon: Icons.music_note_rounded,
                  title: 'No popular songs yet',
                  message: "This artist's releases are below.",
                ),
              );
            }
            final shown = collapsible && !_expanded
                ? items.take(widget.collapsedCount).toList()
                : items;
            return SliverList.builder(
              itemCount: shown.length,
              itemBuilder: (context, i) {
                final t = shown[i];
                final status = ref.watch(instantStatusProvider(t.id));
                final playingId = snapshot?.track?.id;
                final current = playingId == t.id ||
                    (status?.track != null && playingId == status!.track!.id);
                void preview() => playPreviewRun(
                      facade,
                      items,
                      index: i,
                      sourceName: artist.name,
                      sourceId: widget.sourceId,
                    );
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
                          .playRun(items,
                              startIndex: i,
                              sourceName: artist.name,
                              sourceId: widget.sourceId))
                      : preview,
                  onLongPress: instant && t.previewUrl != null ? preview : null,
                );
              },
            );
          },
        ),
      ],
    );
  }
}

/// Albums, then singles and EPs, then compilations; a section without releases is not drawn.
class ArtistReleaseSections extends StatelessWidget {
  const ArtistReleaseSections({super.key, required this.releases});

  /// Newest first (as the catalogue providers give them).
  final List<ArtistRelease> releases;

  @override
  Widget build(BuildContext context) {
    final groups = groupReleases(releases);
    return SliverMainAxisGroup(
      slivers: [
        ReleaseSection(title: 'Albums', releases: groups.albums),
        ReleaseSection(
            title: 'Singles and EPs',
            releases: groups.singles,
            collapsedCount: 5),
        ReleaseSection(
            title: 'Compilations',
            releases: groups.compilations,
            collapsedCount: 5),
      ],
    );
  }
}

/// A titled list of releases; long lists start collapsed.
class ReleaseSection extends StatefulWidget {
  const ReleaseSection({
    super.key,
    required this.title,
    required this.releases,
    this.collapsedCount = 8,
  });

  final String title;
  final List<ArtistRelease> releases;
  final int collapsedCount;

  @override
  State<ReleaseSection> createState() => _ReleaseSectionState();
}

class _ReleaseSectionState extends State<ReleaseSection> {
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    final all = widget.releases;
    if (all.isEmpty) return const SliverToBoxAdapter(child: SizedBox.shrink());
    final collapsible = all.length > widget.collapsedCount;
    final visible = collapsible && !_expanded
        ? all.take(widget.collapsedCount).toList()
        : all;
    return SliverMainAxisGroup(
      slivers: [
        SliverToBoxAdapter(
          child: SectionHeader(
            title: widget.title,
            seeAllLabel: _expanded ? 'Show less' : 'Show all',
            onSeeAll: collapsible
                ? () => setState(() => _expanded = !_expanded)
                : null,
          ),
        ),
        SliverList.builder(
          itemCount: visible.length,
          itemBuilder: (context, i) => ReleaseTile(release: visible[i]),
        ),
      ],
    );
  }
}
