import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../app/navigation.dart';
import '../../app/tab_reselect.dart';
import '../../data/catalogue/catalogue_models.dart';
import '../../design/tokens.dart';
import '../common/away_words.dart';
import '../common/playability.dart';
import '../common/widgets.dart';
import '../providers.dart';
import 'search_results.dart';

/// Recent searches, persisted locally (most recent first, max 10).
class RecentSearches extends Notifier<List<String>> {
  static const _key = 'encore.recent_searches';

  @override
  List<String> build() {
    unawaited(_load());
    return const [];
  }

  Future<void> _load() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      state = prefs.getStringList(_key) ?? const [];
    } on Object {
      // Preference storage is a convenience; never block search on it.
    }
  }

  Future<void> add(String query) async {
    final q = query.trim();
    if (q.length < 2) return;
    final next = [q, ...state.where((e) => e.toLowerCase() != q.toLowerCase())]
        .take(10)
        .toList();
    state = next;
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setStringList(_key, next);
    } on Object {
      // ignore: see above
    }
  }

  Future<void> clear() async {
    state = const [];
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.remove(_key);
    } on Object {
      // ignore: see above
    }
  }
}

final recentSearchesProvider =
    NotifierProvider<RecentSearches, List<String>>(RecentSearches.new);

/// Search (docs/06-ux-spec.md 4.2): instant offline results from the local
/// FTS index; browse-by-genre when the query is empty. While the server is away (P1-16, S-11 offline) the field says what can still be
/// searched and the genre tiles are dimmed: the page is the same for both causes.
class SearchScreen extends ConsumerStatefulWidget {
  const SearchScreen({super.key});

  @override
  ConsumerState<SearchScreen> createState() => _SearchScreenState();
}

class _SearchScreenState extends ConsumerState<SearchScreen> {
  final _controller = TextEditingController();
  final _focus = FocusNode();
  Timer? _debounce;
  String _query = '';

  @override
  void dispose() {
    _debounce?.cancel();
    _controller.dispose();
    _focus.dispose();
    super.dispose();
  }

  void _onChanged(String text) {
    // Local FTS is fast enough to run on every keystroke; the tiny debounce
    // only coalesces rapid typing.
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 90), () {
      if (mounted) setState(() => _query = text.trim());
    });
  }

  void _commit(String text) {
    ref.read(recentSearchesProvider.notifier).add(text);
  }

  /// A second tap on the Search tab (N-22): the first search page, as if nothing had been searched.
  void _backToFirstPage() {
    _debounce?.cancel();
    _controller.clear();
    _focus.unfocus();
    if (_query.isNotEmpty) setState(() => _query = '');
    scrollPageToTop(context);
  }

  @override
  Widget build(BuildContext context) {
    ref.onTabReselected(MainTab.search, _backToFirstPage);
    // The lasting state, not the strip's: the hint stays for as long as the outage does (D-45) and leaves by itself.
    final away = ref.watch(serverAwayProvider);
    return SafeArea(
      bottom: false,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(
                Space.gutter, Space.lg, Space.gutter, Space.md),
            child: Text('Search', style: context.text.headlineMedium),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: Space.gutter),
            child: TextField(
              controller: _controller,
              focusNode: _focus,
              onChanged: _onChanged,
              onSubmitted: _commit,
              textInputAction: TextInputAction.search,
              style: context.text.bodyLarge,
              decoration: InputDecoration(
                hintText:
                    away ? kSearchHintAway : 'What do you want to listen to?',
                prefixIcon: const Icon(Icons.search_rounded),
                suffixIcon: _query.isEmpty
                    ? null
                    : IconButton(
                        tooltip: 'Clear',
                        icon: const Icon(Icons.close_rounded),
                        onPressed: () {
                          _controller.clear();
                          setState(() => _query = '');
                        },
                      ),
                filled: true,
                fillColor: context.colors.surfaceHigh,
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(Radii.card),
                  borderSide: BorderSide.none,
                ),
                contentPadding: const EdgeInsets.symmetric(vertical: 14),
              ),
            ),
          ),
          const SizedBox(height: Space.sm),
          Expanded(
            child: _query.isEmpty
                ? _Browse(
                    onRecent: (q) {
                      _controller.text = q;
                      setState(() => _query = q);
                    },
                  )
                : SearchResultsView(query: _query, onOpen: _commit),
          ),
        ],
      ),
    );
  }
}

class _Browse extends ConsumerWidget {
  const _Browse({required this.onRecent});

