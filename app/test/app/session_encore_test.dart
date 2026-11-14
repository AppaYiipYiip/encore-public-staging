import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:drift/native.dart';
import 'package:encore/app/session.dart';
import 'package:encore/core/logger.dart';
import 'package:encore/data/auth/credential_store.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/encore/encore_device.dart';
import 'package:encore/data/encore/encore_mutations.dart';
import 'package:encore/data/sync/playlist_mutations.dart';
import 'package:encore/data/sync/sync_engine.dart';
import 'package:encore/data/sync/sync_state_store.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fake_encore_server.dart';
import '../support/fake_http.dart' show subsonicError;
import '../support/fake_subsonic_server.dart';

/// How the MUSIC server (Navidrome, behind the same address) fails while the Encore server answers (AUDIT B-77).
enum _MusicFault {
  /// A gateway answers 503 for it (Navidrome restarting during `encore update`): the Subsonic client says `ServerFailure`.
  unavailable,

  /// Its own login is refused (a stale music-server password): `AuthFailure`.
  loginRefused,

  /// Nothing answers for it at all: `NetworkFailure`.
  unreachable,
}

/// One address, two servers behind it: the music server's `/rest/...` and the Encore server's `/encore/...`.
class _OneDoor implements HttpClientAdapter {
  _OneDoor(this.music, this.encore);

  final FakeSubsonicServer music;
  final FakeEncoreServer encore;
  bool encoreInstalled = true;

  /// While set, the music server's own calls (`/rest/...`) fail this way; the Encore server is untouched.
  _MusicFault? musicFault;

