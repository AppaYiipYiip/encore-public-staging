import 'package:dio/dio.dart';
import 'package:encore/core/result.dart';
import 'package:encore/data/encore/encore_api.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_encore_server.dart';

void main() {
  late FakeEncoreServer server;
  late EncoreApi api;

  setUp(() {
    server = FakeEncoreServer();
    api = EncoreApi(
      dio: Dio()..httpClientAdapter = server.adapter,
      baseUrl: () => Uri.parse('http://home.test:4540'),
      auth: () => {'u': 'tester', 't': 'tok', 's': 'salt'},
    );
  });

  test(
      'saving a release names its songs in one call and says how the server goes about each',
      () async {
    final first = server.addRef('Weird Fishes', 'Radiohead');
    final second = server.addRef('Nude', 'Radiohead');
    server.keepStates[second] = 'kept';

    final saved = (await api.saveRelease('cat:in-rainbows', [first, second]))
        .getOrThrow();

    expect(saved.changed, isTrue);
    expect(server.savedReleases['cat:in-rainbows'], [first, second]);
    expect(saved.keep[first]!.state, 'queued');
    expect(saved.keep[first]!.isKept, isFalse);
    expect(saved.keep[second]!.isKept, isTrue);
  });

  test('saving it again changes nothing', () async {
    final only = server.addRef('Nude', 'Radiohead');
    await api.saveRelease('cat:x', [only]);

    final again = (await api.saveRelease('cat:x', [only])).getOrThrow();

    expect(again.changed, isFalse);
  });

  test(
      'a song the server does not know refuses the whole call, and nothing is saved',
      () async {
    final known = server.addRef('Nude', 'Radiohead');

    final refused = await api.saveRelease('cat:y', [known, 'sr_nothere']);

    expect(refused.failureOrNull, isA<NotFoundFailure>());
    expect(server.savedReleases, isEmpty);
  });

  test('a server that is not there is a network failure, not a saved release',
      () async {
    final only = server.addRef('Nude', 'Radiohead');
    server.online = false;

    final result = await api.saveRelease('cat:z', [only]);

    expect(result.failureOrNull, isA<NetworkFailure>());
    expect(server.savedReleases, isEmpty);
  });
}
