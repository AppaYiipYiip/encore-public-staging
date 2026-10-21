import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/navigation.dart';
import '../../app/providers.dart';
import '../../design/tokens.dart';
import '../../domain/year_in_music.dart';
import '../common/cover_art.dart';
import '../common/format.dart';
import '../common/widgets.dart';
import 'year_providers.dart';

/// Year in Music: what the person played, counted on this phone from the
/// history their own server keeps for them (ADR-064). A month, the year or all
/// time; the minutes, the favourites, the days, the hours of the day, and the
/// kind of listener that makes them, each with the number behind it.
class YearInMusicScreen extends ConsumerWidget {
  const YearInMusicScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final kind = ref.watch(yearPeriodKindProvider);
    final now = ref.watch(clockProvider).now();
    final period = periodFor(kind, now);
    final stats = ref.watch(yearInMusicProvider(period));
    return Scaffold(
      appBar: AppBar(title: const Text('Year in Music')),
      body: ListView(
        padding: const EdgeInsets.only(bottom: Space.xxl),
        children: [
          _PeriodChips(kind: kind, year: now.year),
          stats.when(
            loading: () => const _Loading(),
            error: (_, __) => _Failed(
              onRetry: () {
                ref.invalidate(playHistoryProvider);
              },
            ),
            data: (s) => s.isEmpty
                ? const EmptyState(
                    icon: Icons.insights_rounded,
                    title: 'Nothing to count yet',
                    message:
                        'Play some music and what you listen to will show up here.',
                  )
                : _Stats(stats: s, kind: kind),
          ),
        ],
      ),
    );
  }
}

class _PeriodChips extends ConsumerWidget {
  const _PeriodChips({required this.kind, required this.year});

  final YearPeriodKind kind;
  final int year;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    Widget chip(YearPeriodKind k, String label) => Padding(
          padding: const EdgeInsets.only(right: Space.sm),
          child: ChoiceChip(
            label: Text(label),
            selected: kind == k,
            onSelected: (_) =>
                ref.read(yearPeriodKindProvider.notifier).choose(k),
          ),
        );
    return Padding(
      padding: const EdgeInsets.fromLTRB(
          Space.gutter, Space.sm, Space.gutter, Space.sm),
      child: Row(
        children: [
          chip(YearPeriodKind.month, 'This month'),
          chip(YearPeriodKind.year, '$year'),
          chip(YearPeriodKind.allTime, 'All time'),
        ],
      ),
    );
  }
}

class _Loading extends StatelessWidget {
  const _Loading();

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.all(Space.xxl),
        child: Column(
          children: [
            const CircularProgressIndicator(),
            const SizedBox(height: Space.lg),
            Text('Reading your listening history…',
                style: context.text.bodyMedium
                    ?.copyWith(color: context.colors.onBgMuted)),
          ],
        ),
      );
}

class _Failed extends StatelessWidget {
  const _Failed({required this.onRetry});

  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) => EmptyState(
        icon: Icons.cloud_off_rounded,
        title: 'Could not read your listening history.',
        message: 'Your server keeps it. Check that it can be reached.',
        actionLabel: 'Try again',
        onAction: onRetry,
      );
}

// ----------------------------------------------------------------- the stats

class _Stats extends StatelessWidget {
  const _Stats({required this.stats, required this.kind});

  final YearInMusic stats;
  final YearPeriodKind kind;

