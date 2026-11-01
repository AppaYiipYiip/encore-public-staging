import 'dart:async';
import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:drift/native.dart';
import 'package:encore/app/connection.dart';
import 'package:encore/app/providers.dart';
import 'package:encore/app/session.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/features/settings/encore_play_section.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_encore_server.dart';
import '../../support/fake_subsonic_server.dart';

/// One address that can be switched off, with the Encore server behind it.
class _Door implements HttpClientAdapter {
  _Door(this.music, this.encore);

  final FakeSubsonicServer music;
  final FakeEncoreServer encore;
  bool down = false;

  @override
  Future<ResponseBody> fetch(RequestOptions options,
      Stream<Uint8List>? requestStream, Future<void>? cancelFuture) {
    if (down) {
      throw DioException.connectionError(
          requestOptions: options, reason: 'no route');
    }
    return options.uri.path.startsWith('/encore/')
        ? encore.adapter.fetch(options, requestStream, cancelFuture)
        : music.adapter.fetch(options, requestStream, cancelFuture);
  }

  @override
  void close({bool force = false}) {}
}

/// "Play any song" on Settings > Your server told a person whose phone had lost the server that it "did not answer", and kept saying so
/// after the server was back, until the page was left and opened again (QA round 1, R1-2, build 123).
void main() {
  late AppDatabase db;
  late ServerSession session;
  late _Door door;

  setUp(() async {
    db = AppDatabase(NativeDatabase.memory());
    final id = await db.into(db.servers).insert(ServersCompanion.insert(
          name: 'Home',
          username: 'tester',
          endpointsJson: '[{"label":"Home","url":"http://home.test:4540"}]',
          capabilitiesJson: Value(jsonEncode({'encore': true})),
          createdAtMs: 0,
        ));
    final server = await (db.select(db.servers)..where((s) => s.id.equals(id)))
        .getSingle();
    door = _Door(FakeSubsonicServer()..seed(songCount: 3, albumCount: 1),
        FakeEncoreServer());
    session = await ServerSession.create(
        verifyAddresses: false,
        db: db,
        server: server,
        password: 'x',
        dio: Dio()..httpClientAdapter = door);
  });

  tearDown(() async {
    await session.dispose();
    await db.close();
  });

  test('the status is asked again when the server comes back', () async {
    final reachable = StreamController<bool>();
    addTearDown(reachable.close);
    final c = ProviderContainer(overrides: [
      sessionProvider.overrideWith((ref) async => session),
      serverReachableProvider.overrideWith((ref) => reachable.stream),
    ]);
    addTearDown(c.dispose);
    final watching = c.listen(encoreServerInfoProvider, (_, __) {});
    addTearDown(watching.close);
    door.down = true;
    reachable.add(false);
    await pumpEventQueue();
    expect(await c.read(encoreServerInfoProvider.future), isNull,
        reason: 'while the server is away it does not answer');

    door.down = false;
    reachable.add(true);
    await pumpEventQueue();

    expect((await c.read(encoreServerInfoProvider.future))?.youtubeState, 'ok',
        reason:
            'back online the page says what the server says, not "did not answer"');
  });
}
