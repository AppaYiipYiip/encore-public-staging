import 'dart:convert';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:drift/native.dart';
import 'package:encore/core/clock.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/db/search_dao.dart';
import 'package:encore/data/downloads/download_planner.dart';
import 'package:encore/data/encore/encore_api.dart';
import 'package:encore/data/encore/encore_merge.dart';
import 'package:encore/data/encore/encore_models.dart';
import 'package:encore/data/encore/encore_sync.dart';
import 'package:encore/data/encore/encore_writer.dart';
import 'package:encore/data/repos/downloads_repository.dart';
import 'package:encore/data/repos/library_repository.dart';
import 'package:encore/data/repos/release_store.dart';
import 'package:encore/data/sync/library_writer.dart';
import 'package:encore/data/sync/sync_state_store.dart';
import 'package:encore/playback/playback_state_store.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:path/path.dart' as p;

import '../../support/fake_encore_server.dart';

/// N-11 part B, the phone's half (docs/17 "Songs merged into another", docs/34 CF-43): the server folded two refs that held one file into one;
/// a phone that synced earlier still has BOTH rows (and a download of one, a like on the other, places in playlists, a saved queue...). It must
/// fold them: one song, one entry, one download, and nothing the person has is lost on the way.
void main() {
  late AppDatabase db;
  late int serverId;
  late Directory dir;
  late EncoreWriter writer;
  late SyncStateStore state;

  setUp(() async {
    db = AppDatabase(NativeDatabase.memory());
    serverId = await db.into(db.servers).insert(ServersCompanion.insert(
          name: 'Test',
          username: 'tester',
          endpointsJson: '[]',
          createdAtMs: 0,
        ));
    dir = Directory.systemTemp.createTempSync('encore_merge_test_');
    writer = EncoreWriter(db, serverId, ownerName: 'tester');
    state = SyncStateStore(db, serverId);
  });

  tearDown(() async {
    await db.close();
    if (dir.existsSync()) dir.deleteSync(recursive: true);
  });

  // ------------------------------------------------------------------ what a test arranges

  Future<void> song(
    String id, {
    String title = 'Echo',
    String? album,
    String? albumId,
    int? starredAtMs,
    int? deletedAtMs,
    int? durationSec,
    String audioKey = '',
  }) =>
      db.into(db.tracks).insert(TracksCompanion.insert(
            serverId: serverId,
            id: id,
            title: title,
            isRef: const Value(true),
            fileId: Value('nd-$id'),
            album: Value(album),
            albumId: Value(albumId),
            artist: const Value('Ivy Jo'),
            artistsJson: const Value('["Ivy Jo"]'),
            starredAtMs: Value(starredAtMs),
            deletedAtMs: Value(deletedAtMs),
            durationSec: Value(durationSec),
            audioKey: Value(audioKey),
          ));

  /// A download whose file really exists (in the temp folder), named the way the manager names it: `<track id>.opus`.
  Future<String> download(
    String id, {
    int state = DownloadState.done,
    bool withFile = true,
    String sourceKey = '',
    String quality = 'original',
    String content = 'audio',
    String ext = 'opus',
  }) async {
    final path = p.join(dir.path, '$id.$ext');
    if (withFile) File(path).writeAsStringSync('$content:$id');
    await db.into(db.downloads).insert(DownloadsCompanion.insert(
          serverId: serverId,
          trackId: id,
          state: Value(state),
          localPath: Value(withFile ? path : null),
          bytes: Value(withFile ? 10 : 0),
          sourceAudioKey: Value(sourceKey),
          quality: Value(quality),
          updatedAtMs: 1,
        ));
    return path;
  }

  Future<void> entry(String playlist, int position, String trackId) async {
    await db
        .into(db.playlists)
        .insertOnConflictUpdate(PlaylistsCompanion.insert(
          serverId: serverId,
          id: playlist,
          name: 'List $playlist',
        ));
    await db.into(db.playlistEntries).insert(PlaylistEntriesCompanion.insert(
          serverId: serverId,
          playlistId: playlist,
          position: position,
          trackId: trackId,
          entryId: Value('pe_$playlist$position'),
        ));
  }

  Future<void> play(String trackId) =>
      db.into(db.playHistory).insert(PlayHistoryCompanion.insert(
            serverId: serverId,
            trackId: trackId,
            playedAtMs: 5,
          ));

  Future<void> pin(String trackId, {String quality = 'original'}) =>
      db.into(db.pins).insert(PinsCompanion.insert(
            serverId: serverId,
            targetType: 'track',
            targetId: trackId,
            quality: Value(quality),
            createdAtMs: 1,
          ));

  Future<void> lyrics(String trackId, String body) =>
      db.into(db.lyrics).insert(LyricsCompanion.insert(
            serverId: serverId,
            trackId: trackId,
            kind: 'plain',
            body: body,
            fetchedAtMs: 1,
          ));

  EncoreMerge merge(String from, String into, [int seq = 1]) =>
      EncoreMerge(from: from, into: into, seq: seq);

  /// What the sync does with a page of merges: inside one transaction (before the refs), then the files once it committed.
  Future<MergeOutcome> fold(List<EncoreMerge> merges) async {
    late MergeOutcome outcome;
    await db.transaction(() async {
      outcome = await writer.applyMerges(merges);
      await writer.settleMerges(outcome);
    });
    await writer.finishMerges(outcome);
    return outcome;
  }

  Future<List<String>> liveIds() async => [
        for (final t in await (db.select(db.tracks)
              ..where((t) => t.deletedAtMs.isNull())
              ..orderBy([(t) => OrderingTerm.asc(t.id)]))
            .get())
          t.id
      ];

  Future<TrackRow?> track(String id) => (db.select(db.tracks)
        ..where((t) => t.serverId.equals(serverId) & t.id.equals(id)))
      .getSingleOrNull();

  Future<DownloadRow?> dl(String id) => (db.select(db.downloads)
        ..where((d) => d.serverId.equals(serverId) & d.trackId.equals(id)))
      .getSingleOrNull();

  Future<List<String>> entriesOf(String playlist) async => [
        for (final e in await (db.select(db.playlistEntries)
              ..where((e) => e.playlistId.equals(playlist))
              ..orderBy([(e) => OrderingTerm.asc(e.position)]))
            .get())
          e.trackId
      ];

  /// Every row of the tables a merge touches, as text: two states are the same when these are.
  Future<String> dump() async {
    final out = StringBuffer();
    for (final table in const [
      'tracks',
      'playlist_entries',
      'play_history',
      'pins',
      'downloads',
      'lyrics',
      'sync_state',
    ]) {
      final rows = await db.customSelect('SELECT * FROM $table').get();
      out.writeln(
          '$table: ${rows.map((r) => jsonEncode(r.data)).toList()..sort()}');
    }
    return out.toString();
  }

  const loser = 'sr_000000000000000000000000L1';
  const survivor = 'sr_000000000000000000000000S1';

  // ------------------------------------------------------------------ the contract

  group('the server\'s answer (the real response the server test saved)', () {
    Map<String, dynamic> fixture() =>
        (jsonDecode(File('test/fixtures/server/library-files-with-merges.json')
                .readAsStringSync()) as Map)
            .cast<String, dynamic>();

    test(
        'the parser reads the merges, their cursor and whether there are more, from the file the server wrote',
        () {
      final files = EncoreFiles.fromJson(fixture());

      expect(files.merges.map((m) => (m.seq, m.from, m.into)), [
        (1, 'sr_00000000000000000000000002', 'sr_00000000000000000000000001'),
        (2, 'sr_00000000000000000000000004', 'sr_00000000000000000000000003'),
        (3, 'sr_00000000000000000000000006', 'sr_00000000000000000000000005'),
        (4, 'sr_00000000000000000000000008', 'sr_00000000000000000000000007'),
        (5, 'sr_00000000000000000000000011', 'sr_00000000000000000000000009'),
        (6, 'sr_00000000000000000000000017', 'sr_00000000000000000000000016'),
      ]);
      expect(files.mergesCursor, '6');
      expect(files.mergesMore, isFalse);
      // The songs of the same answer are read as before.
      expect(files.refs, hasLength(11));
      expect(files.cursor, '23');
    });

    test(
        'an answer without merges (a server from before them) reads as none, and no cursor to keep',
        () {
      final old = fixture()
        ..remove('merges')
        ..remove('mergesCursor')
        ..remove('mergesMore');

      final files = EncoreFiles.fromJson(old);

      expect(files.merges, isEmpty);
      expect(files.mergesCursor, isNull);
      expect(files.mergesMore, isFalse);
    });

    test(
        'an entry that names no song, or a song merged into itself, is skipped (one odd entry never stops a sync); the rest are in order of seq',
        () {
      final files = EncoreFiles.fromJson({
        'refs': const <Object?>[],
        'cursor': '0',
        'more': false,
        'merges': [
          {'from': 'b', 'into': 'c', 'seq': 2},
          {'from': 'a', 'into': 'b', 'seq': 1},
          {'from': 'x', 'into': 'x', 'seq': 3},
          {'into': 'y', 'seq': 4},
          'what',
        ],
        'mergesCursor': '2',
        'mergesMore': true,
      });

      expect(files.merges.map((m) => '${m.from}>${m.into}'), ['a>b', 'b>c']);
      expect(files.mergesMore, isTrue);
    });
  });

  // ------------------------------------------------------------------ one song is one entry

  group('everything the phone has under the old id moves to the survivor', () {
    test(
        'playlist entries and plays are re-pointed (nothing skipped, nothing lost) and the old row is gone',
        () async {
      await song(loser);
      await song(survivor);
      await entry('pl_a', 0, loser);
      await entry('pl_a', 1, 'sr_other');
      await entry('pl_b', 0, loser);
      await play(loser);
      await play(loser);
      await play(survivor);

      final outcome = await fold([merge(loser, survivor)]);

      expect(await entriesOf('pl_a'), [survivor, 'sr_other']);
      expect(await entriesOf('pl_b'), [survivor]);
      final plays = await db.select(db.playHistory).get();
      expect(plays.map((r) => r.trackId), everyElement(survivor));
      expect(plays, hasLength(3));
      expect(await track(loser), isNull);
      expect(await liveIds(), [survivor]);
      expect(outcome.folded, 1);
    });

    test(
        'the like of the old row goes to the survivor when it has none, and the survivor\'s own like is never replaced',
        () async {
      await song(loser, starredAtMs: 111);
      await song(survivor);
      await fold([merge(loser, survivor)]);
      expect((await track(survivor))!.starredAtMs, 111);

      // Both liked: the survivor's stays.
      await song('sr_000000000000000000000000L2', starredAtMs: 222);
      await song('sr_000000000000000000000000S2', starredAtMs: 333);
      await fold([
        merge(
            'sr_000000000000000000000000L2', 'sr_000000000000000000000000S2', 2)
      ]);
      expect((await track('sr_000000000000000000000000S2'))!.starredAtMs, 333);
    });

    test(
        'the phone never had the survivor: the old row is renamed to it, with its like, and the page\'s own data then lands on it',
        () async {
      await song(loser, title: 'Old tags', starredAtMs: 111);
      await entry('pl_a', 0, loser);
      await download(loser);

      await fold([merge(loser, survivor)]);

      final row = await track(survivor);
      expect(row, isNotNull);
      expect(row!.starredAtMs, 111);
      expect(row.title, 'Old tags');
      expect(await track(loser), isNull);
      expect(await liveIds(), [survivor]);
      expect(await entriesOf('pl_a'), [survivor]);
      expect(await dl(survivor), isNotNull);
    });

    test(
        'a survivor that the phone had retired (no file, nothing of the person\'s) comes back when the old row was live',
        () async {
      await song(loser, starredAtMs: 5);
      await song(survivor, deletedAtMs: 99);

      await fold([merge(loser, survivor)]);

      expect((await track(survivor))!.deletedAtMs, isNull);
      expect(await liveIds(), [survivor]);
    });

    test(
        'the Songs total and the album lists show one song: the old copy under "[Unknown Album]" is gone, the right album has its song',
        () async {
      await song(loser,
          title: 'Creature', album: '[Unknown Album]', albumId: 'al-unknown');
      await song(survivor,
          title: 'Creature', album: 'The Darkest Place', albumId: 'al-1');
      final library = LibraryRepository(db, serverId);
      expect(await library.watchTrackCount().first, 2);

      await fold([merge(loser, survivor)]);

      expect(await library.watchTrackCount().first, 1);
      expect((await library.watchAlbumTracks('al-1').first).map((t) => t.id),
          [survivor]);
      expect(await library.watchAlbumTracks('al-unknown').first, isEmpty);
    });

    test('a search for the title finds the song once', () async {
      await song(loser, title: 'Hate Me');
      await song(survivor, title: 'Hate Me');
      expect(await SearchDao(db).tracks(serverId, 'hate').get(), hasLength(2));

      await fold([merge(loser, survivor)]);

      final hits = await SearchDao(db).tracks(serverId, 'hate').get();
      expect(hits.map((t) => t.id), [survivor]);
    });

    test(
        'a pin on the one song moves; when both are pinned the survivor\'s stays at the better quality (and the old pin is gone)',
        () async {
      await song(loser);
      await song(survivor);
      await pin(loser);
      await fold([merge(loser, survivor)]);
      var pins = await db.select(db.pins).get();
      expect(pins.map((p) => p.targetId), [survivor]);

      await song('sr_000000000000000000000000L2');
      await song('sr_000000000000000000000000S2');
      await pin('sr_000000000000000000000000L2', quality: 'original');
      await pin('sr_000000000000000000000000S2', quality: 'opus96');
      await fold([
        merge(
            'sr_000000000000000000000000L2', 'sr_000000000000000000000000S2', 2)
      ]);
      pins = await (db.select(db.pins)
            ..where((p) => p.targetId.equals('sr_000000000000000000000000S2')))
          .get();
      expect(pins, hasLength(1));
      expect(pins.single.quality, 'original');
      expect(await db.select(db.pins).get(), hasLength(2));
    });

    test(
        'lyrics move to the survivor when it has none; its own are kept when it has',
        () async {
      await song(loser);
      await song(survivor);
      await lyrics(loser, 'words of the old row');
      await fold([merge(loser, survivor)]);
      var rows = await db.select(db.lyrics).get();
      expect(rows.map((r) => (r.trackId, r.body)),
          [(survivor, 'words of the old row')]);

      await song('sr_000000000000000000000000L2');
      await song('sr_000000000000000000000000S2');
      await lyrics('sr_000000000000000000000000L2', 'old');
      await lyrics('sr_000000000000000000000000S2', 'own');
      await fold([
        merge(
            'sr_000000000000000000000000L2', 'sr_000000000000000000000000S2', 2)
      ]);
      rows = await (db.select(db.lyrics)
            ..where((l) => l.trackId.equals('sr_000000000000000000000000S2')))
          .get();
      expect(rows.single.body, 'own');
      expect(await db.select(db.lyrics).get(), hasLength(2));
    });

    test(
        'a chain in one page (A into B, then B into C) ends at C: every child, the like and the download follow it all the way',
        () async {
      const a = 'sr_00000000000000000000000000A';
      const b = 'sr_00000000000000000000000000B';
      const c = 'sr_00000000000000000000000000C';
      await song(a, starredAtMs: 7);
      await song(b);
      await song(c);
      await entry('pl_a', 0, a);
      await entry('pl_a', 1, b);
      await play(a);
      await download(a);

      await fold([merge(a, b, 1), merge(b, c, 2)]);

      expect(await liveIds(), [c]);
      expect((await track(c))!.starredAtMs, 7);
      expect(await entriesOf('pl_a'), [c, c]);
      expect((await db.select(db.playHistory).get()).single.trackId, c);
      final row = await dl(c);
      expect(row, isNotNull);
      expect(await db.select(db.downloads).get(), hasLength(1));
      // One copy, named after the song it ended up with (never an orphan, never a name of the middle one).
      expect(File(row!.localPath!).existsSync(), isTrue);
      expect(p.basename(row.localPath!), '$c.opus');
      expect(dir.listSync(), hasLength(1));
    });

    test(
        'a chain across two pages (A into B now, B into C later) ends at C the same way',
        () async {
      const a = 'sr_00000000000000000000000000A';
      const b = 'sr_00000000000000000000000000B';
      const c = 'sr_00000000000000000000000000C';
      await song(a);
      await song(b);
      await song(c);
      await entry('pl_a', 0, a);
      await download(a);

      await fold([merge(a, b, 1)]);
      expect(await entriesOf('pl_a'), [b]);
      await fold([merge(b, c, 2)]);

      expect(await entriesOf('pl_a'), [c]);
      expect(await liveIds(), [c]);
      expect(p.basename((await dl(c))!.localPath!), '$c.opus');
      expect(dir.listSync(), hasLength(1));
    });

    test(
        'applying the same merge again changes nothing (a re-sent page, a phone that reads them all from 0)',
        () async {
      await song(loser, starredAtMs: 1);
      await song(survivor);
      await entry('pl_a', 0, loser);
      await play(loser);
      await pin(loser);
      await lyrics(loser, 'x');
      await download(loser);
      await state.set(
          'playback.state',
          jsonEncode({
            'queue': {
              'ids': [loser]
            }
          }));

      final first = await fold([merge(loser, survivor)]);
      final after = await dump();
      final second = await fold([merge(loser, survivor)]);

      expect(first.folded, 1);
      expect(second.folded, 0);
      expect(await dump(), after);
    });

    test(
        'an empty list is nothing, and a merge of a song the phone never had is nothing',
        () async {
      await song('sr_other');
      final before = await dump();

      expect((await fold(const [])).folded, 0);
      expect((await fold([merge(loser, survivor)])).folded, 0);

      expect(await dump(), before);
    });
  });

  // ------------------------------------------------------------------ the download is moved, never deleted

  group('a download of the old song', () {
    test(
        'only the old one is downloaded: the file is MOVED to the survivor (renamed, the row re-keyed, nothing deleted, the audio is the same file)',
        () async {
      await song(loser);
      await song(survivor);
      final oldPath = await download(loser, sourceKey: 'k-old');

      final outcome = await fold([merge(loser, survivor)]);

      final row = await dl(survivor);
      expect(row, isNotNull);
      expect(await dl(loser), isNull);
      expect(row!.state, DownloadState.done);
      expect(p.basename(row.localPath!), '$survivor.opus');
      expect(File(row.localPath!).readAsStringSync(), 'audio:$loser',
          reason: 'the very same bytes, not a new download');
      expect(File(oldPath).existsSync(), isFalse);
      expect(dir.listSync(), hasLength(1));
      expect(row.bytes, 10);
      expect(outcome.deletes, isEmpty);
      expect(await db.select(db.downloads).get(), hasLength(1));
    });

    test(
        'the survivor has a queued or failed row of its own (no file): the copy takes its place',
        () async {
      await song(loser);
      await song(survivor);
      await download(loser);
      await db.into(db.downloads).insert(DownloadsCompanion.insert(
          serverId: serverId,
          trackId: survivor,
          state: const Value(DownloadState.failed),
          updatedAtMs: 1));

      await fold([merge(loser, survivor)]);

      final row = await dl(survivor);
      expect(row!.state, DownloadState.done);
      expect(File(row.localPath!).existsSync(), isTrue);
      expect(await db.select(db.downloads).get(), hasLength(1));
    });

    test(
        'both are downloaded: the survivor\'s copy is kept and only the old file is deleted (after the commit)',
        () async {
      await song(loser);
      await song(survivor);
      final oldPath = await download(loser);
      final ownPath = await download(survivor);

      final outcome = await fold([merge(loser, survivor)]);

      expect(outcome.deletes, [oldPath]);
      expect(File(oldPath).existsSync(), isFalse);
      expect(File(ownPath).existsSync(), isTrue);
      expect((await dl(survivor))!.localPath, ownPath);
      expect(await dl(loser), isNull);
      expect(await db.select(db.downloads).get(), hasLength(1));
    });

    test(
        'both are downloaded and the old copy is the better one (the survivor has a 48 kbps Data saver copy): the 160 kbps file ends up under the survivor id, the worse file and row are gone',
        () async {
      await song(loser);
      await song(survivor);
      final better = await download(loser, quality: 'opus160', content: 'high');
      final worse = await download(survivor, quality: 'opus48', content: 'low');

      final outcome = await fold([merge(loser, survivor)]);

      final row = await dl(survivor);
      expect(await dl(loser), isNull);
      expect(await db.select(db.downloads).get(), hasLength(1));
      expect(row!.quality, 'opus160');
      expect(p.basename(row.localPath!), '$survivor.opus');
      expect(File(row.localPath!).readAsStringSync(), 'high:$loser',
          reason: 'the better file, not the 48 kbps one');
      expect(File(better).existsSync(), isFalse);
      expect(dir.listSync(), hasLength(1));
      expect(outcome.deletes, [worse]);
    });

    test(
        'the better copy of a different container is renamed to the survivor id with its own extension (a flac over an opus)',
        () async {
      await song(loser);
      await song(survivor);
      await download(loser, quality: 'original', ext: 'flac', content: 'flac');
      await download(survivor, quality: 'opus96', content: 'opus');

      await fold([merge(loser, survivor)]);

      final row = await dl(survivor);
      expect(p.basename(row!.localPath!), '$survivor.flac');
      expect(File(row.localPath!).readAsStringSync(), 'flac:$loser');
      expect(dir.listSync(), hasLength(1));
    });

    test(
        'both are downloaded and the survivor copy is the better one (or equal): it stays where it is and the old file goes',
        () async {
      await song(loser);
      await song(survivor);
      final oldPath = await download(loser, quality: 'opus48');
      final ownPath = await download(survivor, quality: 'opus160');

      await fold([merge(loser, survivor)]);

      expect((await dl(survivor))!.quality, 'opus160');
      expect((await dl(survivor))!.localPath, ownPath);
      expect(File(ownPath).existsSync(), isTrue);
      expect(File(oldPath).existsSync(), isFalse);
    });

    test(
        'the row of the copy that stays is re-keyed in place: what it carries (the time it was made, its bytes, its attempts) comes along',
        () async {
      await song(loser);
      await song(survivor);
      await download(loser, quality: 'opus160');
      await (db.update(db.downloads)..where((d) => d.trackId.equals(loser)))
          .write(const DownloadsCompanion(
              bytes: Value(1234), updatedAtMs: Value(777), attempts: Value(3)));
      await download(survivor, quality: 'opus48');

      await fold([merge(loser, survivor)]);

      final row = await dl(survivor);
      expect((row!.bytes, row.updatedAtMs, row.attempts), (1234, 777, 3));
    });

    test(
        'the survivor is downloading right now: it is left to finish and the old copy goes (the same song is arriving)',
        () async {
      await song(loser);
      await song(survivor);
      final oldPath = await download(loser);
      await db.into(db.downloads).insert(DownloadsCompanion.insert(
          serverId: serverId,
          trackId: survivor,
          state: const Value(DownloadState.downloading),
          updatedAtMs: 1));

      await fold([merge(loser, survivor)]);

      expect((await dl(survivor))!.state, DownloadState.downloading);
      expect(File(oldPath).existsSync(), isFalse);
    });

    test(
        'the old one is still being downloaded for the first time: its row goes and the survivor is queued in its place (the running transfer finds no row when it ends and throws its file away)',
        () async {
      await song(loser);
      await song(survivor);
      await download(loser, state: DownloadState.downloading, withFile: false);

      await fold([merge(loser, survivor)]);

      expect(await dl(loser), isNull);
      final row = await dl(survivor);
      expect(row!.state, DownloadState.queued);
      expect(row.localPath, isNull);
    });

    test(
        'a refresh of the old copy in flight (the old copy is still on disk): the copy moves, as done',
        () async {
      await song(loser);
      await song(survivor);
      await download(loser, state: DownloadState.downloading);

      await fold([merge(loser, survivor)]);

      final row = await dl(survivor);
      expect(row!.state, DownloadState.done);
      expect(File(row.localPath!).existsSync(), isTrue);
    });

    test(
        'the files cannot be renamed: the row still names the file where it is, so the song plays and nothing is lost',
        () async {
      await song(loser);
      await song(survivor);
      final oldPath = await download(loser);
      final broken = EncoreWriter(db, serverId,
          ownerName: 'tester', files: _FailingFiles());

      late MergeOutcome outcome;
      await db.transaction(() async {
        outcome = await broken.applyMerges([merge(loser, survivor)]);
      });
      await broken.finishMerges(outcome);

      final row = await dl(survivor);
      expect(row!.localPath, oldPath);
      expect(File(oldPath).existsSync(), isTrue);
    });

    test(
        'the file is not where the row says (the system cleared it): the move still re-keys the row and nothing throws',
        () async {
      await song(loser);
      await song(survivor);
      final oldPath = await download(loser);
      File(oldPath).deleteSync();

      await fold([merge(loser, survivor)]);

      expect((await dl(survivor))!.localPath, oldPath);
    });

    test(
        'a copy that is named in some other way than the manager names it keeps its name (only the row changes)',
        () async {
      await song(loser);
      await song(survivor);
      final odd = p.join(dir.path, 'something-else.opus');
      File(odd).writeAsStringSync('x');
      await db.into(db.downloads).insert(DownloadsCompanion.insert(
          serverId: serverId,
          trackId: loser,
          state: const Value(DownloadState.done),
          localPath: Value(odd),
          updatedAtMs: 1));

      await fold([merge(loser, survivor)]);

      expect((await dl(survivor))!.localPath, odd);
      expect(File(odd).existsSync(), isTrue);
    });

    test(
        'the moved copy is NOT downloaded again and NOT deleted: it takes the survivor\'s audio key, a track pin follows, and the planner (no grace) has nothing to do',
        () async {
      // The two refs share one file but describe it with their own length: their audio keys differ.
      await song(loser, durationSec: 200, audioKey: 'key-200');
      await song(survivor, durationSec: 207, audioKey: 'key-207');
      await pin(loser);
      await download(loser, sourceKey: 'key-200');

      final outcome = await fold([merge(loser, survivor)]);

      expect(outcome.moves, hasLength(1));
      expect((await dl(survivor))!.sourceAudioKey, 'key-207');
      final repo = DownloadsRepository(db, serverId);
      final plan = planDownloads(
        desired: await repo.desired(),
        existing: await repo.existing(),
        nowMs: 1000,
        graceMs: 0,
      );
      expect(plan.isEmpty, isTrue, reason: '$plan');
      expect(
          await LibraryWriter(db)
              .markStaleDownloads(serverId: serverId, nowMs: 1000),
          0);
    });

    test(
        'a playlist pin wants the song under the survivor now, and the moved copy answers it',
        () async {
      await song(loser, audioKey: 'k');
      await song(survivor, audioKey: 'k');
      await entry('pl_a', 0, loser);
      await db.into(db.pins).insert(PinsCompanion.insert(
          serverId: serverId,
          targetType: 'playlist',
          targetId: 'pl_a',
          createdAtMs: 1));
      await download(loser, sourceKey: 'k');

      await fold([merge(loser, survivor)]);

      final repo = DownloadsRepository(db, serverId);
      final desired = await repo.desired();
      expect(desired.keys, [survivor]);
      final plan = planDownloads(
          desired: desired,
          existing: await repo.existing(),
          nowMs: 1000,
          graceMs: 0);
      expect(plan.isEmpty, isTrue, reason: '$plan');
    });
  });

  // ------------------------------------------------------------------ the saved queue and what else names a song

  group('the saved queue, the resume position and the saved releases', () {
    test(
        'a queue that names the old song names the survivor, the order, the cursor and the resume position stay as they were',
        () async {
      await song(loser);
      await song(survivor);
      const store = 'playback.state';
      final queue = {
        'queue': {
          'ids': ['sr_a', loser, 'sr_b', loser],
          'order': [0, 1, 2, 3],
          'cursor': 1,
          'shuffle': false,
          'repeat': 'off',
          'named': {
            'https://x/y.mp3': {'artist': 'a', 'title': 't', 'album': null}
          },
        },
        'positionMs': 83000,
        'sourceName': 'My list',
        'sourceId': 'pl_a',
      };
      await state.set(store, jsonEncode(queue));
      await state.set(
          'playback.progress', jsonEncode({'id': loser, 'ms': 90500}));

      await fold([merge(loser, survivor)]);

      final saved = await DbPlaybackStateStore(state).load();
      expect(saved!.queue['ids'], ['sr_a', survivor, 'sr_b', survivor]);
      expect(saved.queue['order'], [0, 1, 2, 3]);
      expect(saved.queue['cursor'], 1);
      expect(saved.queue['named'], {
        'https://x/y.mp3': {'artist': 'a', 'title': 't', 'album': null}
      });
      expect(saved.positionMs, 83000);
      expect(saved.sourceId, 'pl_a');
      final progress = await DbPlaybackStateStore(state).loadProgress();
      expect(progress!.itemId, survivor,
          reason:
              'the engine uses the position only when it is for the song that is current: the old id would drop it');
      expect(progress.positionMs, 90500);
    });

    test('a queue that names none of the merged songs is not rewritten',
        () async {
      await song(loser);
      await song(survivor);
      final raw = jsonEncode({
        'queue': {
          'ids': ['sr_a']
        }
      });
      await state.set('playback.state', raw);

      await fold([merge(loser, survivor)]);

      expect(await state.get('playback.state'), raw);
    });

    test(
        'a damaged snapshot is left alone (the player ignores it as it always did)',
        () async {
      await state.set('playback.state', '{not json');

      await fold([merge(loser, survivor)]);

      expect(await state.get('playback.state'), '{not json');
    });

    test(
        'a chain also moves the queue all the way (A into B, B into C: a queue naming A names C)',
        () async {
      await state.set(
          'playback.state',
          jsonEncode({
            'queue': {
              'ids': ['A', 'B']
            }
          }));

      await fold([merge('A', 'B', 1), merge('B', 'C', 2)]);

      expect(
          (await DbPlaybackStateStore(state).load())!.queue['ids'], ['C', 'C']);
    });

    test(
        'a release saved on this phone names the survivor once (Library > Downloaded would show the same song twice, or a missing one)',
        () async {
      final releases = ReleaseStore(db, serverId);
      await releases.put(
          'cat:1',
          const PhoneRelease(
              refIds: ['sr_a', loser, 'sr_b', survivor],
              title: 'Album',
              artist: 'Artist',
              download: true));
      await releases.put(
          'cat:2', const PhoneRelease(refIds: ['sr_a'], title: 'Other'));

      await fold([merge(loser, survivor)]);

      final now = await releases.phone();
      expect(now['cat:1']!.refIds, ['sr_a', survivor, 'sr_b']);
      expect(now['cat:1']!.download, isTrue);
      expect(now['cat:1']!.title, 'Album');
      expect(now['cat:2']!.refIds, ['sr_a']);
    });
  });

  // ------------------------------------------------------------------ the pull

  group('the pull', () {
    late FakeEncoreServer server;
    EncoreSync make({int pageLimit = 500}) => EncoreSync(
          db: db,
          api: EncoreApi(
            dio: Dio()..httpClientAdapter = server.adapter,
            baseUrl: () => Uri.parse('http://home.test:4540'),
            auth: () => {'u': 'tester', 't': 'tok', 's': 'salt'},
          ),
          serverId: serverId,
          ownerName: 'tester',
          clock: FakeClock(DateTime.utc(2026, 11, 14, 12)),
          pageLimit: pageLimit,
        );

    setUp(() => server = FakeEncoreServer());

    test(
        'the real response, served as the server wrote it: the old row becomes the survivor, with the survivor\'s own data, the like, the place in the playlist and the file',
        () async {
      server.filesAnswer = (jsonDecode(
              File('test/fixtures/server/library-files-with-merges.json')
                  .readAsStringSync()) as Map)
          .cast<String, Object?>();
      const old = 'sr_00000000000000000000000002';
      const into = 'sr_00000000000000000000000001';
      // A phone that synced before the server merged: it holds the old row, with tags of its own, a like, an entry, a play and a download.
      await song(old, title: 'Old tags', starredAtMs: 42);
      await entry('pl_a', 0, old);
      await play(old);
      final oldPath = await download(old);

      final result = await make().pull();

      expect(result.isOk, isTrue);
      expect(await track(old), isNull);
      final row = await track(into);
      expect(row!.title, 'Neon Harbor',
          reason: 'the page\'s own data lands on the renamed row');
      expect(row.starredAtMs, 42);
      expect(await entriesOf('pl_a'), [into]);
      expect((await db.select(db.playHistory).get()).single.trackId, into);
      final moved = await dl(into);
      expect(p.basename(moved!.localPath!), '$into.opus');
      expect(File(moved.localPath!).existsSync(), isTrue);
      expect(File(oldPath).existsSync(), isFalse);
      expect(await state.get(EncoreSync.mergesCursor), '6');
      expect(await state.get(EncoreSync.filesCursor), '23');
      // The phone asked from 0 for the merges, and the answer is not asked for again once it is read.
      expect(server.mergesSinceSeen.first, '0');
    });

    test(
        'a phone that has none of the merged songs just stores the cursor (a fresh phone reads the whole list from 0 and folds nothing)',
        () async {
      server.filesAnswer = (jsonDecode(
              File('test/fixtures/server/library-files-with-merges.json')
                  .readAsStringSync()) as Map)
          .cast<String, Object?>();

      final stats = (await make().pull()).getOrThrow();

      expect(stats.merges, 0);
      expect(stats.files, 11);
      expect(await state.get(EncoreSync.mergesCursor), '6');
      expect(await liveIds(), hasLength(11));
    });

    test(
        'merges are read in pages, with their own cursor, even after the files are caught up; and the cursor is kept',
        () async {
      // 8 merges of songs the phone holds, two files, a page of 3.
      for (var i = 1; i <= 8; i++) {
        final from = server.addRef('Song $i', 'Artist', fileId: 'nd-$i');
        final into = server.addRef('Song $i', 'Artist', fileId: 'nd-$i');
        await song(from);
        await entry('pl_a', i, from);
        server.mergeRefs(from, into);
      }

      final stats = (await make(pageLimit: 3).pull()).getOrThrow();

      expect(stats.merges, 8);
      expect(await state.get(EncoreSync.mergesCursor), '8');
      final entries = await entriesOf('pl_a');
      expect(entries, hasLength(8));
      expect(entries.every(server.refs.containsKey), isTrue,
          reason: 'every entry names a song the server still has');
      // The cursors were sent: the first question from 0, later ones from where the last answer stopped.
      expect(server.mergesSinceSeen.first, '0');
      expect(server.mergesSinceSeen.toSet(), containsAll(['0', '3', '6']));
    });

    test(
        'the merges go on after the songs are caught up (the two feeds have two cursors: nothing changed for the files, eight merges still to read)',
        () async {
      for (var i = 1; i <= 8; i++) {
        final from = 'sr_0000000000000000000000X$i';
        await song(from);
        await entry('pl_a', i, from);
        server.mergeRefs(from, 'sr_0000000000000000000000Y$i');
      }

      final stats = (await make(pageLimit: 3).pull()).getOrThrow();

      expect(stats.files, 0);
      expect(stats.merges, 8);
      expect(await state.get(EncoreSync.mergesCursor), '8');
      expect(await entriesOf('pl_a'),
          [for (var i = 1; i <= 8; i++) 'sr_0000000000000000000000Y$i']);
      expect(server.mergesSinceSeen, ['0', '3', '6']);
    });

    test('the second pull asks from the stored cursor and finds nothing to do',
        () async {
      final from = server.addRef('Song', 'Artist', fileId: 'nd-1');
      final into = server.addRef('Song', 'Artist', fileId: 'nd-1');
      await song(from);
      server.mergeRefs(from, into);
      final sync = make();
      await sync.pull();
      server.mergesSinceSeen.clear();

      final again = (await sync.pull()).getOrThrow();

      expect(again.merges, 0);
      expect(server.mergesSinceSeen, ['1']);
    });

    test(
        'a server from before merges (no merges in its answer) works as it always did and leaves no cursor behind',
        () async {
      server.hasMerges = false;
      server.addRef('Song', 'Artist', fileId: 'nd-1');

      final stats = (await make().pull()).getOrThrow();

      expect(stats.files, 1);
      expect(stats.merges, 0);
      expect(await state.get(EncoreSync.mergesCursor), isNull,
          reason: 'it never said where it was: nothing to remember');
      expect(await liveIds(), hasLength(1));
    });

    test(
        'a new account on this phone forgets the merges cursor with the others',
        () async {
      await state.set(EncoreSync.mergesCursor, '5');
      final sync = make();

      await sync.reset();

      expect(await state.get(EncoreSync.mergesCursor), isNull);
    });

    test(
        'a move of the download does not come back as a refresh: the survivor\'s page has another length, the phone does not download the song again',
        () async {
      final old = server.addRef('Echo', 'Ivy Jo', fileId: 'nd-1');
      final into =
          server.addRef('Echo', 'Ivy Jo', fileId: 'nd-1', durationMs: 207000);
      server.mergeRefs(old, into);
      await song(old, audioKey: 'key-from-the-old-length', durationSec: 200);
      await entry('pl_a', 0, old);
      await pin(old);
      await download(old, sourceKey: 'key-from-the-old-length');

      await make().pull();

      final row = await dl(into);
      expect(row, isNotNull);
      expect(row!.state, DownloadState.done);
      final live = await track(into);
      expect(row.sourceAudioKey, live!.audioKey);
      expect(live.audioKey, isNotEmpty);
      final repo = DownloadsRepository(db, serverId);
      final plan = planDownloads(
          desired: await repo.desired(),
          existing: await repo.existing(),
          nowMs: 1000,
          graceMs: 0);
      expect(plan.isEmpty, isTrue, reason: '$plan');
      expect(
          await LibraryWriter(db)
              .markStaleDownloads(serverId: serverId, nowMs: 1000),
          0);
    });
  });
}

/// Files that cannot be touched (a locked folder, a full disk).
class _FailingFiles implements MergedFiles {
  @override
  Future<bool> exists(String path) async => true;

  @override
  Future<void> rename(String from, String to) async =>
      throw const FileSystemException('locked');

  @override
  Future<void> delete(String path) async =>
      throw const FileSystemException('locked');
}