  @override
  Widget build(BuildContext context) {
    final s = stats;
    final span = switch (kind) {
      YearPeriodKind.month => 'this month',
      YearPeriodKind.year => 'this year',
      YearPeriodKind.allTime => 'so far',
    };
    return Column(
      // The cards use the whole width; a column that starts its children at
      // the left would make each one only as wide as its text.
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _Hero(stats: s, span: span),
        _PersonalityCard(result: s.personality),
        if (s.topSongs.isNotEmpty) ...[
          const SectionHeader(title: 'Top songs'),
          for (var i = 0; i < s.topSongs.length; i++)
            _SongRow(rank: i + 1, ranked: s.topSongs[i]),
        ],
        if (s.topArtists.isNotEmpty) ...[
          const SectionHeader(title: 'Top artists'),
          for (var i = 0; i < s.topArtists.length; i++)
            _NameRow(rank: i + 1, entry: s.topArtists[i], circular: true),
        ],
        if (s.topAlbums.isNotEmpty) ...[
          const SectionHeader(title: 'Top albums'),
          for (var i = 0; i < s.topAlbums.length; i++)
            _NameRow(rank: i + 1, entry: s.topAlbums[i], album: true),
        ],
        if (s.topGenres.isNotEmpty) ...[
          const SectionHeader(title: 'Top genres'),
          _GenreBars(genres: s.topGenres),
        ],
        // One play on a day is not a busiest day.
        if (s.busiestDay != null && s.busiestDay!.plays >= 2) ...[
          const SectionHeader(title: 'Your busiest day'),
          _Fact(
            big: _dayLabel(s.busiestDay!.day),
            small: plural(s.busiestDay!.plays, 'play'),
          ),
        ],
        if (s.longestStreak > 0) ...[
          const SectionHeader(title: 'Longest streak'),
          _Fact(big: '${plural(s.longestStreak, 'day')} in a row'),
        ],
        const SectionHeader(title: 'When you listen'),
        _Clock(counts: s.clock),
        if (s.newArtists.isNotEmpty) ...[
          const SectionHeader(title: 'New to you'),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: Space.gutter),
            child: Wrap(
              spacing: Space.sm,
              runSpacing: Space.sm,
              children: [
                for (final a in s.newArtists.take(10))
                  Chip(label: Text(a.name)),
              ],
            ),
          ),
        ],
        if (s.firstSong != null && s.lastSong != null) ...[
          const SectionHeader(title: 'First and latest'),
          _Fact(
            small: 'First: ${s.firstSong!.song.title} '
                '(${_shortDate(s.firstSong!.at)})',
          ),
          _Fact(
            small: 'Latest: ${s.lastSong!.song.title} '
                '(${_shortDate(s.lastSong!.at)})',
          ),
        ],
      ],
    );
  }
}

const _months = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
];
const _weekdays = [
  'Monday',
  'Tuesday',
  'Wednesday',
  'Thursday',
  'Friday',
  'Saturday',
  'Sunday',
];

String _dayLabel(DateTime d) =>
    '${_weekdays[d.weekday - 1]} ${d.day} ${_months[d.month - 1]}';

String _shortDate(DateTime d) =>
    '${d.day} ${_months[d.month - 1].substring(0, 3)}';

class _Hero extends StatelessWidget {
  const _Hero({required this.stats, required this.span});

  final YearInMusic stats;
  final String span;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    return Container(
      margin: const EdgeInsets.fromLTRB(
          Space.gutter, Space.md, Space.gutter, Space.sm),
      padding: const EdgeInsets.all(Space.xl),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(Radii.hero),
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [c.accent.withValues(alpha: 0.45), c.surface],
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('You listened for', style: context.text.bodyMedium),
          const SizedBox(height: Space.xs),
          Text(
            '${_thousands(stats.minutes)} ${stats.minutes == 1 ? 'minute' : 'minutes'}',
            style: context.text.displaySmall
                ?.copyWith(fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: Space.sm),
          Text(
            '${plural(stats.plays, 'play')} · '
            '${plural(stats.distinctSongs, 'song')} · '
            '${plural(stats.distinctArtists, 'artist')} $span',
            style: context.text.bodyMedium?.copyWith(color: c.onBgMuted),
          ),
        ],
      ),
    );
  }
}

String _thousands(int n) {
  final s = '$n';
  final out = StringBuffer();
  for (var i = 0; i < s.length; i++) {
    if (i > 0 && (s.length - i) % 3 == 0) out.write(',');
    out.write(s[i]);
  }
  return out.toString();
}

class _PersonalityCard extends StatelessWidget {
  const _PersonalityCard({required this.result});

  final PersonalityResult result;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final title = result.kind.title;
    final article = 'AEIOU'.contains(title[0]) ? 'an' : 'a';
    return Container(
      margin:
          const EdgeInsets.fromLTRB(Space.gutter, 0, Space.gutter, Space.sm),
      padding: const EdgeInsets.all(Space.lg),
      decoration: BoxDecoration(
        color: c.surface,
        borderRadius: BorderRadius.circular(Radii.hero),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('You are $article $title', style: context.text.titleLarge),
          const SizedBox(height: Space.xs),
          Text(result.reason,
              style: context.text.bodyMedium?.copyWith(color: c.onBgMuted)),
        ],
      ),
    );
  }
}

class _Rank extends StatelessWidget {
  const _Rank(this.rank);

  final int rank;

  @override
  Widget build(BuildContext context) => SizedBox(
        width: 28,
        child: Text('$rank',
            style: context.text.titleMedium
                ?.copyWith(color: context.colors.onBgMuted)),
      );
}

