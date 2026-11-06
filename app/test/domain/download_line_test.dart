import 'package:encore/domain/download_line.dart';
import 'package:flutter_test/flutter_test.dart';

/// The lines under a download's title (docs/design S-16 "the two stages", drawn 5 Nov 2026; P2-22 part 2, PB-34, PB-35, PB-37): one vocabulary for
/// the Library rows, the playlist and album headers and Settings > Downloads & storage. Both numbers, the phone's first.
void main() {
  // A server that keeps songs and told us how it goes.
  DownloadFacts withServer({
    int done = 0,
    int total = 217,
    int active = 0,
    int phoneFailed = 0,
    int ready = 0,
    int keeping = 0,
    int queued = 0,
    int failed = 0,
    int? serverTotal,
    PhoneWait? wait,
    DateTime? restingUntil,
    bool loaded = true,
  }) =>
      DownloadFacts(
        phoneDone: done,
        phoneTotal: total,
        phoneActive: active,
        phoneFailed: phoneFailed,
        serverKeeps: true,
        wait: wait,
        server: loaded
            ? ServerStage(
                total: serverTotal ?? total,
                ready: ready,
                keeping: keeping,
                queued: queued,
                failed: failed,
                retryable: failed,
                restingUntil: restingUntil)
            : null,
      );

  String line(DownloadFacts f) => describeDownload(f).text;

  group('the two stages (S-16): both numbers, the phone first', () {
    test('some of it on the phone, some ready on the server', () {
      final l = describeDownload(
          withServer(done: 12, active: 3, ready: 40, keeping: 1, queued: 176));

      expect(l.text, '12 of 217 on this phone · 40 ready on your server');
      expect(l.phoneFraction, closeTo(12 / 217, 1e-9));
      expect(l.serverFraction, closeTo(40 / 217, 1e-9),
          reason: 'the lighter tone of the bar: ready on the server');
    });

    test('nothing on the phone yet: the line starts with the server', () {
      expect(line(withServer(ready: 40, keeping: 1, queued: 176)),
          'Getting it on your server · 40 of 217 ready');
      expect(line(withServer(ready: 0, keeping: 1, queued: 216)),
          'Getting it on your server · 0 of 217 ready');
    });

    test('queued behind another download: nothing is being fetched for it', () {
      expect(line(withServer(ready: 0, keeping: 0, queued: 217)),
          'Waiting its turn on your server');
    });

    test('the server has all of it: the phone is the only stage left', () {
      expect(line(withServer(done: 30, total: 40, ready: 40, active: 10)),
          'Downloading to this phone · 30 of 40');
      expect(line(withServer(done: 0, total: 40, ready: 40, active: 5)),
          'Downloading to this phone · 0 of 40');
    });

    test(
        'YouTube holds the server back: the server half becomes its reason, with the time',
        () {
      final until = DateTime(2026, 11, 6, 21, 40);

      expect(
          line(withServer(
              done: 3, total: 9, ready: 3, queued: 6, restingUntil: until)),
          '3 of 9 on this phone · your server is resting until 21:40');
    });

    test('and with nothing on the phone yet the rest is said first', () {
      final until = DateTime(2026, 11, 6, 9, 5);

      expect(line(withServer(ready: 40, queued: 177, restingUntil: until)),
          'Your server is resting until 09:05 · 40 of 217 ready');
    });

    test(
        'a download the server has no answer for yet says only what the phone has',
        () {
      expect(
          line(withServer(done: 12, loaded: false)), '12 of 217 on this phone');
      expect(line(withServer(done: 0, loaded: false)),
          'Getting ready to download');
    });
  });

  group('the phone\'s reason wins (S-16 "waiting")', () {
    test(
        'three reasons, one cause for the whole screen, the server half is gone',
        () {
      for (final (wait, words) in [
        (PhoneWait.wifi, 'waiting for Wi-Fi'),
        (PhoneWait.connection, 'waiting for a connection'),
        (PhoneWait.server, 'waiting for your server'),
      ]) {
        final l = describeDownload(
            withServer(done: 12, total: 40, ready: 30, queued: 10, wait: wait));

        expect(l.text, '12 of 40 on this phone · $words');
        expect(l.serverFraction, l.phoneFraction,
            reason:
                'its counts are stale while the live channel is down: no tone for them');
      }
    });

    test('it replaces the resting reason too: one cause, the phone\'s', () {
      expect(
          line(withServer(
              done: 3,
              total: 9,
              ready: 3,
              queued: 6,
              wait: PhoneWait.connection,
              restingUntil: DateTime(2026, 11, 6, 21, 40))),
          '3 of 9 on this phone · waiting for a connection');
    });

    test('nothing on the phone yet still says why', () {
      expect(line(withServer(done: 0, total: 40, wait: PhoneWait.wifi)),
          '0 of 40 on this phone · waiting for Wi-Fi');
    });

    test('a finished download stays finished however the connection is', () {
      expect(
          line(withServer(
              done: 40, total: 40, ready: 40, wait: PhoneWait.connection)),
          'Downloaded • 40 songs');
    });
  });

  group('songs that did not come (PB-37)', () {
    test('named as a count, with Retry when asking again can help', () {
      final l =
          describeDownload(withServer(done: 0, total: 3, ready: 0, failed: 3));

      expect(l.text, '3 songs did not come');
      expect(l.failed, 3);
      expect(l.canRetry, isTrue);
    });

    test('one song is not "1 songs"', () {
      expect(line(withServer(done: 0, total: 1, ready: 0, failed: 1)),
          '1 song did not come');
    });

    test('the rest is fine and on the phone: both numbers, then the failures',
        () {
      final l =
          describeDownload(withServer(done: 7, total: 10, ready: 7, failed: 3));

      expect(l.text, '7 of 10 on this phone · 3 songs did not come');
    });

    test(
        'while other songs are still coming, the progress line stays and the count is carried apart',
        () {
      final l = describeDownload(
          withServer(done: 4, total: 10, ready: 5, queued: 3, failed: 2));

      expect(l.text, '4 of 10 on this phone · 5 ready on your server');
      expect(l.failed, 2,
          reason: 'the row shows it as its own line with Retry');
    });

    test('a song the server will never get is a failure but not a Retry', () {
      final f = DownloadFacts(
        phoneDone: 0,
        phoneTotal: 2,
        serverKeeps: true,
        server: const ServerStage(
            total: 2, ready: 0, keeping: 0, queued: 0, failed: 2, retryable: 0),
      );

      final l = describeDownload(f);

      expect(l.text, '2 songs did not come');
      expect(l.canRetry, isFalse);
    });

    test(
        'a file the phone could not take is a failure of the phone, counted with the others',
        () {
      expect(
          line(withServer(
              done: 5, total: 10, ready: 10, phoneFailed: 2, active: 0)),
          '5 of 10 on this phone · 2 songs did not come');
    });
  });

  group('the ends of it', () {
    test('everything on the phone', () {
      final l = describeDownload(withServer(done: 217, ready: 217));

      expect(l.text, 'Downloaded • 217 songs');
      expect(l.complete, isTrue);
      expect(l.phoneFraction, 1);
    });

    test('a playlist that holds no songs has nothing to wait for', () {
      expect(
          line(DownloadFacts(
              phoneDone: 0,
              phoneTotal: 0,
              confirmedEmpty: true,
              serverKeeps: true,
              server: const ServerStage(
                  total: 0, ready: 0, keeping: 0, queued: 0, failed: 0))),
          'Nothing to download yet');
    });

    test('songs that have not reached the phone yet are not "nothing"', () {
      expect(
          line(DownloadFacts(
              phoneDone: 0,
              phoneTotal: 0,
              serverKeeps: true,
              server: const ServerStage(
                  total: 9, ready: 0, keeping: 0, queued: 9, failed: 0))),
          'Waiting its turn on your server');
    });

    test(
        'the bar never goes backwards: the lighter tone is never shorter than the filled one',
        () {
      final l = describeDownload(withServer(done: 30, total: 40, ready: 10));

      expect(l.serverFraction, greaterThanOrEqualTo(l.phoneFraction));
    });
  });

  group(
      'a plain music server (no keep): exactly the lines the app has always had',
      () {
    DownloadFacts plain({
      int done = 0,
      int total = 10,
      int active = 0,
      int failed = 0,
      PhoneWait? wait,
      bool empty = false,
    }) =>
        DownloadFacts(
            phoneDone: done,
            phoneTotal: total,
            phoneActive: active,
            phoneFailed: failed,
            wait: wait,
            confirmedEmpty: empty);

    test('complete, downloading, waiting, attention, empty, preparing', () {
      expect(line(plain(done: 10)), 'Downloaded • 10 songs');
      expect(line(plain(done: 1, total: 1)), 'Downloaded • 1 song');
      expect(line(plain(done: 4, active: 3)), 'Downloading 4 of 10');
      expect(line(plain(done: 4, active: 3, wait: PhoneWait.wifi)),
          'Waiting for Wi-Fi • 4 of 10');
      expect(line(plain(done: 4, active: 3, wait: PhoneWait.connection)),
          'Waiting for a connection • 4 of 10');
      expect(line(plain(done: 4, failed: 2)),
          '4 of 10 downloaded • some did not come');
      expect(line(plain(total: 0, empty: true)), 'Nothing to download yet');
      expect(line(plain(total: 0)), 'Getting ready to download');
    });

    test(
        'a server that cannot be reached is not a reason a plain server ever gave',
        () {
      expect(line(plain(done: 4, active: 3, wait: PhoneWait.server)),
          'Downloading 4 of 10');
    });
  });
}
