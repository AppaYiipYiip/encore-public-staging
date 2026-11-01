import '../../core/result.dart';
import '../db/app_database.dart';
import '../sync/outbox.dart';
import 'encore_api.dart';
import 'encore_mutations.dart';

/// Sends one queued edit to an Encore server. Every kind is safe to send twice (the ids are the phone's own, a like is a set, a play has an
/// id), so a delivery that was cut off half way is simply sent again.
///
/// Ratings and "now playing" pings have no Encore equivalent yet: they are dropped as delivered rather than kept for ever.
Future<Result<void>> deliverToEncore(
  EncoreApi api,
  OutboxRow row,
  Map<String, dynamic> p, {
  String? deviceId,
}) async {
  List<String> strings(String key) =>
      [for (final v in (p[key] as List? ?? const [])) v.toString()];
  List<({String ref, String entryId})> entries() => [
        for (final e in (p['entries'] as List? ?? const []))
          (ref: (e as Map)['ref'] as String, entryId: e['id'] as String),
      ];

  /// What a playlist the server no longer has means for an edit of it: there is nothing left to do (only its owner can delete it, so the same
  /// person did, on another device: deleted wins, and the next pull removes it here too).
  ///
  /// **Except a song the server does not know** (B3): the same code answers that, but there the playlist is still there and the song that was
  /// added to it would vanish without a word. The server names the song in the error's details; such a failure is kept, parked as a failed
  /// edit the person can see.
  Result<void> gone(Result<void> result) {
    final failure = result.failureOrNull;
    return failure is NotFoundFailure && failure.unknownRef == null
        ? const Result.ok(null)
        : result;
  }

  Future<Result<void>> inOrder(
      Iterable<Future<Result<void>> Function()> steps) async {
    for (final step in steps) {
      final result = await step();
      if (result.isErr) return result;
    }
    return const Result.ok(null);
  }

  switch (row.kind) {
    case OutboxKind.star:
      return inOrder([
        for (final id in strings('songIds'))
          () => api.like(id, atMs: row.createdAtMs),
        for (final id in strings('albumIds')) () => api.saveAlbum(id),
        for (final id in strings('artistIds')) () => api.follow(id),
      ]);
    case OutboxKind.unstar:
      return inOrder([
        for (final id in strings('songIds')) () => api.unlike(id),
        for (final id in strings('albumIds')) () => api.unsaveAlbum(id),
        for (final id in strings('artistIds')) () => api.unfollow(id),
      ]);
    case OutboxKind.rating:
      return const Result.ok(null);
    case OutboxKind.scrobble:
      if (p['submission'] == false) return const Result.ok(null);
      final at = (p['timeMs'] as int?) ?? row.createdAtMs;
      return api.play(
        id: 'p${deviceId == null ? '' : '-${deviceId.substring(deviceId.length > 8 ? deviceId.length - 8 : 0)}'}-${row.id}-$at',
        refId: p['id'] as String,
        atMs: at,
        msPlayed: (p['listenedMs'] as int?) ?? 30000,
        context: p['source'] as String?,
      );
    case EncoreOutboxKind.playlistCreate:
      final all = entries();
      final made =
          await api.createPlaylist(p['id'] as String, p['name'] as String);
      if (made.isErr) return made;
      return inOrder([
        for (var i = 0; i < all.length; i += 500)
          () => api.addEntries(p['id'] as String,
              all.sublist(i, i + 500 > all.length ? all.length : i + 500)),
      ]);
    case EncoreOutboxKind.playlistAdd:
      final all = entries();
      return gone(await inOrder([
        for (var i = 0; i < all.length; i += 500)
          () => api.addEntries(p['playlistId'] as String,
              all.sublist(i, i + 500 > all.length ? all.length : i + 500)),
      ]));
    case EncoreOutboxKind.playlistRemove:
      return gone(await api.removeEntries(
          p['playlistId'] as String, strings('entryIds')));
    case EncoreOutboxKind.playlistRename:
      return gone(await api.renamePlaylist(
          p['playlistId'] as String, p['name'] as String));
    case EncoreOutboxKind.playlistDelete:
      return gone(await api.deletePlaylist(p['id'] as String));
    default:
      return Result.err(UnexpectedFailure(OutboxProcessor.unreadable));
  }
}
