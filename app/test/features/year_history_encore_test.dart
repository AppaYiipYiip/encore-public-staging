import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:drift/drift.dart' show Value;
import 'package:drift/native.dart';
import 'package:encore/app/providers.dart';
import 'package:encore/app/session.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/features/year/year_providers.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fake_encore_server.dart';
import '../support/test_app.dart';

/// One address, two servers behind it: the Encore server's `/encore/...`, and the music server's own `/auth` and `/api`, which only COUNT what asks for them.
class _Door implements HttpClientAdapter {
  _Door(this.encore);

  final FakeEncoreServer encore;

  /// Every request to the music server's own native API, as `METHOD /path`.
  final List<String> nativeCalls = [];

  /// What the music server's own history holds (the old way of reading it).
  int nativePlays = 0;

  @override
  Future<ResponseBody> fetch(RequestOptions options,
      Stream<Uint8List>? requestStream, Future<void>? cancelFuture) {
    final path = options.uri.path;
    if (path.startsWith('/encore/')) {
      return encore.adapter.fetch(options, requestStream, cancelFuture);
    }
    nativeCalls.add('${options.method} $path');
    Object body = const {'error': 'not found'};
    var status = 404;
    if (path == '/auth/login') {
      status = 200;
      body = {'token': 't'};
    } else if (path == '/api/scrobble') {
      status = 200;
      body = [
        for (var i = 0; i < nativePlays; i++)
          {'id': i, 'mediaFileId': 'al1-t1', 'submissionTime': 1792234918 + i},
      ];
    }
    return Future.value(
        ResponseBody.fromString(jsonEncode(body), status, headers: {
      Headers.contentTypeHeader: ['application/json'],
      if (path == '/api/scrobble') 'x-total-count': ['$nativePlays'],
    }));
  }

  @override
  void close({bool force = false}) {}
}

/// P3-34 slice 0: Year in Music in Encore mode reads the Encore server's own record of plays (`GET me/plays`), and the music server's own sign-in and `/api` only
/// where there is no such route (a plain Navidrome, or an Encore server from before it).
void main() {
  late AppDatabase db;
  late FakeEncoreServer encore;
  late _Door door;
  late ServerSession session;

  Future<void> start({bool encoreMode = true}) async {
    db = AppDatabase(NativeDatabase.memory());
    await Seed.library(db);
    if (encoreMode) {
      await (db.update(db.servers)).write(ServersCompanion(
          capabilitiesJson: Value(jsonEncode({'encore': true}))));
    }
    encore = FakeEncoreServer();
    door = _Door(encore);
    final server = (await db.select(db.servers).get()).first;
    session = await ServerSession.create(
      verifyAddresses: false,
      db: db,
      server: server,
      password: 'x',
      dio: Dio()..httpClientAdapter = door,
    );
  }

  tearDown(() async {
    await session.dispose();
    await db.close();
  });

  ProviderContainer container() {
    final c = ProviderContainer(overrides: [
      sessionProvider.overrideWith((ref) async => session),
      playHistoryKeepProvider.overrideWithValue(Duration.zero),
    ]);
    addTearDown(c.dispose);
    return c;
  }

  void play(String id, String ref, int at) => encore.plays.add(
      {'id': id, 'ref': ref, 'at': at, 'msPlayed': 200000, 'context': null});

  test(
      'in Encore mode the history is the Encore server\'s own record, and the music server\'s own sign-in and API are never asked',
      () async {
    await start();
    play('p-1', 'al1-t1', 1700000000000);
    play('p-2', 'al1-t2', 1700000500000);
    door.nativePlays = 5; // what the music server holds: not what is read

    final listens = await container().read(playHistoryProvider.future);

    expect([for (final l in listens) l.trackId], ['al1-t2', 'al1-t1']);
    expect(door.nativeCalls, isEmpty,
        reason: 'no /auth/login and no /api/scrobble through the gateway');
    expect(encore.myPlaysCursors, [null]);
  });

  test(
      'an Encore server from before the route is read the old way, as it always was',
      () async {
    await start();
    encore.hasMyPlays = false;
    door.nativePlays = 3;

    final listens = await container().read(playHistoryProvider.future);

    expect(listens, hasLength(3));
    expect(door.nativeCalls, ['POST /auth/login', 'GET /api/scrobble']);
    expect(encore.myPlaysCursors, isEmpty,
        reason: 'a route that is not listed is never tried to find out');
  });

  test(
      'a server that lists the route and fails it leaves the person with what this phone saw itself, not an error',
      () async {
    await start();
    encore.failMyPlays = true;
    // This phone's own record: one play of a song it knows.
    await db.into(db.playHistory).insert(PlayHistoryCompanion.insert(
          serverId: (await db.select(db.servers).get()).first.id,
          trackId: 'al1-t1',
          playedAtMs: 1700000000000,
        ));

    final listens = await container().read(playHistoryProvider.future);

    expect([for (final l in listens) l.trackId], ['al1-t1']);
    expect(door.nativeCalls, isEmpty);
  });

  test(
      'a plain Navidrome server (no Encore) keeps reading the music server\'s own list',
      () async {
    await start(encoreMode: false);
    door.nativePlays = 2;

    final listens = await container().read(playHistoryProvider.future);

    expect(listens, hasLength(2));
    expect(door.nativeCalls, ['POST /auth/login', 'GET /api/scrobble']);
    expect(encore.myPlaysCursors, isEmpty);
  });
}
