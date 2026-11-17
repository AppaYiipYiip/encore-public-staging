import 'package:encore/data/encore/encore_models.dart';
import 'package:encore/data/repos/downloads_repository.dart';
import 'package:encore/domain/download_card.dart';
import 'package:encore/domain/download_line.dart';
import 'package:encore/features/downloads/download_card_jobs.dart';
import 'package:encore/features/downloads/download_line_providers.dart';
import 'package:encore/features/downloads/download_providers.dart';
import 'package:encore/features/downloads/keep_providers.dart';
import 'package:encore/features/import/import_watch.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';

/// docs/design S-95 (P2-29): which jobs the card follows and what each says. The line of a download is S-16's (`downloadLineProvider`), the numbers
/// are the phone's own table and the server's keep answer; an import comes from the import watch, and an import with the Download of the playlist it
/// made is ONE job.
class _Keep extends KeepController {
  _Keep(this.fixed);
  final KeepState fixed;

  @override
  KeepState build() => fixed;
}

class _Watch extends ImportWatch {
  _Watch(this.fixed);
  final ImportWatchState fixed;

  @override
  ImportWatchState build() => fixed;
}

EncoreImport _import(
  String id, {
  String state = 'running',
  int total = 217,
  int matched = 0,
  int unmatched = 0,
  int pending = 217,
  int kept = 0,
  String? playlistId = 'pl_import',
  String name = 'Prog snob',
  int createdAtMs = 0,
}) =>
    EncoreImport(
      id: id,
      name: name,
      source: 'youtube',
      state: state,
      total: total,
      matched: matched,
      unmatched: unmatched,
      pending: pending,
      kept: kept,
      playlistId: playlistId,
      createdAtMs: createdAtMs,
    );

KeepGroup _group(String kind, String id,
        {int total = 217,
        int ready = 0,
        int keeping = 0,
        int queued = 0,
        int failed = 0}) =>
    KeepGroup(
      kind: kind,
      id: id,
      total: total,
      ready: ready,
      keeping: keeping,
      queued: queued,
      failed: failed,
      retryable: failed,
      failures: const [],
    );

