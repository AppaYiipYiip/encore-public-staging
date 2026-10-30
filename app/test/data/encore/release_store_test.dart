import 'package:drift/native.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/encore/encore_models.dart';
import 'package:encore/data/repos/release_store.dart';
import 'package:flutter_test/flutter_test.dart';

/// D-35 (B2): what the phone remembers about catalogue releases, in the per-server sync-state store, so a release looks the same after a restart.
/// A fresh `ReleaseStore` over the same database stands in for the restart.
void main() {
  late AppDatabase db;
  late int one;

  Future<int> server(String user) =>
      db.into(db.servers).insert(ServersCompanion.insert(
            name: 'Home',
            username: user,
            endpointsJson: '[]',
            createdAtMs: 0,
          ));

  setUp(() async {
    db = AppDatabase(NativeDatabase.memory());
    one = await server('marwa');
  });
  tearDown(() => db.close());

  EncoreSetItem item(String id, {bool removed = false}) =>
      EncoreSetItem(id: id, atMs: 1, removed: removed);

  group('the saved releases the sync hands over', () {
    test(
        'only catalogue releases (cat:) are kept; the music server\'s own albums are not',
        () async {
      await ReleaseStore(db, one)
          .applySaved([item('cat:100'), item('al-7'), item('cat:200')]);

      expect(await ReleaseStore(db, one).saved(), {'cat:100', 'cat:200'});
    });

    test('a release the server no longer has is taken out, and the others stay',
        () async {
      final store = ReleaseStore(db, one);
      await store.applySaved([item('cat:100'), item('cat:200')]);

      await store.applySaved([item('cat:100', removed: true)]);

      expect(await ReleaseStore(db, one).saved(), {'cat:200'});
    });

    test('a pass with no releases in it writes nothing', () async {
      await ReleaseStore(db, one).applySaved([item('al-7')]);

      expect(await ReleaseStore(db, one).saved(), isEmpty);
      expect(await db.select(db.syncState).get(), isEmpty);
    });
  });

  group('this phone\'s own releases', () {
    const release = PhoneRelease(
      refIds: ['sr_1', 'sr_2'],
      title: 'In Rainbows',
      artist: 'Radiohead',
      download: true,
    );

    test('are still there for a store that did not write them', () async {
      await ReleaseStore(db, one).put('cat:100', release);

      final back = (await ReleaseStore(db, one).phone())['cat:100']!;

      expect(back.refIds, ['sr_1', 'sr_2']);
      expect(back.title, 'In Rainbows');
      expect(back.artist, 'Radiohead');
      expect(back.download, isTrue);
    });

    test(
        'taking the downloads off keeps the release, with no intent to keep it here',
        () async {
      final store = ReleaseStore(db, one);
      await store.put('cat:100', release);

      await store.clearDownload('cat:100');

      final back = (await ReleaseStore(db, one).phone())['cat:100']!;
      expect(back.download, isFalse);
      expect(back.refIds, ['sr_1', 'sr_2'], reason: 'it is still saved');
    });

    test('the saved set and the phone\'s releases never share a key', () async {
      final store = ReleaseStore(db, one);
      await store.applySaved([item('cat:100')]);
      await store.put('cat:200', release);

      expect(await store.saved(), {'cat:100'});
      expect((await store.phone()).keys, ['cat:200']);
    });

    test('an entry that is not what it should be is skipped, not thrown on',
        () async {
      await db.into(db.syncState).insert(SyncStateCompanion.insert(
          serverId: one, key: ReleaseStore.phoneKey, value: '{"cat:1": 5}'));
      await db.into(db.syncState).insert(SyncStateCompanion.insert(
          serverId: one, key: ReleaseStore.savedKey, value: 'not json'));

      expect(await ReleaseStore(db, one).phone(), isEmpty);
      expect(await ReleaseStore(db, one).saved(), isEmpty);
    });
  });

  group('people on one phone', () {
    test(
        'another person\'s releases are not mine, and signing out takes mine with the account',
        () async {
      final two = await server('sara');
      await ReleaseStore(db, one).applySaved([item('cat:100')]);
      await ReleaseStore(db, one)
          .put('cat:100', const PhoneRelease(refIds: ['sr_1'], download: true));

      expect(await ReleaseStore(db, two).saved(), isEmpty);
      expect(await ReleaseStore(db, two).phone(), isEmpty);

      // Signing out removes the server row; the store goes with it.
      await (db.delete(db.servers)..where((s) => s.id.equals(one))).go();

      expect(await ReleaseStore(db, one).saved(), isEmpty);
      expect(await ReleaseStore(db, one).phone(), isEmpty);
    });
  });
}
