import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../core/logger.dart';
import '../../data/db/app_database.dart';
import '../instant/instant_controller.dart';
import '../instant/library_resolver.dart';
import 'playback_facade.dart';
import 'streamed_song.dart'
    show libraryLookDelaysProvider, resolvedLibraryIdsProvider;

/// A like the person asked for on a song the service is still putting into the
/// library.
@immutable
class PendingLike {
  const PendingLike({
    required this.trackId,
    required this.artist,
    required this.title,
    this.album,
  });

  /// The id the player knows the song by (not a library id: there is none yet).
  final String trackId;
  final String artist;
  final String title;
  final String? album;
}

@immutable
class PendingLikesState {
  const PendingLikesState({this.waiting = const {}, this.failedMessage});

  /// Likes waiting for their song to be listed, by [PendingLike.trackId].
  final Map<String, PendingLike> waiting;

  /// A sentence for a like that could not be delivered, until it is shown.
  final String? failedMessage;
}

/// "Like" on a song that is not in the library yet (owner, 2026-10-17: pressing
/// the heart on a song being fetched "does not add it, or it does, hella slow").
///
/// The tap is answered at once (the heart is on while the like is waiting), the
/// like is delivered to the library's copy of the song the moment the music
/// server lists it, and it survives leaving the player. A second press before
/// that takes it back. If the song never arrives the heart goes back off with a
/// sentence saying so: what is shown stays what is true.
class PendingLikes extends Notifier<PendingLikesState> {
  @override
  PendingLikesState build() => const PendingLikesState();

  /// Likes the song, or takes the waiting like back.
  void toggle(NowPlayingTrack track) {
    if (state.waiting.containsKey(track.id)) {
      state = PendingLikesState(
        waiting: {...state.waiting}..remove(track.id),
        failedMessage: state.failedMessage,
      );
      return;
    }
    final like = PendingLike(
      trackId: track.id,
      artist: track.artist ?? '',
      title: track.title,
      album: track.album,
    );
    state = PendingLikesState(
      waiting: {...state.waiting, track.id: like},
      failedMessage: state.failedMessage,
    );
    unawaited(_deliver(like));
  }

  /// The message was shown.
  void failureShown() {
    if (state.failedMessage == null) return;
    state = PendingLikesState(waiting: state.waiting);
  }

  bool _stillWanted(PendingLike like) =>
      ref.mounted && state.waiting.containsKey(like.trackId);

  void _drop(PendingLike like, {String? because}) {
    if (!ref.mounted) return;
    state = PendingLikesState(
      waiting: {...state.waiting}..remove(like.trackId),
      failedMessage: because ?? state.failedMessage,
    );
  }

  Future<void> _deliver(PendingLike like) async {
    final resolver = ref.read(libraryResolverProvider);
    final delays = ref.read(libraryLookDelaysProvider);
    for (var attempt = 0;; attempt++) {
      if (!_stillWanted(like)) return;
      TrackRow? row = ref.read(instantStatusProvider(like.trackId))?.track;
      row ??= await resolver
          ?.find(artist: like.artist, title: like.title, album: like.album)
          .onError((_, __) => null);
      if (!_stillWanted(like)) return; // taken back while looking
      if (row != null) {
        final session = ref.read(sessionProvider).value;
        if (session == null) break;
        // Everybody who shows this song now knows which library song it is,
        // and the library copy is starred before the wait is over: the heart
        // has no moment in which it is off.
        ref
            .read(resolvedLibraryIdsProvider.notifier)
            .learn(like.trackId, row.id);
        await session.mutations.setTrackStarred(row.id, true);
        _drop(like);
        return;
      }
      final status = ref.read(instantStatusProvider(like.trackId));
      if (status != null && status.isFailed) break;
      if (attempt >= delays.length) break;
      await Future<void>.delayed(delays[attempt]);
    }
    Log.info('likes', 'a like on "${like.title}" could not be delivered');
    _drop(like,
        because: '"${like.title}" could not be added to your library, so it '
            'was not liked.');
  }
}

final pendingLikesProvider =
    NotifierProvider<PendingLikes, PendingLikesState>(PendingLikes.new);