class _SongRow extends StatelessWidget {
  const _SongRow({required this.rank, required this.ranked});

  final int rank;
  final RankedSong ranked;

  @override
  Widget build(BuildContext context) {
    final song = ranked.song;
    return ListTile(
      leading: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          _Rank(rank),
          SizedBox.square(
            dimension: 48,
            child:
                CoverArt(coverArtId: song.coverArt, fallbackLabel: song.title),
          ),
        ],
      ),
      title: Text(song.title, maxLines: 1, overflow: TextOverflow.ellipsis),
      subtitle: song.artist == null ? null : Text(song.artist!),
      trailing: Text(plural(ranked.plays, 'play'),
          style: context.text.bodyMedium
              ?.copyWith(color: context.colors.onBgMuted)),
      onTap:
          song.albumId == null ? null : () => Nav.album(context, song.albumId!),
    );
  }
}

class _NameRow extends StatelessWidget {
  const _NameRow({
    required this.rank,
    required this.entry,
    this.circular = false,
    this.album = false,
  });

  final int rank;
  final RankedName entry;
  final bool circular;
  final bool album;

  @override
  Widget build(BuildContext context) {
    final id = entry.id;
    return ListTile(
      leading: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          _Rank(rank),
          SizedBox.square(
            dimension: 48,
            child: CoverArt(
              coverArtId: entry.coverArt,
              fallbackLabel: entry.name,
              circular: circular,
            ),
          ),
        ],
      ),
      title: Text(entry.name, maxLines: 1, overflow: TextOverflow.ellipsis),
      subtitle: Text([
        if (album && entry.artist != null) entry.artist!,
        '${entry.minutes} min',
      ].join(' · ')),
      trailing: Text(plural(entry.plays, 'play'),
          style: context.text.bodyMedium
              ?.copyWith(color: context.colors.onBgMuted)),
      onTap: id == null
          ? null
          : () => album ? Nav.album(context, id) : Nav.artist(context, id),
    );
  }
}

class _GenreBars extends StatelessWidget {
  const _GenreBars({required this.genres});

  final List<RankedName> genres;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final most = genres.first.plays;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: Space.gutter),
      child: Column(
        children: [
          for (final g in genres)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: Space.xs),
              child: Row(
                children: [
                  SizedBox(
                    width: 110,
                    child: Text(g.name,
                        maxLines: 1, overflow: TextOverflow.ellipsis),
                  ),
                  Expanded(
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(Radii.pill),
                      child: LinearProgressIndicator(
                        value: g.plays / most,
                        minHeight: 10,
                        backgroundColor: c.surface,
                        color: c.accent,
                      ),
                    ),
                  ),
                  const SizedBox(width: Space.sm),
                  SizedBox(
                    width: 36,
                    child: Text('${g.plays}',
                        textAlign: TextAlign.end,
                        style: context.text.bodyMedium
                            ?.copyWith(color: c.onBgMuted)),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

class _Fact extends StatelessWidget {
  const _Fact({this.big, this.small});

  final String? big;
  final String? small;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(
            horizontal: Space.gutter, vertical: Space.xxs),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (big != null) Text(big!, style: context.text.titleLarge),
            if (small != null)
              Text(small!,
                  style: context.text.bodyMedium
                      ?.copyWith(color: context.colors.onBgMuted)),
          ],
        ),
      );
}

/// Plays in each hour of the day, as 24 bars.
class _Clock extends StatelessWidget {
  const _Clock({required this.counts});

  final List<int> counts;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final most = counts.fold<int>(1, (a, b) => b > a ? b : a);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: Space.gutter),
      child: Semantics(
        label: 'Plays in each hour of the day',
        child: Column(
          children: [
            SizedBox(
              height: 90,
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  for (var h = 0; h < 24; h++)
                    Expanded(
                      child: Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 1),
                        child: Container(
                          height: 4 + 86 * counts[h] / most,
                          decoration: BoxDecoration(
                            color: counts[h] == 0 ? c.surface : c.accent,
                            borderRadius: BorderRadius.circular(2),
                          ),
                        ),
                      ),
                    ),
                ],
              ),
            ),
            const SizedBox(height: Space.xs),
            // Each label starts under the bar of its hour: a quarter of the
            // width is six hours.
            Row(
              children: [
                for (final label in const ['12 am', '6 am', '12 pm', '6 pm'])
                  Expanded(
                    child: Text(label,
                        style: context.text.labelSmall
                            ?.copyWith(color: c.onBgFaint)),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
