@Tags(['live'])
library;

import 'dart:io';

import 'package:dio/dio.dart';
import 'package:drift/native.dart';
import 'package:encore/data/api/opensubsonic/opensubsonic_client.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/db/search_dao.dart';
import 'package:encore/data/sync/sync_engine.dart';
import 'package:flutter_test/flutter_test.dart';

/// Read-only verification against a real Navidrome server (docs/08).
///
/// Enabled only when ENCORE_LIVE=1 and credentials are provided through the
/// environment - never stored in the repo:
///   ENCORE_SERVER_URL, ENCORE_USER, ENCORE_PASSWORD
///
/// Nothing here mutates server state (no star, no playlist edit, no scrobble).
void main() {
  final env = Platform.environment;
  final enabled = env['ENCORE_LIVE'] == '1';
  final url = env['ENCORE_SERVER_URL'];
  final user = env['ENCORE_USER'];
  final password = env['ENCORE_PASSWORD'];

  if (!enabled || url == null || user == null || password == null) {
    test('live tests are opt-in (set ENCORE_LIVE=1 + credentials)', () {},
        skip: 'ENCORE_LIVE not set');
    return;
  }

  late AppDatabase db;
  late OpenSubsonicClient client;
  late int serverId;

  setUp(() async {
    db = AppDatabase(NativeDatabase.memory());
    serverId = await db.into(db.servers).insert(ServersCompanion.insert(
          name: 'Live',
          username: user,
          endpointsJson: '[]',
          createdAtMs: 0,
        ));
    client = OpenSubsonicClient(
      dio: Dio(BaseOptions(
        connectTimeout: const Duration(seconds: 8),
        receiveTimeout: const Duration(seconds: 60),
      )),
      baseUrl: () => Uri.parse(url),
      credentials: SubsonicCredentials(username: user, password: password),
    );
  });

  tearDown(() => db.close());

  test('ping + extensions', () async {
    final ping = (await client.ping()).getOrThrow();
    // ignore: avoid_print
    print('server: ${ping.type} ${ping.serverVersion} '
        'openSubsonic=${ping.openSubsonic}');
    final ext = (await client.loadExtensions()).getOrThrow();
    // ignore: avoid_print
    print('extensions: ${ext.toList()..sort()}');
    expect(ping.apiVersion, isNotEmpty);
  });

  test('full sync into an empty DB, then a no-change sync', () async {
    final engine = SyncEngine(db: db, client: client, serverId: serverId);
    await client.loadExtensions();

    final sw = Stopwatch()..start();
    final first = await engine.run(reason: SyncReason.manual);
    sw.stop();
    expect(first, isA<SyncCompleted>(), reason: '$first');
    final s1 = (first as SyncCompleted).stats;
    // ignore: avoid_print
    print('FIRST SYNC ${sw.elapsedMilliseconds} ms: artists=${s1.artists} '
        'albums=${s1.albums} tracks=${s1.tracks} playlists=${s1.playlistsFetched}');

    final trackCount =
        (await db.select(db.tracks).get()).where((t) => t.deletedAtMs == null);
    expect(trackCount, isNotEmpty);

    sw
      ..reset()
      ..start();
    final second = await engine.run(reason: SyncReason.resume);
    sw.stop();
    final s2 = (second as SyncCompleted).stats;
    // ignore: avoid_print
    print('NO-CHANGE SYNC ${sw.elapsedMilliseconds} ms '
        'libraryPhaseRan=${s2.libraryPhaseRan}');
    expect(s2.libraryPhaseRan, isFalse);

    // Offline FTS over the real library.
    final hits = await SearchDao(db).tracks(serverId, 'alcest').get();
    // ignore: avoid_print
    print('FTS "alcest": ${hits.length} tracks');
  }, timeout: const Timeout(Duration(minutes: 5)));
}
