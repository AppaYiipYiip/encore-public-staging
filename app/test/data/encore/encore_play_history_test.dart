import 'dart:convert';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:encore/core/result.dart';
import 'package:encore/data/encore/encore_api.dart';
import 'package:encore/data/encore/encore_models.dart';
import 'package:encore/data/encore/encore_play_history.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_encore_server.dart';

EncoreApi apiFor(FakeEncoreServer server) => EncoreApi(
      dio: Dio()..httpClientAdapter = server.adapter,
      baseUrl: () => Uri.parse('http://home.test:4540'),
      auth: () => {'u': 'tester', 't': 'tok', 's': 'salt'},
    );

/// P3-34 slice 0: the person's history is the Encore server's own record (`GET me/plays`), not the music server's list read through its own sign-in.
void main() {
  late FakeEncoreServer server;

  setUp(() => server = FakeEncoreServer());

  test(
      'the REAL first page the server\'s own test saved is read as it is: three plays, the song and the time of each, and the cursor for the next page',
      () {
    final saved = jsonDecode(
            File('test/fixtures/server/me-plays-page.json').readAsStringSync())
        as Map<String, dynamic>;

    final page = EncorePlaysPage.fromJson(saved);

    expect([for (final p in page.items) p.id], ['play-0', 'play-2', 'play-1']);
    expect(page.items.first.refId, startsWith('sr_'));
    expect(page.items.first.atMs, 1700000300000);
    expect(page.items.first.msPlayed, 180000);
    expect(page.nextCursor, '1700000200000:play-1');
  });

  void play(String id, String ref, int at) => server.plays.add({
        'id': id,
        'ref': ref,
        'at': at,
        'msPlayed': 200000,
        'context': null,
      });

  test(
    'every play comes back as a listen of the Encore song id, newest first',
    () async {
      play('p-1', 'sr_a', 1700000000000);
      play('p-2', 'sr_b', 1700000500000);

      final result = await EncorePlayHistory(apiFor(server)).fetchAll();

      final listens = result.valueOrNull!;
      expect([for (final l in listens) l.trackId], ['sr_b', 'sr_a']);
      expect(
        listens.first.at,
        DateTime.fromMillisecondsSinceEpoch(1700000500000),
      );
    },
  );

  test(
      'pages are followed by the server\'s own cursor until it says there is no more: plays of one millisecond are neither skipped nor repeated',
      () async {
    for (var n = 0; n < 7; n++) {
      play('same-$n', 'sr_$n', 1700000000000);
    }
    play('earlier', 'sr_e', 1699999999999);
    play('later', 'sr_l', 1700000000001);

    final seen = <int>[];
    final result = await EncorePlayHistory(
      apiFor(server),
      pageSize: 3,
    ).fetchAll(progress: seen.add);

    final refs = [for (final l in result.valueOrNull!) l.trackId];
    expect(refs.length, 9);
    expect(refs.toSet().length, 9, reason: 'none twice');
    expect(refs.first, 'sr_l');
    expect(refs.last, 'sr_e');
    expect(server.myPlaysCursors.length, 3, reason: '9 plays, 3 to a page');
    expect(server.myPlaysCursors.first, isNull);
    expect(seen, [3, 6, 9]);
  });

  test('a person with no plays has an empty list, not a failure', () async {
    final result = await EncorePlayHistory(apiFor(server)).fetchAll();
    expect(result.valueOrNull, isEmpty);
  });

  test(
      'a server that fails is a failure the caller can read, never a thrown error',
      () async {
    server.hasMyPlays = false; // the route answers 404 as an older server does
    final result = await EncorePlayHistory(apiFor(server)).fetchAll();
    expect(result.failureOrNull, isA<AppFailure>());
  });

  test(
    'a cursor that never moves does not keep the phone asking for ever',
    () async {
      play('p-1', 'sr_a', 1700000000000);
      play('p-2', 'sr_b', 1700000000001);
      server.stuckCursor = '1700000000000:p-1';

      final result = await EncorePlayHistory(
        apiFor(server),
        pageSize: 1,
      ).fetchAll();

      expect(result.valueOrNull, isNotNull);
      expect(server.myPlaysCursors.length, lessThanOrEqualTo(3));
    },
  );

  test(
      'the info of a server that has the route says so, one that has not does not',
      () async {
    final api = apiFor(server);
    expect((await api.info()).valueOrNull!.hasMyPlays, isTrue);
    server.hasMyPlays = false;
    expect((await api.info()).valueOrNull!.hasMyPlays, isFalse);
  });
}
