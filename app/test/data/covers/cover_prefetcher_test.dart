import 'dart:async';

import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:drift/native.dart';
import 'package:encore/core/cover_sizes.dart';
import 'package:encore/data/covers/cover_prefetcher.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/repos/library_repository.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/test_app.dart';

/// Offline shows covers, not letters (E3): the covers of what a person is likely to see are fetched while the network is there.
void main() {
  group('the fetcher', () {
    late Set<String> cache;
    late List<String> fetched;
    late Future<void> Function(String id, int size) onFetch;

    CoverPrefetcher make({int concurrency = 2, int giveUpAfter = 4}) =>
        CoverPrefetcher(
          serverId: 1,
          isCached: (key) async => cache.contains(key),
          fetch: (id, size) async {
            await onFetch(id, size);
            fetched.add('$id@$size');
            cache.add(CoverSize.key(1, id, size));
          },
          concurrency: concurrency,
          giveUpAfter: giveUpAfter,
        );

    setUp(() {
      cache = {};
      fetched = [];
      onFetch = (id, size) async {};
    });

    test('it fetches both sizes of what is missing and nothing that is cached',
        () async {
      cache.add(CoverSize.key(1, 'al-1', CoverSize.small));

      final count = await make().prefetch(['al-1', 'al-2']);

      expect(count, 3);
      expect(
          fetched,
          unorderedEquals([
            'al-1@${CoverSize.large}',
            'al-2@${CoverSize.large}',
            'al-2@${CoverSize.small}'
          ]));
    });

    test('a second run finds everything cached and fetches nothing', () async {
      final prefetcher = make();
      await prefetcher.prefetch(['al-1', 'al-2']);
      fetched.clear();

      expect(await prefetcher.prefetch(['al-1', 'al-2']), 0);
      expect(fetched, isEmpty);
    });

    test('on mobile data only the small size is asked for', () async {
      await make().prefetch(['al-1'], sizes: const [CoverSize.small]);
      expect(fetched, ['al-1@${CoverSize.small}']);
    });

    test('an id twice, or empty, is fetched once or not at all', () async {
      await make().prefetch(['al-1', '', 'al-1']);
      expect(
          fetched,
          unorderedEquals(
              ['al-1@${CoverSize.large}', 'al-1@${CoverSize.small}']));
    });

    test(
        'with the network gone it gives up after a few failures instead of trying every cover',
        () async {
      var asked = 0;
      onFetch = (id, size) async {
        asked++;
        throw Exception('offline');
      };

      final count = await make(giveUpAfter: 4)
          .prefetch([for (var i = 0; i < 200; i++) 'al-$i']);

      expect(count, 0);
      expect(asked, lessThan(10), reason: 'not 400 attempts');
    });

    test('one cover that fails does not stop the others', () async {
      onFetch = (id, size) async {
        if (id == 'al-2') throw Exception('404');
      };

      final count = await make().prefetch(['al-1', 'al-2', 'al-3']);

      expect(count, 4, reason: 'al-1 and al-3, two sizes each');
      expect(fetched, isNot(contains('al-2@${CoverSize.small}')));
    });

    test('it never runs more than the allowed number at once', () async {
      var running = 0;
      var most = 0;
      onFetch = (id, size) async {
        running++;
        if (running > most) most = running;
        await Future<void>.delayed(const Duration(milliseconds: 5));
        running--;
      };

      await make(concurrency: 2)
          .prefetch([for (var i = 0; i < 12; i++) 'al-$i']);

      expect(most, 2);
    });

    test('runs are one after the other: asking during a run waits for it',
        () async {
      final gate = Completer<void>();
      onFetch = (id, size) => gate.future;
      final prefetcher = make();

      final first =
          prefetcher.prefetch(['al-1'], sizes: const [CoverSize.small]);
      final second =
          prefetcher.prefetch(['al-1'], sizes: const [CoverSize.small]);
      gate.complete();

      expect(await first, 1);
      expect(await second, 0, reason: 'by then it is cached');
    });
  });

  group('what is worth keeping', () {
    late AppDatabase db;
    late int serverId;
    late LibraryRepository repo;

    setUp(() async {
      db = AppDatabase(NativeDatabase.memory());
      serverId = await Seed.library(db);
      repo = LibraryRepository(db, serverId);
    });

    tearDown(() => db.close());

    test(
        'the first songs of every playlist come first, and every cover is there once',
        () async {
      final ids = await repo.coverIdsToKeepOffline();

      // The first song of the four playlists is in al3, al1, al3 and al6: those albums' covers come first.
      expect(ids.take(3).toSet(), {'al-al1', 'al-al3', 'al-al6'});
      expect(ids.toSet(), {
        for (final a in ['al1', 'al2', 'al3', 'al4', 'al5', 'al6']) 'al-$a'
      });
      expect(ids.length, ids.toSet().length, reason: 'each cover once');
    });

    test(
        "a song row's own cover id is fetched too when it differs from its album's",
        () async {
      // The row of a song shows `mf-...`; the collage and the album page show the album's id. Offline the row was a letter (E3).
      await (db.update(db.tracks)..where((t) => t.id.equals('al3-t1')))
          .write(const TracksCompanion(coverArt: Value('mf-al3-t1')));
      await (db.update(db.tracks)..where((t) => t.id.equals('al3-t2'))).write(
          const TracksCompanion(
              coverArt:
                  Value('al-al3'))); // the same id as the album's: not twice

      final ids = await repo.coverIdsToKeepOffline();

      expect(ids, contains('mf-al3-t1'));
      expect(ids.where((id) => id == 'al-al3'), hasLength(1));
    });

    test(
        "a song the server found a picture for brings that picture into the playlist's collage, not its album's blank record",
        () async {
      const url = 'https://cdn-images.dzcdn.net/images/cover/abc/1000x1000.jpg';
      await (db.update(db.tracks)..where((t) => t.albumId.equals('al3')))
          .write(const TracksCompanion(coverArt: Value(url)));

      final ids = await repo.coverIdsToKeepOffline();
      final playlists = await db.select(db.playlists).get();
      final collages = <String>{};
      for (final p in playlists) {
        collages.addAll(await repo.watchPlaylistCoverIds(p.id).first);
      }

      expect(ids, contains(url));
      expect(collages, contains(url));
      expect(collages, isNot(contains('al-al3')));
    });

    test('the list is cut at the limit', () async {
      expect(await repo.coverIdsToKeepOffline(limit: 2), hasLength(2));
    });

    test('a song that is downloaded brings its cover before the newest albums',
        () async {
      // Two albums that no playlist and no like mentions: a new one, and an old one with a song on the phone.
      for (final (id, created) in [('new', 9000000000000), ('old', 1)]) {
        await db.into(db.albums).insert(AlbumsCompanion.insert(
              serverId: serverId,
              id: id,
              name: id,
              coverArt: Value('al-$id'),
              createdAtMs: Value(created),
            ));
        await db.into(db.tracks).insert(TracksCompanion.insert(
              serverId: serverId,
              id: '$id-t1',
              title: id,
              albumId: Value(id),
            ));
      }
      await db.into(db.downloads).insert(DownloadsCompanion.insert(
            serverId: serverId,
            trackId: 'old-t1',
            state: const Value(2),
            updatedAtMs: 0,
          ));

      final ids = await repo.coverIdsToKeepOffline();

      expect(ids.indexOf('al-old'), lessThan(ids.indexOf('al-new')),
          reason: 'what is on the phone matters more than what is merely new');
    });

    test('albums that were deleted are not fetched', () async {
      await (db.update(db.albums)..where((a) => a.id.equals('al6')))
          .write(AlbumsCompanion(deletedAtMs: Value(1)));
      await (db.update(db.tracks)..where((t) => t.albumId.equals('al6')))
          .write(TracksCompanion(deletedAtMs: Value(1)));

      expect(await repo.coverIdsToKeepOffline(), isNot(contains('al-al6')));
    });
  });
}
