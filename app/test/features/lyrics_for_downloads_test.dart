import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:drift/native.dart';
import 'package:encore/app/providers.dart';
import 'package:encore/data/api/lrclib_client.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/repos/lyrics_repository.dart';
import 'package:encore/features/downloads/lyrics_for_downloads.dart';
import 'package:encore/features/providers.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../support/fake_http.dart';
import '../support/test_app.dart';

/// "Download the songs and the lyrics": a song that reaches the phone brings
/// its lyrics with it, so the lyrics screen works offline.
void main() {
  late AppDatabase db;
  late int serverId;
  late FakeHttpAdapter lrclib;
  late ProviderContainer container;
  var network = NetworkKind.wifi;

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    network = NetworkKind.wifi;
    db = AppDatabase(NativeDatabase.memory());
    serverId = await Seed.library(db);
    lrclib = FakeHttpAdapter(routes: {
      'get': (_) => const FakeResponse.json({
            'plainLyrics': 'la la la',
            'syncedLyrics': null,
          }),
      // A plain exact record is no longer the end of the search (B-103): LRCLIB is asked for a synced one too.
      'search': (_) => const FakeResponse.json(<Object>[]),
    });
  });

  tearDown(() async {
    container.dispose();
    await db.close();
  });

  Future<void> download(String trackId) =>
      db.into(db.downloads).insertOnConflictUpdate(DownloadsCompanion.insert(
            serverId: serverId,
            trackId: trackId,
            updatedAtMs: 0,
            state: const Value(2),
          ));

  ProviderContainer build() {
    container = ProviderContainer(overrides: [
      databaseProvider.overrideWithValue(db),
      networkKindProvider.overrideWith((ref) => Stream.value(network)),
      lyricsRepositoryProvider.overrideWith(
        (ref) => LyricsRepository(
          db: db,
          serverId: serverId,
          lrclib: LrcLibClient(dio: fakeDio(lrclib)),
        ),
      ),
    ]);
    container.listen(lyricsForDownloadsProvider, (_, __) {});
    return container;
  }

  Future<void> until(bool Function() done) async {
    for (var i = 0; i < 300 && !done(); i++) {
      await Future<void>.delayed(const Duration(milliseconds: 20));
    }
  }

  Future<int> cachedCount() async => (await db.select(db.lyrics).get()).length;

  test('lyrics of a downloaded song are fetched and cached', () async {
    await download('al1-t1');
    build();

    await until(() => lrclib.requests.isNotEmpty);
    await Future<void>.delayed(const Duration(milliseconds: 100));

    expect(lrclib.count('get'), 1);
    expect(await cachedCount(), 1);
    final row = (await db.select(db.lyrics).get()).single;
    expect(row.trackId, 'al1-t1');
    expect(row.body, contains('la la la'));
  });

  test('a song whose lyrics are already cached is not asked about again',
      () async {
    await db.into(db.lyrics).insert(LyricsCompanion.insert(
          serverId: serverId,
          trackId: 'al1-t1',
          kind: 'plain',
          body: '["cached"]',
          fetchedAtMs: DateTime.now().millisecondsSinceEpoch,
        ));
    await download('al1-t1');
    build();

    await Future<void>.delayed(const Duration(milliseconds: 500));

    expect(lrclib.requests, isEmpty);
  });

  test('songs downloaded later are picked up too', () async {
    build();
    await download('al2-t1');
    await until(() => lrclib.requests.isNotEmpty);
    await download('al2-t2');
    await until(() => lrclib.count('get') >= 2);

    expect(lrclib.count('get'), 2);
  });

  test('nothing is fetched while offline', () async {
    network = NetworkKind.none;
    await download('al1-t1');
    build();

    await Future<void>.delayed(const Duration(milliseconds: 400));

    expect(lrclib.requests, isEmpty);
  });

  test('on mobile data it waits when downloads are Wi-Fi only', () async {
    network = NetworkKind.mobile; // wifiOnlyDownloads defaults to true
    await download('al1-t1');
    build();

    await Future<void>.delayed(const Duration(milliseconds: 400));

    expect(lrclib.requests, isEmpty);
  });
}
