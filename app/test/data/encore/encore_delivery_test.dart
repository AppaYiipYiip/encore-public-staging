import 'package:encore/core/result.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/encore/encore_delivery.dart';
import 'package:encore/data/encore/encore_mutations.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_encore_server.dart';
import 'encore_api_test.dart' show apiFor;

/// What a queued edit means when the server says "not found" (QA-BACKEND B3). The server uses one code for a playlist that is gone and for a
/// song it does not know. A playlist that is gone was deleted by its owner on another device: deleted wins, the edit is finished (rename,
/// remove, delete and add alike). A song the server does not know is different: the playlist is still there and the song that was added to it
/// would vanish without a word, so that answer (it names the song) is kept as a failure the person can see.
void main() {
  final playlist = 'pl_${'a' * 26}';
  late FakeEncoreServer server;

  OutboxRow row(String kind) => OutboxRow(
        id: 1,
        serverId: 1,
        kind: kind,
        payloadJson: '{}',
        createdAtMs: 0,
        attempts: 0,
        serverErrors: 0,
        nextAttemptAtMs: 0,
        status: 'pending',
      );

  setUp(() => server = FakeEncoreServer());

  Future<Result<void>> deliver(String kind, Map<String, dynamic> payload) =>
      deliverToEncore(apiFor(server), row(kind), payload);

  /// A playlist that was made on the server and then deleted (on another device).
  Future<void> deletedPlaylist() async {
    final api = apiFor(server);
    (await api.createPlaylist(playlist, 'Late night')).getOrThrow();
    (await api.deletePlaylist(playlist)).getOrThrow();
  }

  test(
      'a song added to a playlist that was deleted elsewhere is dropped: deleted wins, and the next pull removes the playlist here',
      () async {
    await deletedPlaylist();
    final song = server.addRef('Nude', 'Radiohead');

    final result = await deliver(EncoreOutboxKind.playlistAdd, {
      'playlistId': playlist,
      'entries': [
        {'ref': song, 'id': 'pe_${'b' * 26}'},
      ],
    });

    expect(result.isOk, isTrue);
  });

  test(
      'a song the server does not know, added to a playlist that is there, is a failure that names the song, not a silent "delivered" (B3)',
      () async {
    final api = apiFor(server);
    (await api.createPlaylist(playlist, 'Late night')).getOrThrow();
    final unknown = 'sr_${'z' * 26}';

    final result = await deliver(EncoreOutboxKind.playlistAdd, {
      'playlistId': playlist,
      'entries': [
        {'ref': unknown, 'id': 'pe_${'b' * 26}'},
      ],
    });

    expect(result.isErr, isTrue,
        reason: 'the song would vanish: keep it, parked, where it is seen');
    final failure = result.failureOrNull;
    expect(failure, isA<NotFoundFailure>());
    expect((failure! as NotFoundFailure).unknownRef, unknown);
  });

  test(
      'renaming, removing from and deleting a playlist that is gone are finished: there is nothing left to do',
      () async {
    await deletedPlaylist();

    expect(
        (await deliver(EncoreOutboxKind.playlistRename,
                {'playlistId': playlist, 'name': 'New'}))
            .isOk,
        isTrue);
    expect(
        (await deliver(EncoreOutboxKind.playlistRemove, {
          'playlistId': playlist,
          'entryIds': ['pe_${'b' * 26}']
        }))
            .isOk,
        isTrue);
    expect(
        (await deliver(EncoreOutboxKind.playlistDelete, {'id': playlist})).isOk,
        isTrue);
  });

  test('adding to a playlist that is there still works', () async {
    final api = apiFor(server);
    (await api.createPlaylist(playlist, 'Late night')).getOrThrow();
    final song = server.addRef('Nude', 'Radiohead');

    final result = await deliver(EncoreOutboxKind.playlistAdd, {
      'playlistId': playlist,
      'entries': [
        {'ref': song, 'id': 'pe_${'b' * 26}'},
      ],
    });

    expect(result.isOk, isTrue);
  });
}