void main() {
  const playlist = DownloadTarget.pin(PinTargetType.playlist, 'pl_1');
  const target =
      CardTarget(target: playlist, name: 'Prog snob', playlistId: 'pl_1');

  ProviderContainer start({
    List<CardTarget> targets = const [target],
    DownloadLine? line,
    PinState phone = const PinState(pinned: true, total: 217, done: 12),
    KeepState keep = const KeepState(),
    ImportWatchState imports = const ImportWatchState(),
  }) {
    final c = ProviderContainer(overrides: <Override>[
      cardTargetsProvider.overrideWithValue(targets),
      downloadLineProvider.overrideWith((ref, t) => line),
      pinStateProvider.overrideWith((ref, arg) => Stream.value(phone)),
      keepProvider.overrideWith(() => _Keep(keep)),
      importWatchProvider.overrideWith(() => _Watch(imports)),
    ]);
    addTearDown(c.dispose);
    return c;
  }

  Future<List<CardJob>> jobs(ProviderContainer c) async {
    // The phone's own table arrives as a stream: one turn of the event loop.
    c.listen(downloadCardJobsProvider, (_, __) {});
    await Future<void>.delayed(const Duration(milliseconds: 5));
    return c.read(downloadCardJobsProvider);
  }

  KeepState keepWith(List<KeepGroup> groups, {DateTime? resting}) => KeepState(
        supported: true,
        answered: true,
        groups: {for (final g in groups) KeepGroupKey(g.kind, g.id): g},
        restingUntil: resting,
      );

  group('a download', () {
    test('says S-16\'s line and the numbers of both stages', () async {
      final c = start(
        line: const DownloadLine(
            '12 of 217 on this phone · 40 ready on your server',
            twoStages: true),
        keep: keepWith([_group('playlist', 'pl_1', ready: 40, queued: 177)]),
      );

      final job = (await jobs(c)).single;
      expect(job.key, 'pin:playlist:pl_1');
      expect(job.name, 'Prog snob');
      expect(job.text, '12 of 217 on this phone · 40 ready on your server');
      expect([job.songs, job.onPhone, job.ready], [217, 12, 40]);
      expect(job.phase, CardPhase.running);
      expect(job.saving, isTrue, reason: 'the server has songs on their way');
      expect(job.kind, CardJobKind.download);
      expect(job.progressDone, 52);
      expect(job.progressOf, 434);
    });

    test('is starting until somebody has said how far it is', () async {
      final c = start(
        line: const DownloadLine('Getting ready to download', starting: true),
        phone: const PinState(pinned: true),
      );

      final job = (await jobs(c)).single;
      expect(job.starting, isTrue);
      expect(job.phase, CardPhase.running);
    });

    test(
        'is over when every song is on the phone, and partly when some did not come',
        () async {
      final done = start(
        line: const DownloadLine('Downloaded • 217 songs', complete: true),
        phone: const PinState(pinned: true, total: 217, done: 217),
      );
      expect((await jobs(done)).single.phase, CardPhase.ready);

      final partly = start(
        line: const DownloadLine('x', stuck: true, failed: 3),
        phone: const PinState(pinned: true, total: 217, done: 214),
      );
      final job = (await jobs(partly)).single;
      expect(job.phase, CardPhase.partly);
      expect(job.failed, 3);
    });

    test('the server is saving only while it has songs on their way', () async {
      final idle = start(
        line: const DownloadLine('x', twoStages: true),
        keep: keepWith([_group('playlist', 'pl_1', ready: 217)]),
      );
      expect((await jobs(idle)).single.saving, isFalse);
    });

    test('on a plain music server there is no server stage to be saving',
        () async {
      final c = start(
        line: const DownloadLine('Downloading 12 of 217'),
      );

      final job = (await jobs(c)).single;
      expect(job.saving, isFalse);
      expect(job.ready, 12, reason: 'what is on the phone is all there is');
    });

    test(
        'a single song, a download that is not there and one with nothing in it are no card',
        () async {
      expect(
          await jobs(start(
            line: const DownloadLine('x'),
            phone: const PinState(pinned: true, total: 1, done: 0),
          )),
          isEmpty);
      expect(await jobs(start(line: null)), isEmpty);
      expect(
          await jobs(start(
            line: const DownloadLine('Nothing to download yet'),
            phone: const PinState(pinned: true, confirmedEmpty: true),
          )),
          isEmpty);
    });
  });

  group('an import', () {
    test(
        'with no Download: Importing, in the import page\'s words while it finds the songs',
        () async {
      final c = start(
        targets: const [],
        imports: ImportWatchState(imports: [
          _import('im_1', matched: 117, unmatched: 3, pending: 97),
        ]),
      );

      final job = (await jobs(c)).single;
      expect(job.key, 'pin:playlist:pl_import',
          reason:
              'the key of the playlist it made: the Download of that playlist is the same job');
      expect(job.kind, CardJobKind.import);
      expect(job.importing, isTrue);
      expect(job.text, 'Finding songs: 120 of 217');
      expect(job.phase, CardPhase.running);
      expect(job.saving, isTrue);
    });

    test(
        'once found, the server\'s stage in S-16\'s words (150 of the 214 found)',
        () async {
      final c = start(
        targets: const [],
        imports: ImportWatchState(imports: [
          _import('im_1',
              state: 'done', matched: 214, unmatched: 3, pending: 0, kept: 150),
        ], saving: const {
          'im_1'
        }),
      );

      final job = (await jobs(c)).single;
      expect(job.text, 'Getting it on your server · 150 of 214 ready');
      expect(job.serverTotal, 214);
      expect(job.ready, 150);
      expect(job.phase, CardPhase.running);
      expect(job.saving, isTrue);
    });

    test('YouTube resting is said as it is said on every screen', () async {
      final c = start(
        targets: const [],
        keep: keepWith(const [], resting: DateTime(2026, 11, 24, 21, 40)),
        imports: ImportWatchState(imports: [
          _import('im_1',
              state: 'done', matched: 214, unmatched: 3, pending: 0, kept: 150),
        ], saving: const {
          'im_1'
        }),
      );

      expect((await jobs(c)).single.text,
          'Your server is resting until 21:40 · 150 of 214 ready');
    });

    test('it is over when the server has kept every song it found', () async {
      final c = start(
        targets: const [],
        imports: ImportWatchState(imports: [
          _import('im_1',
              state: 'done', matched: 214, unmatched: 3, pending: 0, kept: 214),
        ]),
      );

      final job = (await jobs(c)).single;
      expect(job.phase, CardPhase.ready);
      expect(job.inLibrary, 214);
      expect(job.importRoute, '/library/playlist/pl_import');
    });

    test('stopped somewhere else says so; stopped on this phone says nothing',
        () async {
      final elsewhere = start(
        targets: const [],
        imports: ImportWatchState(imports: [
          _import('im_1', state: 'stopped', matched: 24, pending: 0),
        ]),
      );
      expect((await jobs(elsewhere)).single.phase, CardPhase.stopped);

      final here = start(
        targets: const [],
        imports: ImportWatchState(imports: [
          _import('im_1', state: 'stopped', matched: 24, pending: 0),
        ], stoppedHere: const {
          'im_1'
        }),
      );
      expect(await jobs(here), isEmpty);
    });

    test('a list of liked songs makes no playlist', () async {
      final c = start(
        targets: const [],
        imports: ImportWatchState(imports: [
          _import('im_1',
              playlistId: null,
              state: 'done',
              matched: 290,
              total: 300,
              pending: 0,
              kept: 290),
        ]),
      );

      final job = (await jobs(c)).single;
      expect(job.liked, isTrue);
      expect(job.importRoute, '/library/liked');
    });

    test(
        'a running import that has stopped moving is no job at all: no card, and no card of its end',
        () async {
      final c = start(
        targets: const [],
        imports: ImportWatchState(imports: [
          _import('im_1', matched: 117, unmatched: 3, pending: 97),
        ], stalled: const {
          'im_1'
        }),
      );

      expect(await jobs(c), isEmpty,
          reason:
              'not a job that is over (that would be a result card, "ready", which it is not): absent');
    });

    test(
        'a stalled import that made the playlist of a Download lends it nothing: the Download is a Download again, once',
        () async {
      final c = start(
        line: const DownloadLine('12 of 217 on this phone', twoStages: true),
        imports: ImportWatchState(imports: [
          _import('im_1', playlistId: 'pl_1', matched: 117, pending: 97),
        ], stalled: const {
          'im_1'
        }),
      );

      final job = (await jobs(c)).single;
      expect(job.kind, CardJobKind.download);
      expect(job.importing, isFalse);
      expect(job.text, '12 of 217 on this phone');
      expect(job.saving, isFalse,
          reason:
              'nothing says the server is still saving: no dated card outside the app for a stuck import');
    });

    test('a single song, a failed import and old history are no card',
        () async {
      final c = start(
        targets: const [],
        imports: ImportWatchState(imports: [
          _import('a', total: 1, pending: 1),
          _import('b', state: 'failed'),
          _import('c',
              state: 'done',
              matched: 5,
              total: 5,
              pending: 0,
              kept: 5,
              createdAtMs: DateTime(2026, 11, 1).millisecondsSinceEpoch),
        ]),
      );

      expect(await jobs(c), isEmpty);
    });

    test('an import and the Download of the playlist it made are ONE job',
        () async {
      final c = start(
        line: const DownloadLine(
            '12 of 217 on this phone · 40 ready on your server',
            twoStages: true),
        keep: keepWith([_group('playlist', 'pl_1', ready: 40, queued: 177)]),
        imports: ImportWatchState(imports: [
          _import('im_1', playlistId: 'pl_1', matched: 117, pending: 100),
        ]),
      );

      final found = await jobs(c);
      expect(found, hasLength(1));
      expect(found.single.key, 'pin:playlist:pl_1');
      expect(found.single.importing, isTrue);
      expect(found.single.text, 'Finding songs: 117 of 217',
          reason: 'the import\'s words first');

      final c2 = start(
        line: const DownloadLine(
            '12 of 217 on this phone · 40 ready on your server',
            twoStages: true),
        keep: keepWith([_group('playlist', 'pl_1', ready: 40, queued: 177)]),
        imports: ImportWatchState(imports: [
          _import('im_1',
              playlistId: 'pl_1',
              state: 'done',
              matched: 217,
              pending: 0,
              kept: 40),
        ]),
      );
      final after = (await jobs(c2)).single;
      expect(after.importing, isFalse);
      expect(after.text, '12 of 217 on this phone · 40 ready on your server');
    });
  });

  group('a Download the person stopped (N-39)', () {
    const stoppedLine = DownloadLine(
        'Stopped · 12 of 217 on this phone · 40 ready on your server',
        twoStages: true,
        stopped: true);

    test(
        "N-39: the job is over as a Download that waits: S-16's line, and it is not running",
        () async {
      final c = start(
        line: stoppedLine,
        phone:
            const PinState(pinned: true, total: 217, done: 12, stopped: true),
        keep: keepWith([_group('playlist', 'pl_1', ready: 40, queued: 177)]),
      );

      final job = (await jobs(c)).single;
      expect(job.phase, CardPhase.stopped);
      expect(job.running, isFalse);
      expect(job.kind, CardJobKind.download);
      expect(job.text, startsWith('Stopped · 12 of 217'));
      expect([job.songs, job.onPhone], [217, 12]);
      expect(job.starting, isFalse);
    });

    test(
        "N-39: a download that has every song is finished, whatever the Stop says",
        () async {
      final c = start(
        line: const DownloadLine('Downloaded • 217 songs', complete: true),
        phone:
            const PinState(pinned: true, total: 217, done: 217, stopped: true),
      );

      expect((await jobs(c)).single.phase, CardPhase.ready);
    });

    test(
        "N-39: an import and the Download of its playlist: Stop stops only the phone copy, so the import goes on as a job of its own with its own end",
        () async {
      final c = start(
        line: stoppedLine,
        phone:
            const PinState(pinned: true, total: 217, done: 12, stopped: true),
        keep: keepWith([_group('playlist', 'pl_1', ready: 40, queued: 177)]),
        imports: ImportWatchState(imports: [
          _import('im_1', playlistId: 'pl_1', matched: 117, pending: 100),
        ]),
      );

      final found = await jobs(c);
      expect(found, hasLength(2));
      final download = found.firstWhere((j) => j.kind == CardJobKind.download);
      final import = found.firstWhere((j) => j.kind == CardJobKind.import);
      expect(download.phase, CardPhase.stopped);
      expect(download.importing, isFalse,
          reason: 'the card is the download\'s: it never says Finding songs');
      expect(download.text, startsWith('Stopped'));
      expect(import.phase, CardPhase.running,
          reason: 'the import has its own Stop and goes on');
      expect(import.key, isNot(download.key),
          reason:
              'one key per job: the stopped download\'s card and the import\'s end are two cards, not one replaced by the other');
      expect(import.importing, isTrue);
    });

    test(
        "N-39: an import that is already over is no job beside the stopped download",
        () async {
      final c = start(
        line: stoppedLine,
        phone:
            const PinState(pinned: true, total: 217, done: 12, stopped: true),
        imports: ImportWatchState(imports: [
          _import('im_1',
              playlistId: 'pl_1',
              state: 'done',
              matched: 217,
              pending: 0,
              kept: 217),
        ]),
      );

      final found = await jobs(c);
      expect(found, hasLength(1));
      expect(found.single.kind, CardJobKind.download);
    });
  });

  group('a single song is no card, not even in its first second', () {
    const starting = DownloadLine('Getting ready to download', starting: true);

    test('a release of one song, a playlist of one song', () async {
      final c = start(
        targets: const [
          CardTarget(
            target: DownloadTarget.release('cat:1', ['sr_1']),
            name: 'A single',
            knownSongs: 1,
          ),
          CardTarget(
            target: DownloadTarget.pin(PinTargetType.playlist, 'pl_one'),
            name: 'One song',
            playlistId: 'pl_one',
            knownSongs: 1,
          ),
        ],
        line: starting,
        phone: const PinState(pinned: true),
      );

      expect(await jobs(c), isEmpty);
    });

    test('a download whose size nobody knows yet still starts at once',
        () async {
      final c = start(line: starting, phone: const PinState(pinned: true));

      expect((await jobs(c)).single.starting, isTrue);
    });
  });

  test(
      'an import and the Download of its playlist are the same key, whichever comes first',
      () async {
    final imports = ImportWatchState(imports: [
      _import('im_1', playlistId: 'pl_1', matched: 117, pending: 100),
    ]);

    final importOnly = await jobs(start(targets: const [], imports: imports));
    final both = await jobs(start(
      line: const DownloadLine('12 of 217 on this phone', twoStages: true),
      imports: imports,
    ));

    expect(importOnly.single.key, both.single.key);
  });

  test('a download and an import side by side are two jobs', () async {
    final c = start(
      line: const DownloadLine('12 of 217 on this phone', twoStages: true),
      imports: ImportWatchState(imports: [
        _import('im_2', playlistId: 'pl_other', matched: 5, pending: 100),
      ]),
    );

    final found = await jobs(c);
    expect({for (final j in found) j.key},
        {'pin:playlist:pl_1', 'pin:playlist:pl_other'},
        reason:
            'an import of a playlist is keyed by that playlist, so a Download of it later is the same job');
  });

  test("an import of the liked songs makes no playlist: it is a job of its own",
      () async {
    final c = start(
      targets: const [],
      imports: ImportWatchState(imports: [
        _import('im_3', playlistId: null, matched: 5, pending: 100),
      ]),
    );

    final found = await jobs(c);
    expect(found.single.key, 'import:im_3');
    expect(found.single.liked, isTrue);
  });
}
