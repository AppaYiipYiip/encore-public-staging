import 'package:dio/dio.dart';
import 'package:encore/data/encore/encore_api.dart';
import 'package:encore/data/encore/encore_models.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_encore_server.dart';

/// The bell on the wire (docs/tasks P2-15, ADR-R44): four kinds of news, written in words by the server.
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

  test('the news comes newest first, with how many are unread and a cursor',
      () async {
    server.addNews('invite_used', 'Sara joined Our music',
        body: 'With the invitation you made.', ago: 86400000);
    server.addNews('import_done', 'Your import is ready',
        body: 'Road trip 2025: 47 of 48 songs', route: '/settings/import');

    final list = (await api.notifications()).getOrThrow();

    expect(list.items.map((n) => n.title),
        ['Your import is ready', 'Sara joined Our music']);
    expect(list.items.first.kind, EncoreNewsKind.importDone);
    expect(list.items.first.route, '/settings/import');
    expect(list.items.last.body, 'With the invitation you made.');
    expect(list.items.every((n) => !n.read), isTrue);
    expect(list.unread, 2);
    expect(list.cursor, '2');
  });

  test(
      'with the cursor only what is newer comes, and the count stays the whole',
      () async {
    server.addNews('invite_used', 'Sara joined Our music');
    final first = (await api.notifications()).getOrThrow();
    server.addNews('jam', 'Nina invited you to a Jam');

    final newer = (await api.notifications(since: first.cursor)).getOrThrow();

    expect(newer.items.map((n) => n.title), ['Nina invited you to a Jam']);
    expect(newer.unread, 2);
    final nothing = (await api.notifications(since: newer.cursor)).getOrThrow();
    expect(nothing.items, isEmpty);
    expect(nothing.cursor, newer.cursor);
  });

  test(
      'reading marks the news up to an id, or all of it, and says what is left',
      () async {
    final one = server.addNews('invite_used', 'One');
    server.addNews('invite_used', 'Two');

    expect((await api.markNewsRead(upTo: one)).getOrThrow(), 1);
    expect((await api.markNewsRead()).getOrThrow(), 0);

    expect(server.newsRead, [one, null]);
    final list = (await api.notifications()).getOrThrow();
    expect(list.items.every((n) => n.read), isTrue);
  });

  test('news of a kind this app does not know is left out, not shown wrongly',
      () async {
    server.addNews('invite_used', 'Known');
    server.addNews('something_new', 'From a newer server');

    final list = (await api.notifications()).getOrThrow();

    expect(list.items.map((n) => n.title), ['Known']);
  });

  test(
      'a server that does not answer is a failure to say in words, not a crash',
      () async {
    server.online = false;

    final result = await api.notifications();

    expect(result.isErr, isTrue);
  });
}