  final ValueChanged<String> onRecent;

  // Own palette (not Spotify's tile colours): saturated but dark enough for
  // white text at >= 4.5:1.
  static const _tileColors = [
    Color(0xFF2B5CE6),
    Color(0xFF7A3FD0),
    Color(0xFFC2255C),
    Color(0xFF1F8A4C),
    Color(0xFFB45309),
    Color(0xFF0E7490),
    Color(0xFF5B21B6),
    Color(0xFFB91C1C),
    Color(0xFF4D7C0F),
    Color(0xFF9D174D),
    Color(0xFF0F766E),
    Color(0xFF9A3412),
  ];

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final recents = ref.watch(recentSearchesProvider);
    final genres = ref.watch(genresProvider).value ?? const [];
    // The catalogue's genres need the server: while it is away their tiles are dimmed, not removed, and a tap says why (S-13 offline).
    final away = ref.watch(serverAwayProvider);
    return CustomScrollView(
      slivers: [
        if (recents.isNotEmpty) ...[
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(
                  Space.gutter, Space.lg, Space.sm, Space.xs),
              child: Row(
                children: [
                  Expanded(
                      child: Text('Recent searches',
                          style: context.text.titleMedium)),
                  TextButton(
                    onPressed: () =>
                        ref.read(recentSearchesProvider.notifier).clear(),
                    child: const Text('Clear'),
                  ),
                ],
              ),
            ),
          ),
          SliverList.builder(
            itemCount: recents.length,
            itemBuilder: (context, i) => ListTile(
              leading: const Icon(Icons.history_rounded),
              title: Text(recents[i]),
              onTap: () => onRecent(recents[i]),
            ),
          ),
        ],
        // The catalogue's genres: never an empty page, whatever the library holds
        // (a friend with no songs saw nothing at all).
        const SliverToBoxAdapter(child: SectionHeader(title: 'Browse all')),
        SliverPadding(
          padding: const EdgeInsets.symmetric(horizontal: Space.gutter),
          sliver: SliverGrid.builder(
            gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
              crossAxisCount: 2,
              mainAxisExtent: 88,
              crossAxisSpacing: Space.md,
              mainAxisSpacing: Space.md,
            ),
            itemCount: kCatalogueGenres.length,
            itemBuilder: (context, i) => _GenreTile(
              name: kCatalogueGenres[i].name,
              color: _tileColors[i % _tileColors.length],
              dimmed: away,
              onTap: () => Nav.catalogueGenre(
                  context, kCatalogueGenres[i].id, kCatalogueGenres[i].name),
            ),
          ),
        ),
        if (genres.isNotEmpty) ...[
          const SliverToBoxAdapter(
              child: SectionHeader(title: 'In your library')),
          SliverPadding(
            padding: const EdgeInsets.symmetric(horizontal: Space.gutter),
            sliver: SliverGrid.builder(
              gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
                crossAxisCount: 2,
                mainAxisExtent: 88,
                crossAxisSpacing: Space.md,
                mainAxisSpacing: Space.md,
              ),
              itemCount: genres.length,
              itemBuilder: (context, i) => _GenreTile(
                name: genres[i].name,
                color: _tileColors[i % _tileColors.length],
                onTap: () => Nav.genre(context, genres[i].name),
              ),
            ),
          ),
        ],
        const SliverToBoxAdapter(child: SizedBox(height: Space.xxl)),
      ],
    );
  }
}

class _GenreTile extends StatelessWidget {
  const _GenreTile(
      {required this.name,
      required this.color,
      required this.onTap,
      this.dimmed = false});

  final String name;
  final Color color;
  final VoidCallback onTap;

  /// The tile needs the server and it is away (S-11 offline: 45 %, as every "cannot be played now" look). It stays a button: a tap says why.
  final bool dimmed;

  @override
  Widget build(BuildContext context) {
    final tile = Semantics(
      button: true,
      label: 'Genre $name',
      excludeSemantics: true,
      child: Material(
        color: color,
        borderRadius: BorderRadius.circular(Radii.card),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.all(Space.md),
            child: Align(
              alignment: Alignment.topLeft,
              child: Text(
                name,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: context.text.titleMedium?.copyWith(
                    color: Colors.white, fontWeight: FontWeight.w800),
              ),
            ),
          ),
        ),
      ),
    );
    return dimmed ? Opacity(opacity: 0.45, child: tile) : tile;
  }
}
