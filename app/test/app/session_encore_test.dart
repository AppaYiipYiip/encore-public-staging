import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:drift/native.dart';
import 'package:encore/app/session.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/encore/encore_mutations.dart';
import 'package:encore/data/sync/playlist_mutations.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fake_encore_server.dart';
import '../support/fake_subsonic_server.dart';

/// One address, two servers behind it: the music server's `/rest/...` and the Encore server's `/encore/...`.
class _OneDoor implements HttpClientAdapter {
  _OneDoor(this.music, this.encore);

  final FakeSubsonicServer music;
  final FakeEncoreServer encore;
  bool encoreInstalled = true;

  @override
  Future<ResponseBody> fetch(RequestOptions options,
      Stream<Uint8List>? requestStream, Future<void>? cancelFuture) {
    if (options.uri.path.startsWith('/encore/')) {
      if (!encoreInstalled) {
        return Future.value(ResponseBody.fromString(
            jsonEncode({
              'error': {'code': 'not_found'}
            }),
            404,
            headers: {
              Headers.contentTypeHeader: ['application/json'],
            }));
      }
      return encore.adapter.fetch(options, requestStream, cancelFuture);
    }
    return music.adapter.fetch(options, requestStream, cancelFuture);
  }

  @override
  void close({bool force = false}) {}
}

void main() {
  late AppDatabase db;
  late FakeSubsonicServer music;
  late FakeEncoreServer encore;
  late _OneDoor door;
  late ServerRow server;
  late ServerSession session;

  Future<void> start({Map<String, Object?> capabilities = const {}}) async {
    db = AppDatabase(NativeDatabase.memory());
    final id = await db.into(db.servers).insert(ServersCompanion.insert(
          name: 'Home',
          username: 'tester',
          endpointsJson: '[{"label":"Home","url":"http://home.test:4540"}]',
          capabilitiesJson: Value(jsonEncode(capabilities)),
          createdAtMs: 0,
        ));
    server = await (db.select(db.servers)..where((s) => s.id.equals(id)))
        .getSingle();
    music = FakeSubsonicServer()..seed(songCount: 6, albumCount: 2);
    encore = FakeEncoreServer();
    door = _OneDoor(music, encore);
    session = await ServerSession.create(
        db: db,
        server: server,
        password: 'x',
        dio: Dio()..httpClientAdapter = door);
  }

  tearDown(() async {
    await session.dispose();
    await db.close();
  });

  Future<void> until(bool Function() done, {int tries = 400}) async {
    for (var i = 0; i < tries && !done(); i++) {
      await Future<void>.delayed(const Duration(milliseconds: 15));
    }
  }

  Future<Map<String, Object?>> capabilitiesNow() async => (jsonDecode(
          (await (db.select(db.servers)..where((s) => s.id.equals(server.id)))
                  .getSingle())
              .capabilitiesJson) as Map)
      .cast();

  test(
      'a server saved as an Encore server runs in Encore mode: its own playlist editing, its feeds for the library',
      () async {
    await start(capabilities: {'encore': true});
    encore.addRef('Kept', 'Artist',
        album: 'Album', fileId: 'nd-1', meta: {'albumId': 'al0'});
    final liked = encore.addRef('Streamed', 'Artist');
    encore.otherDeviceLikes(liked);

    expect(session.encoreMode, isTrue);
    expect(session.playlists, isA<EncorePlaylistEditor>());
    final outcome = await session.sync.run();

    expect(outcome.runtimeType.toString(), 'SyncCompleted');
    final titles = (await (db.select(db.tracks)
              ..where((t) => t.deletedAtMs.isNull()))
            .get())
        .map((t) => t.title)
        .toSet();
    expect(titles, {'Kept', 'Streamed'},
        reason:
            'the songs come from the Encore server\'s feeds, not from a dump of the music server');
    expect(music.adapter.count('search3'), 0);
    expect(music.adapter.count('getArtists'), 1,
        reason: 'the browse index still comes from the music server');
  });

  test('a plain music server is synced the old way and never upgraded',
      () async {
    await start();
    door.encoreInstalled = false;

    await session.start();
    await until(() => music.adapter.count('search3') > 0);

    expect(session.encoreMode, isFalse);
    expect(session.playlists, isA<PlaylistMutations>());
    expect(music.adapter.count('search3'), greaterThan(0));
    expect(encore.migrations, 0);
    expect((await capabilitiesNow())['encore'], isNull);
  });

  test(
      'a phone that knew the server as a plain one is moved over the first time it turns out to be an Encore server',
      () async {
    await start();
    // the phone has the music server's songs, one liked, and the person's playlist
    await session.sync.run();
    final before = await (db.select(db.tracks)..where((t) => t.id.equals('s1')))
        .getSingle();
    expect(before.isRef, isFalse);
    final a = encore.addRef('Song 1', 'Alcest',
        album: 'Album 1', fileId: 's1', meta: {'albumId': 'al1'});
    encore.addRef('Song 2', 'Alcest',
        album: 'Album 0', fileId: 's2', meta: {'albumId': 'al0'});

    await session.start();
    await until(() => encore.migrations > 0);
    await until(() => false, tries: 30); // let the move finish

    final track = await (db.select(db.tracks)..where((t) => t.id.equals(a)))
        .getSingleOrNull();
    expect(encore.migrations, 1);
    expect(track, isNotNull,
        reason: 'the song of the music server now has the ref\'s id');
    expect((track!.isRef, track.fileId), (true, 's1'));
    expect(
        await (db.select(db.tracks)..where((t) => t.id.equals('s1')))
            .getSingleOrNull(),
        isNull);
    expect((await capabilitiesNow())['encore'], true,
        reason:
            'remembered: the session is rebuilt in Encore mode from here on');
  });

  test(
      'a move that cannot finish is said so, and the phone goes on working the old way meanwhile',
      () async {
    await start();
    encore.failMigration = true;

    await session.start();
    await until(() => session.upgrade.value.failure != null);

    expect(session.upgrade.value.failure, isNotNull);
    await until(() => music.adapter.count('search3') > 0);
    expect(music.adapter.count('search3'), greaterThan(0),
        reason: 'the old way of syncing carries on');
    expect((await capabilitiesNow())['encore'], isNull);
  });
}
