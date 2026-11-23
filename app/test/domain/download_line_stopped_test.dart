import 'package:encore/domain/download_line.dart';
import 'package:flutter_test/flutter_test.dart';

/// N-39: the line of a download the person stopped, in the words drawn on 17 Nov 2026 (docs/design S-16 "stopped, files kept, Resume", "a stopped
/// list, the app opened again", "Stopping...", "a song interrupted from outside", S-17, S-96). One new word, "Stopped"; the phone's number stays first
/// and says what is kept.
void main() {
  ServerStage server({
    int total = 217,
    int ready = 40,
    int keeping = 1,
    int queued = 176,
    int failed = 0,
    int retryable = 0,
  }) =>
      ServerStage(
          total: total,
          ready: ready,
          keeping: keeping,
          queued: queued,
          failed: failed,
          retryable: retryable);

  DownloadFacts facts({
    int done = 12,
    int total = 217,
    int active = 205,
    int failed = 0,
    bool stopped = true,
    ServerStage? stage,
    PhoneWait? wait,
  }) =>
      DownloadFacts(
        phoneDone: done,
        phoneTotal: total,
        phoneActive: active,
        phoneFailed: failed,
        serverKeeps: true,
        stopped: stopped,
        server: stage,
        wait: wait,
      );

  group('the words of a stopped download', () {
    test(
        'N-39: the phone number first, then what the server has ready: "Stopped · 12 of 217 on this phone · 40 ready on your server"',
        () {
      final line = describeDownload(facts(stage: server()));
      expect(line.text,
          'Stopped · 12 of 217 on this phone · 40 ready on your server');
      expect(line.stopped, isTrue);
      expect(line.twoStages, isTrue);
      expect(line.complete, isFalse);
    });

    test(
        'N-39: nothing on the phone yet keeps its zero, and the server half goes on rising while it is stopped',
        () {
      final line = describeDownload(
          facts(done: 0, active: 217, stage: server(ready: 118, queued: 98)));
      expect(line.text,
          'Stopped · 0 of 217 on this phone · 118 ready on your server');
    });

    test(
        'N-39: when the server already has every song there is no server half, and it never reads "Stopped · Downloading to this phone"',
        () {
      final line = describeDownload(facts(
          total: 24,
          active: 12,
          stage: server(total: 24, ready: 24, keeping: 0, queued: 0)));
      expect(line.text, 'Stopped · 12 of 24 on this phone');
      expect(line.text, isNot(contains('Downloading')));
    });

    test(
        'N-39: with no server numbers (the app was just opened, the live channel is not up) there is no server half',
        () {
      expect(
          describeDownload(facts()).text, 'Stopped · 12 of 217 on this phone');
      expect(describeDownload(facts(done: 0)).text,
          'Stopped · 0 of 217 on this phone');
    });

    test(
        'N-39: stopped wins over a reason the phone cannot move: no "waiting for Wi-Fi", no server half (its numbers are stale)',
        () {
      for (final wait in PhoneWait.values) {
        final line = describeDownload(facts(stage: server(), wait: wait));
        expect(line.text, 'Stopped · 12 of 217 on this phone',
            reason: wait.name);
        expect(line.stopped, isTrue);
      }
    });

    test(
        'N-39: the songs that did not come are still counted in the line, named by the screen, and there is no Retry on a stopped row',
        () {
      final line = describeDownload(facts(
          done: 7,
          total: 10,
          active: 0,
          stage: server(
              total: 10,
              ready: 7,
              keeping: 0,
              queued: 0,
              failed: 3,
              retryable: 3)));
      expect(
          line.text, 'Stopped · 7 of 10 on this phone · 3 songs did not come');
      expect(line.failed, 3);
      expect(line.canRetry, isFalse,
          reason: 'Retry would send asks, which a stopped download does not');
      expect(line.canStop, isFalse);
      expect(line.stuck, isFalse);
    });

    test(
        'N-39: songs the PHONE could not take are counted on a stopped row too, with no Retry',
        () {
      final line = describeDownload(facts(failed: 2));
      expect(line.failed, 2);
      expect(line.canRetry, isFalse);
    });

    test(
        'N-39: a download that has every song is finished, whatever the stop says: no Stopped, no Resume',
        () {
      final line = describeDownload(
          facts(done: 24, total: 24, active: 0, stage: server(total: 24)));
      expect(line.text, 'Downloaded • 24 songs');
      expect(line.complete, isTrue);
      expect(line.stopped, isFalse);
      expect(line.canStop, isFalse);
    });

    test('N-39: a stopped download with no songs known yet says only "Stopped"',
        () {
      expect(describeDownload(facts(done: 0, total: 0, active: 0)).text,
          'Stopped');
    });

    test(
        'N-39: the bar of a stopped download keeps the numbers: the phone share and the server share',
        () {
      final line = describeDownload(
          facts(done: 50, total: 100, stage: server(total: 100, ready: 80)));
      expect(line.phoneFraction, 0.5);
      expect(line.serverFraction, 0.8);
    });
  });

  group('the Stop that stands where Retry stands', () {
    test(
        'N-39: it is offered while songs are coming: also while the phone waits, with nothing on the phone yet, and while the server rests',
        () {
      for (final f in [
        facts(stopped: false, stage: server()),
        facts(stopped: false, stage: server(), wait: PhoneWait.wifi),
        facts(stopped: false, done: 0, stage: server(ready: 118)),
        facts(stopped: false),
        DownloadFacts(
            phoneDone: 3,
            phoneTotal: 9,
            phoneActive: 6,
            serverKeeps: true,
            server: ServerStage(
                total: 9,
                ready: 3,
                keeping: 0,
                queued: 6,
                failed: 0,
                restingUntil: DateTime(2026, 11, 17, 21, 40))),
      ]) {
        final line = describeDownload(f);
        expect(line.canStop, isTrue, reason: line.text);
        expect(line.stopped, isFalse);
      }
    });

    test(
        'N-39: it is not offered on a finished download, on one that has only songs that did not come (it keeps its Retry), or on the line a plain music server has always had',
        () {
      final done = describeDownload(facts(
          stopped: false,
          done: 24,
          total: 24,
          active: 0,
          stage: server(total: 24)));
      expect(done.canStop, isFalse);

      final stuck = describeDownload(facts(
          stopped: false,
          done: 7,
          total: 10,
          active: 0,
          stage: server(
              total: 10,
              ready: 7,
              keeping: 0,
              queued: 0,
              failed: 3,
              retryable: 3)));
      expect(stuck.stuck, isTrue);
      expect(stuck.canStop, isFalse);
      expect(stuck.canRetry, isTrue);

      final legacy = describeDownload(const DownloadFacts(
          phoneDone: 3, phoneTotal: 9, phoneActive: 6, stopped: false));
      expect(legacy.twoStages, isFalse);
      expect(legacy.canStop, isFalse,
          reason:
              'the line of a plain music server has no Stop drawn (a question for the lead)');
    });

    test(
        'N-39: "Stopping…" is the quiet form of the moment after Stop: no button, no Retry, the bar where it was',
        () {
      final running = describeDownload(facts(stopped: false, stage: server()));
      final stopping = running.asStopping();
      expect(stopping.text, 'Stopping…');
      expect(stopping.canStop, isFalse);
      expect(stopping.canRetry, isFalse);
      expect(stopping.stopping, isTrue);
      expect(stopping.phoneFraction, running.phoneFraction);
      expect(stopping.serverFraction, running.serverFraction);
      expect(stopping.twoStages, isTrue);
    });
  });

  group('the reason of a song that something else interrupted', () {
    test(
        'N-39: what PR 113 records for a cancel from outside is told as "Interrupted before it finished.", by the constant, never as its own words',
        () {
      expect(kDownloadStoppedReason, 'The download was stopped',
          reason: 'what PR 113 records and what an older row may already say');
      expect(phoneFailureWords(kDownloadStoppedReason),
          'Interrupted before it finished.');
      expect(
          phoneFailureWords(kDownloadStoppedReason), isNot(contains('stopped')),
          reason: 'nobody who never pressed Stop reads it as their own act');
    });

    test('N-39: every other sentence stays as it was', () {
      expect(phoneFailureWords(null), 'Could not be saved on this phone.');
      expect(
          phoneFailureWords('HTTP 500'), 'Could not be saved on this phone.');
      expect(phoneFailureWords('Track is no longer on the server'),
          'The server no longer has this song.');
      expect(phoneFailureWords('ENOSPC'), 'There is no room on this phone.');
    });
  });
}
