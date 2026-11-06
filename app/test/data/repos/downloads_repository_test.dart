import 'package:drift/drift.dart' show Value;
import 'package:drift/native.dart';
import 'package:encore/core/clock.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/downloads/download_planner.dart';
import 'package:encore/data/repos/downloads_repository.dart';
import 'package:encore/domain/audio_quality.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  late AppDatabase db;
  late FakeClock clock;
  late DownloadsRepository repo;
  late int serverId;

  setUp(() async {
    db = AppDatabase(NativeDatabase.memory());
    clock = FakeClock(DateTime.utc(2026, 10, 14, 12));
    serverId = await db.into(db.servers).insert(ServersCompanion.insert(
          name: 'T',
          username: 'u',
          endpointsJson: '[]',
          createdAtMs: 0,
        ));
    repo = DownloadsRepository(db, serverId, clock: clock);

    Future<void> track(String id, String albumId, {int? starred}) =>
        db.into(db.tracks).insert(TracksCompanion.insert(
              serverId: serverId,
              id: id,
              title: 'Song $id',
              albumId: Value(albumId),
              artistId: const Value('ar1'),
              starredAtMs: Value(starred),
              audioKey: Value('key-$id'),
            ));
    await track('a1', 'alb1', starred: 5);
    await track('a2', 'alb1');
    await track('a3', 'alb1');
    await track('b1', 'alb2', starred: 7);
    await track('b2', 'alb2');

    await db.into(db.playlists).insert(
        PlaylistsCompanion.insert(serverId: serverId, id: 'pl1', name: 'Mix'));
    for (var i = 0; i < 3; i++) {
      await db.into(db.playlistEntries).insert(PlaylistEntriesCompanion.insert(
            serverId: serverId,
            playlistId: 'pl1',
            position: i,
            trackId: ['a1', 'b1', 'b2'][i],
          ));
    }
  });

  tearDown(() => db.close());

  Future<void> setDownload(String id, int state,
      {int bytes = 1000, bool stale = false}) async {
    await db.into(db.downloads).insertOnConflictUpdate(
          DownloadsCompanion.insert(
            serverId: serverId,
            trackId: id,
            state: Value(state),
            bytes: Value(bytes),
            stale: Value(stale),
            localPath: Value(state == DownloadState.done ? '/d/$id' : null),
            updatedAtMs: clock.now().millisecondsSinceEpoch,
          ),
        );
  }

  group('pin state', () {
    test('is off until the user pins', () async {
      final s = await repo.watchPinState(PinTargetType.album, 'alb1').first;
      expect(s.phase, PinPhase.off);
      expect(s.total, 3);
    });

    test('pinning an album with nothing downloaded is "preparing"', () async {
      await repo.pin(PinTargetType.album, 'alb1');
      final s = await repo.watchPinState(PinTargetType.album, 'alb1').first;
      expect(s.pinned, isTrue);
      expect(s.phase, PinPhase.preparing);
    });

    test(
        'an empty playlist, once pinned, has nothing to download: it is not "preparing" for ever (Q1)',
        () async {
      await db.into(db.playlists).insert(PlaylistsCompanion.insert(
          serverId: serverId, id: 'plEmpty', name: 'Blank'));
      await repo.pin(PinTargetType.playlist, 'plEmpty');
      final s =
          await repo.watchPinState(PinTargetType.playlist, 'plEmpty').first;
      expect(s.pinned, isTrue);
      expect(s.total, 0);
      expect(s.phase, isNot(PinPhase.preparing),
          reason: 'an arrow that spins at 0 % for ever promises a download '
              'that cannot happen');
      expect(s.phase.name, 'empty');
    });

    test(
        'an album pinned before its songs reached the phone is "preparing", not "nothing to download" (code review: only a playlist can be confirmed empty)',
        () async {
      await repo.pin(PinTargetType.album, 'alb-not-synced-yet');
      final s = await repo
          .watchPinState(PinTargetType.album, 'alb-not-synced-yet')
          .first;

      expect(s.confirmedEmpty, isFalse);
      expect(s.phase, PinPhase.preparing);
    });

    test(
        'a pinned song whose row has not reached the phone yet is still "preparing" (it is on its way, not absent)',
        () async {
      await repo.pin(PinTargetType.track, 'not-synced-yet');
      final s =
          await repo.watchPinState(PinTargetType.track, 'not-synced-yet').first;
      expect(s.pinned, isTrue);
      expect(s.phase, PinPhase.preparing);
    });

    test(
        'a playlist the server says has songs, with no entries on this phone yet, is "preparing" and not "nothing to download" (Q1)',
        () async {
      await db.into(db.playlists).insert(PlaylistsCompanion.insert(
          serverId: serverId,
          id: 'plLate',
          name: 'Forty songs',
          songCount: const Value(5)));
      await repo.pin(PinTargetType.playlist, 'plLate');
      final s =
          await repo.watchPinState(PinTargetType.playlist, 'plLate').first;
      expect(s.total, 0);
      expect(s.phase, PinPhase.preparing);
    });

    test('progress follows the downloads table', () async {
      await repo.pin(PinTargetType.album, 'alb1');
      await setDownload('a1', DownloadState.done);
      await setDownload('a2', DownloadState.downloading);
      await setDownload('a3', DownloadState.queued);
      final s = await repo.watchPinState(PinTargetType.album, 'alb1').first;
      expect(s.phase, PinPhase.downloading);
      expect(s.done, 1);
      expect(s.active, 2);
      expect(s.progress, closeTo(1 / 3, 1e-9));
      expect(s.bytes, 1000);
    });

    test('complete when every member is downloaded', () async {
      await repo.pin(PinTargetType.album, 'alb1');
      for (final id in ['a1', 'a2', 'a3']) {
        await setDownload(id, DownloadState.done);
      }
      final s = await repo.watchPinState(PinTargetType.album, 'alb1').first;
      expect(s.phase, PinPhase.complete);
    });

    test('a stale copy does not count as done', () async {
      await repo.pin(PinTargetType.album, 'alb1');
      for (final id in ['a1', 'a2']) {
        await setDownload(id, DownloadState.done);
      }
      await setDownload('a3', DownloadState.done, stale: true);
      final s = await repo.watchPinState(PinTargetType.album, 'alb1').first;
      expect(s.done, 2);
      expect(s.phase, isNot(PinPhase.complete));
    });

    test('needs attention when only failures remain', () async {
      await repo.pin(PinTargetType.album, 'alb1');
      await setDownload('a1', DownloadState.done);
      await setDownload('a2', DownloadState.done);
      await setDownload('a3', DownloadState.failed);
      final s = await repo.watchPinState(PinTargetType.album, 'alb1').first;
      expect(s.phase, PinPhase.attention);
    });

    test('playlist members come from playlist entries', () async {
      await repo.pin(PinTargetType.playlist, 'pl1');
      final s = await repo.watchPinState(PinTargetType.playlist, 'pl1').first;
      expect(s.total, 3);
    });

    test('liked songs follow the starred flag', () async {
      await repo.pin(PinTargetType.liked, 'ignored');
      var s = await repo.watchPinState(PinTargetType.liked, 'x').first;
      expect(s.pinned, isTrue);
      expect(s.total, 2);

      await (db.update(db.tracks)..where((t) => t.id.equals('a2')))
          .write(const TracksCompanion(starredAtMs: Value(9)));
      s = await repo.watchPinState(PinTargetType.liked, 'x').first;
      expect(s.total, 3);
    });

    test('the stream re-emits when a download finishes', () async {
      await repo.pin(PinTargetType.album, 'alb2');
      final states = <PinPhase>[];
      final sub = repo
          .watchPinState(PinTargetType.album, 'alb2')
          .listen((s) => states.add(s.phase));
      await Future<void>.delayed(const Duration(milliseconds: 20));
      await setDownload('b1', DownloadState.done);
      await Future<void>.delayed(const Duration(milliseconds: 20));
      await setDownload('b2', DownloadState.done);
      await Future<void>.delayed(const Duration(milliseconds: 20));
      await sub.cancel();
      expect(states.last, PinPhase.complete);
      expect(states, contains(PinPhase.downloading));
    });

    test('unpinning turns the toggle off again', () async {
      await repo.pin(PinTargetType.album, 'alb1');
      await repo.unpin(PinTargetType.album, 'alb1');
      final s = await repo.watchPinState(PinTargetType.album, 'alb1').first;
      expect(s.phase, PinPhase.off);
    });
  });

  group('desired set', () {
    test('is the union of all pins, deduplicated', () async {
      await repo.pin(PinTargetType.album, 'alb2'); // b1 b2
      await repo.pin(PinTargetType.playlist, 'pl1'); // a1 b1 b2
      final d = await repo.desired();
      expect(d.keys.toSet(), {'a1', 'b1', 'b2'});
    });

    test('a track pinned twice keeps the best quality', () async {
      await repo.pin(PinTargetType.album, 'alb2', quality: AudioQuality.normal);
      await repo.pin(PinTargetType.playlist, 'pl1', quality: AudioQuality.high);
      final d = await repo.desired();
      expect(d['b1']!.quality, AudioQuality.high.id);
      expect(d['a1']!.quality, AudioQuality.high.id);
    });

    test('carries the current audio key for staleness checks', () async {
      await repo.pin(PinTargetType.album, 'alb2');
      final d = await repo.desired();
      expect(d['b1']!.audioKey, 'key-b1');
    });

    test('skips tracks the server removed or reports missing', () async {
      await (db.update(db.tracks)..where((t) => t.id.equals('b1')))
          .write(const TracksCompanion(deletedAtMs: Value(1)));
      await (db.update(db.tracks)..where((t) => t.id.equals('b2')))
          .write(const TracksCompanion(missing: Value(true)));
      await repo.pin(PinTargetType.album, 'alb2');
      expect(await repo.desired(), isEmpty);
    });
  });

  group('applying a plan', () {
    test('queues new tracks', () async {
      await repo.pin(PinTargetType.album, 'alb2');
      final desired = await repo.desired();
      final plan = planDownloads(
        desired: desired,
        existing: await repo.existing(),
        nowMs: clock.now().millisecondsSinceEpoch,
      );
      await repo.applyPlan(plan, desired);

      final rows = await repo.existing();
      expect(rows.keys.toSet(), {'b1', 'b2'});
      expect(rows['b1']!.state, DownloadState.queued);
    });

    test('orphaning then rescuing round-trips', () async {
      await setDownload('a1', DownloadState.done);
      final now = clock.now().millisecondsSinceEpoch;

      var plan = planDownloads(
          desired: {}, existing: await repo.existing(), nowMs: now);
      await repo.applyPlan(plan, {});
      expect((await repo.existing())['a1']!.orphanedAtMs, now);

      await repo.pin(PinTargetType.album, 'alb1');
      final desired = await repo.desired();
      plan = planDownloads(
          desired: desired, existing: await repo.existing(), nowMs: now);
      expect(plan.toRescue, ['a1']);
      await repo.applyPlan(plan, desired);
      expect((await repo.existing())['a1']!.orphanedAtMs, isNull);
    });

    test('refresh keeps the old file until the new one lands', () async {
      await setDownload('a1', DownloadState.done);
      await repo.applyPlan(
        const DownloadPlan(toRefresh: ['a1']),
        {'a1': const DesiredDownload(trackId: 'a1', quality: 'original')},
      );
      final row = (await repo.existing())['a1']!;
      expect(row.state, DownloadState.queued);
      expect(row.localPath, '/d/a1', reason: 'file still playable');
    });

    test('markDone / markFailed record outcome and retry counter', () async {
      await setDownload('a1', DownloadState.queued);
      await repo.markFailed('a1', 'timeout');
      await repo.markFailed('a1', 'timeout');
      var row = (await repo.existing())['a1']!;
      expect(row.state, DownloadState.failed);
      expect(row.attempts, 2);
      expect(row.lastError, 'timeout');

      await repo.markDone('a1',
          localPath: '/d/a1.opus',
          bytes: 4242,
          audioKey: 'key-a1',
          quality: 'opus160');
      row = (await repo.existing())['a1']!;
      expect(row.state, DownloadState.done);
      expect(row.attempts, 0);
      expect(row.lastError, isNull);
      expect(row.bytes, 4242);
    });
  });

  group('read side', () {
    test('storage summary counts finished files only', () async {
      await setDownload('a1', DownloadState.done, bytes: 1000);
      await setDownload('a2', DownloadState.done, bytes: 2500);
      await setDownload('a3', DownloadState.queued, bytes: 0);
      final s = await repo.watchStorage().first;
      expect(s.tracks, 2);
      expect(s.bytes, 3500);
    });

    test('downloaded tracks join the catalogue', () async {
      await setDownload('b2', DownloadState.done);
      final tracks = await repo.watchDownloadedTracks().first;
      expect(tracks.map((t) => t.id), ['b2']);
    });

    test('local path is only offered for finished downloads', () async {
      await setDownload('a1', DownloadState.done);
      await setDownload('a2', DownloadState.downloading);
      expect(await repo.localPathFor('a1'), '/d/a1');
      expect(await repo.localPathFor('a2'), isNull);
      expect(await repo.localPathFor('nope'), isNull);
    });
  });

  group('the songs the phone could not take', () {
    Future<void> failed(String id, String error) =>
        db.into(db.downloads).insertOnConflictUpdate(DownloadsCompanion.insert(
              serverId: serverId,
              trackId: id,
              state: const Value(DownloadState.failed),
              lastError: Value(error),
              updatedAtMs: clock.now().millisecondsSinceEpoch,
            ));

    test('are named for a playlist, with the error the manager recorded',
        () async {
      await failed('b1', 'SocketException: reset');
      await failed('a2', 'not in the playlist, so not listed');

      final songs = await repo
          .watchFailedSongs(PinTargetType.playlist, 'pl1')
          .firstWhere((l) => l.isNotEmpty);

      expect(songs.map((f) => f.title), ['Song b1']);
      expect(songs.single.error, 'SocketException: reset');
    });

    test('are named for a list of songs (a catalogue release)', () async {
      await failed('a1', 'x');
      await failed('b2', 'y');

      final songs = await repo
          .watchFailedSongsIn(['a1', 'a2']).firstWhere((l) => l.isNotEmpty);

      expect(songs.map((f) => f.ref), ['a1']);
    });

    test('and a song that is fine is not listed', () async {
      await setDownload('b1', DownloadState.done);

      final songs =
          await repo.watchFailedSongs(PinTargetType.playlist, 'pl1').first;

      expect(songs, isEmpty);
    });
  });
}