  @override
  Future<ResponseBody> fetch(RequestOptions options,
      Stream<Uint8List>? requestStream, Future<void>? cancelFuture) {
    final fault = musicFault;
    if (fault != null && !options.uri.path.startsWith('/encore/')) {
      switch (fault) {
        case _MusicFault.unavailable:
          return Future.value(
              ResponseBody.fromString('Service Unavailable', 503, headers: {
            Headers.contentTypeHeader: ['text/plain'],
          }));
        case _MusicFault.loginRefused:
          return Future.value(ResponseBody.fromString(
              jsonEncode(subsonicError(40, 'Wrong username or password')), 200,
              headers: {
                Headers.contentTypeHeader: ['application/json'],
              }));
        case _MusicFault.unreachable:
          return Future.error(DioException.connectionError(
              requestOptions: options, reason: 'connection refused'));
      }
    }
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

  Future<void> start({
    Map<String, Object?> capabilities = const {},
    CredentialStore? credentialStore,
  }) async {
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
        verifyAddresses: false,
        db: db,
        server: server,
        password: 'x',
        credentialStore: credentialStore,
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

    expect(session.encoreApi, same(session.encore),
        reason:
            'the one way outside code asks "is this an Encore server" and talks to it');
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

  test(
      'P2-20: in Encore mode a picture is asked for with the cover ticket, never with the music server\'s login',
      () async {
    await start(capabilities: {'encore': true});

    expect(session.coverArtUrl('al-1', size: 300), isNull,
        reason: 'no ticket yet: a placeholder, not a login in an address');

    await session.covers.ensure();
    final url = session.coverArtUrl('al-1', size: 300)!;

    expect(url.host, 'home.test');
    expect(url.path, '/encore/cover/al-1');
    expect(url.queryParameters['sig'], 'coversig');
    expect(url.queryParameters['e'], '9999999999',
        reason: "the server's own end, not one counted by the phone");
    for (final login in ['u', 't', 's', 'p_']) {
      expect(url.queryParameters.containsKey(login), isFalse, reason: login);
    }
    expect(music.adapter.requests, isEmpty,
        reason: 'the music server was not asked anything');
  });

  test(
      'P2-20: a catalogue picture stays its own address, and a plain music server keeps its own cover address and login',
      () async {
    await start(capabilities: {'encore': true});
    expect(
        session.coverArtUrl('https://cdn.example/a.jpg')!.host, 'cdn.example');
    await session.dispose();
    await db.close();

    await start();
    final url = session.coverArtUrl('al-1', size: 300)!;

    expect(url.path, endsWith('/rest/getCoverArt'));
    expect(url.queryParameters['u'], 'tester');
  });

  test(
      'P2-20: in Encore mode a song is played from the server\'s signed address, kept or not, and the music server is never asked for it',
      () async {
    await start(capabilities: {'encore': true});
    final kept = encore.addRef('Kept', 'Artist', fileId: 'nd-1');
    final streamed = encore.addRef('Streamed', 'Artist');

    final a = await session.streams.forRef(kept);
    final b = await session.streams.forRef(streamed);
    final again = await session.streams.forRef(kept);

    expect(a.path, '/encore/stream/$kept');
    expect(b.path, '/encore/stream/$streamed');
    expect(again, a);
    expect(
        encore.adapter.requests
            .where((r) => r.uri.path.endsWith('/stream-url')),
        hasLength(2),
        reason: 'the kept song was asked for once');
    expect(music.adapter.requests, isEmpty);
  });

  test(
      'DV-2: ending the device of a session tells the server which phone it was and forgets the saved sign-in',
      () async {
    final store = InMemoryCredentialStore();
    await store.writeSecret(
        'encore.device.1', EncoreDevice.encode('ed_saved', 'dv_9'));
    await start(capabilities: {'encore': true}, credentialStore: store);

    await session.endDevice();

    expect(encore.logouts, ['dv_9']);
    expect(await store.readSecret('encore.device.1'), isNull);
  });

  test('a plain music server is synced the old way and never upgraded',
      () async {
    await start();
    door.encoreInstalled = false;

    await session.start();
    await until(() => music.adapter.count('search3') > 0);

    expect(session.encoreApi, isNull);
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

  group(
      'AUDIT B-77: the Encore server answering is not the music server answering',
      () {
    for (final fault in _MusicFault.values) {
      test(
          'a pass still pulls the Encore feeds and completes while the music server fails ($fault)',
          () async {
        await start(capabilities: {'encore': true});
        encore.addRef('Kept', 'Artist',
            album: 'Album', fileId: 'nd-1', meta: {'albumId': 'al0'});
        final liked = encore.addRef('Streamed', 'Artist');
        encore.otherDeviceLikes(liked);
        door.musicFault = fault;
        Log.clear();

        final outcome = await session.sync.run();

        expect(
            Log.recent.where((r) =>
                r.level == LogLevel.warn &&
                r.message.contains('browse index could not be refreshed')),
            isNotEmpty,
            reason:
                'the recorded stop-gap of B-77 (AUDIT B-130): a music-server login that stays broken is visible in the log at WARNING level, every pass');
        expect(outcome, isA<SyncCompleted>(),
            reason:
                'Settings must not say "did not finish" because Navidrome is restarting: the Encore server answered');
        final titles = (await (db.select(db.tracks)
                  ..where((t) => t.deletedAtMs.isNull()))
                .get())
            .map((t) => t.title)
            .toSet();
        expect(titles, {'Kept', 'Streamed'},
            reason: 'the Encore feeds do not depend on the music server');
        expect((outcome as SyncCompleted).stats.browseFailure, isNotNull,
            reason: 'the browse failure is reported, separately');
        expect(
            await SyncStateStore(db, server.id).get(SyncStateStore.lastError),
            isNull);
      });
    }

    test(
        'the browse index is tried again on the next pass, once the music server is back',
        () async {
      await start(capabilities: {'encore': true});
      encore.addRef('Kept', 'Artist',
          album: 'Album', fileId: 'nd-1', meta: {'albumId': 'al0'});
      door.musicFault = _MusicFault.unavailable;
      final first = await session.sync.run() as SyncCompleted;
      expect(first.stats.libraryPhaseRan, isFalse);

      door.musicFault = null;
      final second = await session.sync.run() as SyncCompleted;

      expect(second.stats.libraryPhaseRan, isTrue,
          reason: 'the index never finished, so it is still due');
      expect(second.stats.browseFailure, isNull);
    });

    for (final fault in _MusicFault.values) {
      test(
          'the cheap check for changes from other devices still pulls them ($fault)',
          () async {
        await start(capabilities: {'encore': true});
        encore.addRef('Kept', 'Artist',
            album: 'Album', fileId: 'nd-1', meta: {'albumId': 'al0'});
        expect(await session.sync.run(), isA<SyncCompleted>());
        door.musicFault = fault;
        final liked = encore.addRef('Added elsewhere', 'Artist');
        encore.otherDeviceLikes(liked);

        final outcome = await session.sync.probe();

        expect(outcome, isA<ProbeUpdated>(),
            reason: 'an edit from another device appears');
      });
    }

    test(
        'a music server that is down never makes the probe ask for a full pass over and over',
        () async {
      await start(capabilities: {'encore': true});
      door.musicFault = _MusicFault.unavailable;

      final outcome = await session.sync.probe();

      expect(outcome, isNot(isA<ProbeNeedsFullPass>()),
          reason: 'a full pass cannot work now; the probe runs every 3 s');
      expect(outcome, isNot(isA<ProbeFailed>()));
    });
  });
}
