import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../data/encore/encore_api.dart';
import '../../data/encore/encore_live.dart';
import '../../data/encore/encore_models.dart';

/// What the bell holds on this phone: the server's news, newest first, and how many are unread in all.
@immutable
class NewsState {
  const NewsState({
    this.items = const [],
    this.unread = 0,
    this.cursor = '0',
    this.loaded = false,
    this.available = false,
  });

  final List<EncoreNews> items;
  final int unread;

  /// What to ask "only what is newer" with.
  final String cursor;

  /// The server has answered at least once.
  final bool loaded;

  /// There is a bell at all: only an Encore server keeps news (the screens follow what the server offers, ADR-R42).
  final bool available;

  NewsState copyWith({List<EncoreNews>? items, int? unread}) => NewsState(
        items: items ?? this.items,
        unread: unread ?? this.unread,
        cursor: cursor,
        loaded: loaded,
        available: available,
      );
}

/// How much news the phone keeps in memory (the server keeps 200 per person).
const int newsKept = 200;

/// The Encore server's API when this phone is on one (only an Encore server keeps news), else `null`: no bell. Tests replace it.
final newsApiProvider = Provider<EncoreApi?>((ref) {
  final session = ref.watch(sessionProvider).value;
  return session != null && session.encoreMode ? session.encore : null;
});

/// What the server says down the live channel. Tests replace it.
final newsEventsProvider = Provider<Stream<LiveEvent>>((ref) {
  return ref.watch(sessionProvider).value?.live?.events ?? const Stream.empty();
});

/// The bell (docs/tasks P2-15, ADR-R44): fetched when the app starts and whenever the server says there is something new, never polled.
/// Nothing here posts to the phone's notification shade; that is a setting the person has to switch on.
final newsProvider =
    NotifierProvider<NewsController, NewsState>(NewsController.new);

class NewsController extends Notifier<NewsState> {
  StreamSubscription<LiveEvent>? _events;

  @override
  NewsState build() {
    final api = ref.watch(newsApiProvider);
    ref.onDispose(() => _events?.cancel());
    if (api == null) return const NewsState();
    // `hello` is what the server says to a phone that has just connected (a start, a return to the app): the news that came meanwhile.
    _events = ref.watch(newsEventsProvider).listen((event) {
      if (event.type == 'notification.new' || event.type == 'hello') {
        unawaited(refresh());
      }
    });
    Future.microtask(refresh);
    return const NewsState(available: true);
  }

  /// Asks the server for what is new since the last answer. A server that does not answer leaves the bell as it was.
  Future<void> refresh() async {
    final api = ref.read(newsApiProvider);
    if (api == null) return;
    final since = state.loaded ? state.cursor : null;
    final list = (await api.notifications(since: since)).valueOrNull;
    if (list == null) return;
    final known = {for (final n in list.items) n.id};
    final merged = since == null
        ? list.items
        : [...list.items, ...state.items.where((n) => !known.contains(n.id))];
    state = NewsState(
      items: merged.length > newsKept ? merged.sublist(0, newsKept) : merged,
      unread: list.unread,
      cursor: list.cursor,
      loaded: true,
      available: true,
    );
  }

  /// The person has seen the news: it is read here at once, and on the server (which tells the person's other phones the same).
  Future<void> markAllRead() async {
    final api = ref.read(newsApiProvider);
    final newest = state.items.firstOrNull;
    if (api == null || newest == null || state.unread == 0) return;
    state = state.copyWith(
        items: [for (final n in state.items) n.read ? n : n.asRead()],
        unread: 0);
    await api.markNewsRead(upTo: newest.id);
  }
}
