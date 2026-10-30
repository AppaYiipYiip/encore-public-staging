import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/providers.dart';
import '../../data/encore/encore_models.dart';
import '../../design/tokens.dart';
import '../common/widgets.dart';
import 'news_providers.dart';
import 'news_time.dart';

/// What's new (docs/design S-24, ADR-R44): the one place news lives. Four kinds and no others; the items that were unread when the person came
/// are shown under "New" with a green dot and a bold title, and are read as soon as they have been shown. Nothing is sent to the phone from
/// here.
class NewsScreen extends ConsumerStatefulWidget {
  const NewsScreen({super.key});

  @override
  ConsumerState<NewsScreen> createState() => _NewsScreenState();
}

class _NewsScreenState extends ConsumerState<NewsScreen> {
  /// Ids that were unread when this page first saw them: they stay under "New" for as long as the page is open, though they are read at once.
  final Set<int> _fresh = {};

  @override
  Widget build(BuildContext context) {
    final news = ref.watch(newsProvider);
    for (final item in news.items) {
      if (!item.read) _fresh.add(item.id);
    }
    if (news.unread > 0) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) ref.read(newsProvider.notifier).markAllRead();
      });
    }
    final now = ref.watch(clockProvider).now();
    final fresh = [
      for (final n in news.items)
        if (_fresh.contains(n.id)) n
    ];
    final earlier = [
      for (final n in news.items)
        if (!_fresh.contains(n.id)) n
    ];

    return Scaffold(
      appBar: AppBar(title: const Text("What's new")),
      body: RefreshIndicator(
        onRefresh: ref.read(newsProvider.notifier).refresh,
        child: news.items.isEmpty
            ? ListView(children: [
                SizedBox(
                  height: MediaQuery.sizeOf(context).height * 0.6,
                  child: EmptyState(
                    icon: Icons.notifications_none_rounded,
                    title: news.loaded ? 'Nothing new yet' : 'Looking for news',
                    message: news.loaded
                        ? 'New releases from artists you play, and news from '
                            'your server, show up here. Nothing is sent to '
                            'your phone unless you ask.'
                        : null,
                  ),
                ),
              ])
            : ListView(
                children: [
                  if (fresh.isNotEmpty) ...[
                    const _Heading('New'),
                    for (final item in fresh)
                      _NewsRow(item: item, fresh: true, now: now),
                  ],
                  if (earlier.isNotEmpty) ...[
                    const _Heading('Earlier'),
                    for (final item in earlier)
                      _NewsRow(item: item, fresh: false, now: now),
                  ],
                  const SizedBox(height: Space.xxl),
                ],
              ),
      ),
    );
  }
}

class _Heading extends StatelessWidget {
  const _Heading(this.text);

  final String text;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(
            Space.gutter, Space.lg, Space.gutter, Space.sm),
        child: Semantics(
            header: true, child: Text(text, style: context.text.titleMedium)),
      );
}

class _NewsRow extends StatelessWidget {
  const _NewsRow({required this.item, required this.fresh, required this.now});

  final EncoreNews item;
  final bool fresh;
  final DateTime now;

  static IconData _icon(EncoreNewsKind kind) => switch (kind) {
        EncoreNewsKind.release => Icons.album_outlined,
        EncoreNewsKind.jam => Icons.groups_outlined,
        EncoreNewsKind.inviteUsed => Icons.person_add_alt_outlined,
        EncoreNewsKind.importDone => Icons.playlist_add_check_rounded,
      };

  /// Where a tap goes: a place inside this app, as the server wrote it; anything else (an address of the internet) is not followed.
  static String? _place(String? route) {
    if (route == null || !route.startsWith('/') || route.startsWith('//')) {
      return null;
    }
    return Uri.tryParse(route)?.hasScheme == false ? route : null;
  }

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final place = _place(item.route);
    final when = newsTimeLabel(
        now, DateTime.fromMillisecondsSinceEpoch(item.createdAtMs));
    return Semantics(
      label: '${fresh ? 'New. ' : ''}${item.title}. '
          '${item.body ?? ''} $when',
      button: place != null,
      excludeSemantics: true,
      child: InkWell(
        onTap: place == null ? null : () => context.push(place),
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: 72),
          child: Padding(
            padding: const EdgeInsets.symmetric(
                horizontal: Space.gutter, vertical: Space.md),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(_icon(item.kind), color: c.onBgMuted),
                const SizedBox(width: Space.lg),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(children: [
                        if (fresh) ...[
                          Container(
                            width: 8,
                            height: 8,
                            decoration: BoxDecoration(
                                color: c.accent, shape: BoxShape.circle),
                          ),
                          const SizedBox(width: Space.sm),
                        ],
                        Expanded(
                          child: Text(
                            item.title,
                            style: context.text.titleSmall?.copyWith(
                                fontWeight:
                                    fresh ? FontWeight.w800 : FontWeight.w500),
                          ),
                        ),
                      ]),
                      if (item.body != null)
                        Text(item.body!,
                            style: context.text.bodyMedium
                                ?.copyWith(color: c.onBgMuted)),
                    ],
                  ),
                ),
                const SizedBox(width: Space.md),
                Text(when,
                    style:
                        context.text.labelSmall?.copyWith(color: c.onBgFaint)),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
