import '../../core/result.dart';
import '../../domain/year_in_music.dart';
import 'encore_api.dart';

/// Every play of this person, read from the Encore server's own record (P3-34 slice 0, `GET me/plays`).
///
/// In Encore mode the phone reports each play it counts to the Encore server and nowhere else, so that record IS the history: the one Year in Music counts. It
/// replaces reading the music server's own list through its own sign-in (`PlayHistoryClient`), which is outside the thin-client rule (ADR-R38) and was never
/// open away from home. The song of a play is the Encore song id, which is also the id of the row the phone has for it in Encore mode.
class EncorePlayHistory {
  EncorePlayHistory(this._api, {this.pageSize = 500, this.maxPages = 2000});

  final EncoreApi _api;

  /// Plays asked for in one request (the server holds it to 500).
  final int pageSize;

  /// A stop for a server that never says it is done: 1,000,000 plays at the default size.
  final int maxPages;

  /// Every play, newest first. [progress] is told how many have arrived (the total is not known up front: the server pages by a cursor). Never throws.
  Future<Result<List<Listen>>> fetchAll({void Function(int done)? progress}) =>
      guard(() async {
        final listens = <Listen>[];
        String? cursor;
        for (var page = 0; page < maxPages; page++) {
          final answer = (await _api.myPlays(
            cursor: cursor,
            limit: pageSize,
          ))
              .getOrThrow();
          for (final play in answer.items) {
            listens.add(
              Listen(
                play.refId,
                DateTime.fromMillisecondsSinceEpoch(play.atMs),
              ),
            );
          }
          progress?.call(listens.length);
          final next = answer.nextCursor;
          // A cursor that does not move is a server that would answer the same page for ever.
          if (next == null || answer.items.isEmpty || next == cursor) break;
          cursor = next;
        }
        return listens;
      });
}
