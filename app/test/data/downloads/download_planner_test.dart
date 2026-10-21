import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/downloads/download_planner.dart';
import 'package:flutter_test/flutter_test.dart';

const _hour = 60 * 60 * 1000;

DownloadRow row(
  String id, {
  int state = DownloadState.done,
  bool stale = false,
  String sourceAudioKey = 'k1',
  int updatedAtMs = 0,
  int? orphanedAtMs,
  int attempts = 0,
}) =>
    DownloadRow(
      serverId: 1,
      trackId: id,
      state: state,
      localPath: state == DownloadState.done ? '/data/$id.opus' : null,
      bytes: 100,
      expectedBytes: 100,
      quality: 'opus160',
      sourceAudioKey: sourceAudioKey,
      stale: stale,
      lastError: null,
      updatedAtMs: updatedAtMs,
      orphanedAtMs: orphanedAtMs,
      attempts: attempts,
    );

DesiredDownload want(String id, {String audioKey = 'k1'}) =>
    DesiredDownload(trackId: id, quality: 'opus160', audioKey: audioKey);

void main() {
  const now = 100 * _hour;

  test('a pinned track with no row is queued', () {
    final plan = planDownloads(
      desired: {'a': want('a')},
      existing: {},
      nowMs: now,
    );
    expect(plan.toQueue, ['a']);
    expect(plan.toDelete, isEmpty);
  });

  test('a healthy downloaded track needs nothing', () {
    final plan = planDownloads(
      desired: {'a': want('a')},
      existing: {'a': row('a')},
      nowMs: now,
    );
    expect(plan.isEmpty, isTrue);
  });

  test('server changed the audio: the copy is refreshed', () {
    final plan = planDownloads(
      desired: {'a': want('a', audioKey: 'k2')},
      existing: {'a': row('a', sourceAudioKey: 'k1')},
      nowMs: now,
    );
    expect(plan.toRefresh, ['a']);
    expect(plan.toQueue, isEmpty);
  });

  test('a tag-only change (same audio key) does not re-download', () {
    final plan = planDownloads(
      desired: {'a': want('a', audioKey: 'k1')},
      existing: {'a': row('a', sourceAudioKey: 'k1')},
      nowMs: now,
    );
    expect(plan.isEmpty, isTrue);
  });

  test('unknown audio key on either side never triggers a refresh', () {
    final plan = planDownloads(
      desired: {'a': want('a', audioKey: ''), 'b': want('b', audioKey: 'k2')},
      existing: {
        'a': row('a', sourceAudioKey: 'k1'),
        'b': row('b', sourceAudioKey: ''),
      },
      nowMs: now,
    );
    expect(plan.toRefresh, isEmpty);
  });

  test('rows flagged stale are refreshed', () {
    final plan = planDownloads(
      desired: {'a': want('a')},
      existing: {'a': row('a', stale: true)},
      nowMs: now,
    );
    expect(plan.toRefresh, ['a']);
  });

  group('failed downloads back off', () {
    test('not retried before the back-off elapsed', () {
      final plan = planDownloads(
        desired: {'a': want('a')},
        existing: {
          'a': row('a',
              state: DownloadState.failed,
              attempts: 0,
              updatedAtMs: now - 60000)
        },
        nowMs: now,
      );
      expect(plan.toQueue, isEmpty);
    });

    test('retried once the back-off elapsed', () {
      final plan = planDownloads(
        desired: {'a': want('a')},
        existing: {
          'a': row('a',
              state: DownloadState.failed,
              attempts: 0,
              updatedAtMs: now - 6 * 60 * 1000)
        },
        nowMs: now,
      );
      expect(plan.toQueue, ['a']);
    });

    test('back-off doubles per attempt and is capped at 6 hours', () {
      // attempts 3 => 40 min wait
      final soon = planDownloads(
        desired: {'a': want('a')},
        existing: {
          'a': row('a',
              state: DownloadState.failed,
              attempts: 3,
              updatedAtMs: now - 30 * 60 * 1000)
        },
        nowMs: now,
      );
      expect(soon.toQueue, isEmpty);

      final later = planDownloads(
        desired: {'a': want('a')},
        existing: {
          'a': row('a',
              state: DownloadState.failed,
              attempts: 3,
              updatedAtMs: now - 41 * 60 * 1000)
        },
        nowMs: now,
      );
      expect(later.toQueue, ['a']);

      // attempts 30 => capped at 6 h, not 5 min * 2^30
      final capped = planDownloads(
        desired: {'a': want('a')},
        existing: {
          'a': row('a',
              state: DownloadState.failed,
              attempts: 30,
              updatedAtMs: now - 6 * _hour - 1)
        },
        nowMs: now,
      );
      expect(capped.toQueue, ['a']);
    });
  });

  test('queued and in-flight rows are left alone', () {
    final plan = planDownloads(
      desired: {'a': want('a'), 'b': want('b')},
      existing: {
        'a': row('a', state: DownloadState.queued),
        'b': row('b', state: DownloadState.downloading),
      },
      nowMs: now,
    );
    expect(plan.isEmpty, isTrue);
  });

  group('tracks that lost their pin', () {
    test('start a grace period first', () {
      final plan = planDownloads(
        desired: {},
        existing: {'a': row('a')},
        nowMs: now,
      );
      expect(plan.toOrphan, ['a']);
      expect(plan.toDelete, isEmpty);
    });

    test('are kept while the grace period runs', () {
      final plan = planDownloads(
        desired: {},
        existing: {'a': row('a', orphanedAtMs: now - 2 * _hour)},
        nowMs: now,
      );
      expect(plan.isEmpty, isTrue);
    });

    test('are deleted after the grace period', () {
      final plan = planDownloads(
        desired: {},
        existing: {'a': row('a', orphanedAtMs: now - 25 * _hour)},
        nowMs: now,
      );
      expect(plan.toDelete, ['a']);
    });

    test('come back if a smart playlist picks them up again', () {
      final plan = planDownloads(
        desired: {'a': want('a')},
        existing: {'a': row('a', orphanedAtMs: now - 2 * _hour)},
        nowMs: now,
      );
      expect(plan.toRescue, ['a']);
      expect(plan.toDelete, isEmpty);
    });

    test('an explicit removal (grace 0) deletes immediately', () {
      final plan = planDownloads(
        desired: {'keep': want('keep')},
        existing: {'keep': row('keep'), 'gone': row('gone')},
        nowMs: now,
        graceMs: 0,
      );
      expect(plan.toDelete, ['gone']);
      expect(plan.toOrphan, isEmpty);
    });

    test('a half-finished download of an unpinned track is deleted too', () {
      final plan = planDownloads(
        desired: {},
        existing: {'a': row('a', state: DownloadState.downloading)},
        nowMs: now,
        graceMs: 0,
      );
      expect(plan.toDelete, ['a']);
    });
  });

  test('a big smart-playlist regeneration is a minimal diff', () {
    final desired = {
      for (var i = 0; i < 800; i++) 't$i': want('t$i'),
    };
    final existing = {
      // 700 songs stay, 100 are replaced by new ones
      for (var i = 100; i < 900; i++) 't$i': row('t$i'),
    };
    // desired = 0..799, existing = 100..899
    final plan =
        planDownloads(desired: desired, existing: existing, nowMs: now);
    expect(plan.toQueue.length, 100, reason: 't0..t99 are new');
    expect(plan.toOrphan.length, 100, reason: 't800..t899 dropped');
    expect(plan.toDelete, isEmpty, reason: 'grace period protects churn');
    expect(plan.toRefresh, isEmpty);
  });
}
