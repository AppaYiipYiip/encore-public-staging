import 'package:encore/domain/download_card.dart';
import 'package:encore/domain/download_card_words.dart';
import 'package:flutter_test/flutter_test.dart';

/// docs/design S-95 "Download notification" (P2-29): the words and numbers of the one card, state by state, pinned to what the drawing says. The
/// phone's line is S-16's own line (it arrives here as text from `describeDownload`), so no second phrasing exists.
void main() {
  const words = DownloadCardWords();

  CardJob download(
    String key,
    String name,
    String text, {
    int songs = 217,
    int onPhone = 12,
    int ready = 40,
    bool starting = false,
    bool saving = true,
    CardPhase phase = CardPhase.running,
    int failed = 0,
    bool importing = false,
  }) =>
      CardJob(
        key: key,
        name: name,
        text: text,
        songs: songs,
        onPhone: onPhone,
        ready: ready,
        starting: starting,
        saving: saving,
        phase: phase,
        failed: failed,
        importing: importing,
        progressDone:
            downloadBar(songs: songs, onPhone: onPhone, ready: ready).done,
        progressOf:
            downloadBar(songs: songs, onPhone: onPhone, ready: ready).of,
      );

  group('the bar is the share of the whole job', () {
    test('a song on the phone and a song ready on the server count the same',
        () {
      // 12 on the phone + 40 ready of 217: (12 + 40) / (2 x 217) = 12 %, the bar of the drawing.
      final bar = downloadBar(songs: 217, onPhone: 12, ready: 40);
      expect(bar.done / bar.of, closeTo(0.12, 0.005));
    });

    test('it is full only when every song is on the phone', () {
      final all = downloadBar(songs: 10, onPhone: 10, ready: 10);
      expect(all.done, all.of);
      final serverOnly = downloadBar(songs: 10, onPhone: 0, ready: 10);
      expect(serverOnly.done / serverOnly.of, 0.5);
    });

    test('a song on the phone is always counted as ready on the server', () {
      // The server's numbers may be older than the phone's own table: never less than what the phone holds.
      final bar = downloadBar(songs: 10, onPhone: 6, ready: 2);
      expect(bar.done, 12);
    });

    test('an import has one stage: found and kept, not-found ones need none',
        () {
      final bar = importBar(total: 217, matched: 150, unmatched: 3, kept: 100);
      // looked 153 + kept 100 + unmatched 3 (nothing to keep) of 434.
      expect(bar.done, 256);
      expect(bar.of, 434);
      final over = importBar(total: 10, matched: 8, unmatched: 2, kept: 8);
      expect(over.done, over.of);
    });
  });

  /// The bar of the card is the share of EVERYTHING the card has followed since it started, and it only moves forward for as long as the card lives:
  /// a job that ends keeps its share in the total, a job that joins does not pull it back, and a new card starts from zero.
  group('the bar of the card only moves forward while the card lives', () {
    CardJob job(
      String key, {
      required int onPhone,
      int? ready,
      int songs = 10,
      CardPhase phase = CardPhase.running,
      bool starting = false,
    }) =>
        download(key, key, 'x',
            songs: songs,
            onPhone: onPhone,
            ready: ready ?? onPhone,
            phase: phase,
            starting: starting);

    test('a bar that is told a smaller share keeps what it showed', () {
      final bar = CardBar();
      expect(bar.apply([job('a', onPhone: 4)]), closeTo(0.40, 1e-9));
      expect(bar.apply([job('a', onPhone: 2)]), closeTo(0.40, 1e-9),
          reason: 'a retry, or numbers a little older: no step back');
      expect(bar.apply([job('a', onPhone: 6)]), closeTo(0.60, 1e-9));
    });

    test(
        "one of two jobs ends: its share stays in the total, the bar does not drop to the other one's own share",
        () {
      final bar = CardBar();
      // A is all on the phone (100 %), B is at 10 %: (20 + 2) / 40 = 55 %.
      final before = bar.apply([
        job('a', onPhone: 10),
        job('b', onPhone: 1, ready: 1),
      ]);
      expect(before, closeTo(0.55, 1e-9));

      // A ends. The share of B alone is 10 %: the bar must not say so.
      final after = bar.apply([
        job('a', onPhone: 10, phase: CardPhase.ready),
        job('b', onPhone: 1, ready: 1),
      ]);

      expect(after, closeTo(0.55, 1e-9));
    });

    test('a finished job that then leaves the list keeps its share too', () {
      final bar = CardBar();
      bar.apply([job('a', onPhone: 10), job('b', onPhone: 1)]);

      // The person removed A (or the list no longer has it): the bar does not drop, and what A was worth is still in the whole.
      expect(bar.apply([job('b', onPhone: 2)]), greaterThanOrEqualTo(0.55));
      expect(bar.apply([job('b', onPhone: 8)]), closeTo(0.90, 1e-9),
          reason:
              '(20 + 16) / 40: Beta moves the bar of the whole, not its own');
    });

    test(
        'two jobs end, in either order: the bar never goes down, then the card is over',
        () {
      for (final firstToEnd in ['a', 'b']) {
        final bar = CardBar();
        final seen = <double>[];
        CardJob a(CardPhase p, int onPhone) =>
            job('a', onPhone: onPhone, phase: p);
        CardJob b(CardPhase p, int onPhone) =>
            job('b', onPhone: onPhone, phase: p);
        seen.add(bar.apply([a(CardPhase.running, 6), b(CardPhase.running, 2)]));
        if (firstToEnd == 'a') {
          seen.add(
              bar.apply([a(CardPhase.ready, 10), b(CardPhase.running, 3)]));
          seen.add(
              bar.apply([a(CardPhase.ready, 10), b(CardPhase.running, 7)]));
          seen.add(bar.apply([a(CardPhase.ready, 10), b(CardPhase.ready, 10)]));
        } else {
          seen.add(
              bar.apply([a(CardPhase.running, 7), b(CardPhase.ready, 10)]));
          seen.add(
              bar.apply([a(CardPhase.running, 9), b(CardPhase.ready, 10)]));
          seen.add(bar.apply([a(CardPhase.ready, 10), b(CardPhase.ready, 10)]));
        }

        expect(seen.removeLast(), 0,
            reason: 'nothing runs any more: the card is over, there is no bar');
        for (var i = 1; i < seen.length; i++) {
          expect(seen[i], greaterThanOrEqualTo(seen[i - 1]),
              reason: '$firstToEnd ended first, step $i: $seen');
        }
      }
    });

    test(
        'a job joins: the bar does not drop, and moves again once the bigger whole passes it',
        () {
      final bar = CardBar();
      expect(bar.apply([job('a', onPhone: 8)]), closeTo(0.80, 1e-9));

      final joined =
          bar.apply([job('a', onPhone: 8), job('b', onPhone: 0, ready: 0)]);
      expect(joined, closeTo(0.80, 1e-9), reason: 'the raw share is now 40 %');

      expect(bar.apply([job('a', onPhone: 9), job('b', onPhone: 9)]),
          closeTo(0.90, 1e-9));
    });

    test(
        'a job whose size is not known yet does not lift the bar: it is not full because the others ended',
        () {
      final bar = CardBar();
      expect(
          bar.apply([
            job('a', onPhone: 5),
            job('b', onPhone: 0, ready: 0, songs: 0, starting: true),
          ]),
          closeTo(0.50, 1e-9));

      // A ends while B has not been answered yet: B counts for nothing so far, and 100 % would be a lie that the floor would then keep.
      expect(
          bar.apply([
            job('a', onPhone: 10, phase: CardPhase.ready),
            job('b', onPhone: 0, ready: 0, songs: 0, starting: true),
          ]),
          closeTo(0.50, 1e-9));

      // B's size arrives: (20 + 0) / 40 = 50 %, and from there it moves.
      expect(
          bar.apply([
            job('a', onPhone: 10, phase: CardPhase.ready),
            job('b', onPhone: 0, ready: 0),
          ]),
          closeTo(0.50, 1e-9));
      expect(
          bar.apply([
            job('a', onPhone: 10, phase: CardPhase.ready),
            job('b', onPhone: 5),
          ]),
          closeTo(0.75, 1e-9));
    });

    test('a download that finished long ago is no part of the card', () {
      final bar = CardBar();
      // A was ready before this card began: it never ran in it, so its full share must not lift the bar.
      final value = bar.apply([
        job('old', onPhone: 10, phase: CardPhase.ready),
        job('b', onPhone: 1, ready: 1),
      ]);

      expect(value, closeTo(0.10, 1e-9));
    });

    test('the card ends, and the next card starts from zero', () {
      final bar = CardBar();
      bar.apply([job('a', onPhone: 9), job('b', onPhone: 9)]);
      expect(
          bar.apply([
            job('a', onPhone: 10, phase: CardPhase.ready),
            job('b', onPhone: 10, phase: CardPhase.ready),
          ]),
          0);

      // A new download is a new card: its bar is its own share, not the floor of the last one.
      expect(bar.apply([job('c', onPhone: 1, ready: 1)]), closeTo(0.10, 1e-9));
      // and the jobs of the card that is over are not in this one's total
      expect(
          bar.apply([
            job('a', onPhone: 10, phase: CardPhase.ready),
            job('c', onPhone: 2, ready: 2),
          ]),
          closeTo(0.20, 1e-9));
    });

    test(
        'an import that becomes the Download of its playlist keeps one share and the floor holds',
        () {
      final bar = CardBar();
      const key = 'pin:playlist:pl_1';
      CardJob made(int done, int of) => CardJob(
            key: key,
            name: 'Prog snob',
            text: 'x',
            songs: 217,
            progressDone: done,
            progressOf: of,
          );

      expect(bar.apply([made(300, 434)]), closeTo(300 / 434, 1e-9));
      expect(bar.apply([made(100, 434)]), closeTo(300 / 434, 1e-9));
    });
  });

  group('the running card', () {
    test('starting: the verb and the name, no end to the bar yet', () {
      final card = liveCard([
        download('playlist:p1', 'Prog snob', 'Getting ready to download',
            onPhone: 0, ready: 0, starting: true),
      ], words)!;

      expect(card.title, 'Downloading Prog snob');
      expect(card.body, 'Starting…');
      expect(card.progress, isNull);
    });

    test('both stages: the line of S-16 word for word, the bar of the job', () {
      final card = liveCard([
        download('playlist:p1', 'Prog snob',
            '12 of 217 on this phone · 40 ready on your server'),
      ], words)!;

      expect(card.title, 'Downloading Prog snob');
      expect(card.body, '12 of 217 on this phone · 40 ready on your server');
      expect(card.progress, closeTo(0.12, 0.005));
      expect(card.route, '/library/downloaded');
    });

    test('only the server so far', () {
      final card = liveCard([
        download('playlist:w', 'Workout',
            'Getting it on your server · 40 of 217 ready',
            onPhone: 0),
      ], words)!;

      expect(card.title, 'Downloading Workout');
      expect(card.body, 'Getting it on your server · 40 of 217 ready');
      expect(card.progress, closeTo(0.092, 0.005),
          reason: 'it moves from the first song on the server');
    });

    test('an import with no Download says Importing and its own words', () {
      final card = liveCard([
        CardJob(
          key: 'import:im1',
          name: 'Prog snob',
          kind: CardJobKind.import,
          text: words.findingSongs(looked: 120, total: 217),
          songs: 217,
          importing: true,
          progressDone: 120,
          progressOf: 434,
        ),
      ], words)!;

      expect(card.title, 'Importing Prog snob');
      expect(card.body, 'Finding songs: 120 of 217');
    });

    test(
        'YouTube resting and the phone\'s reasons are S-16\'s words as they are',
        () {
      final resting = liveCard([
        download('playlist:f', 'Fairouz mornings',
            '3 of 9 on this phone · your server is resting until 21:40',
            songs: 9, onPhone: 3, ready: 4),
      ], words)!;
      expect(resting.body,
          '3 of 9 on this phone · your server is resting until 21:40');

      final waiting = liveCard([
        download('playlist:p1', 'Prog snob',
            '12 of 217 on this phone · waiting for a connection'),
      ], words)!;
      expect(
          waiting.body, '12 of 217 on this phone · waiting for a connection');
    });

    test(
        'several downloads are ONE card: how many, then a line each, three named',
        () {
      final jobs = [
        download('playlist:p1', 'Prog snob',
            '12 of 217 on this phone · 40 ready on your server'),
        download('playlist:f', 'Fairouz mornings',
            '3 of 9 on this phone · your server is resting until 21:40',
            songs: 9, onPhone: 3, ready: 4),
        download('playlist:w', 'Workout',
            'Getting it on your server · 40 of 217 ready',
            onPhone: 0),
        download('playlist:x', 'Road trip', '30 of 50 on this phone',
            songs: 50, onPhone: 30, ready: 30),
      ];
      final card = liveCard(jobs, words)!;

      expect(card.title, '4 downloads');
      expect(card.body, '45 of 493 songs on this phone');
      expect(
          card.expanded,
          [
            'Prog snob',
            '12 of 217 on this phone · 40 ready on your server',
            'Fairouz mornings',
            '3 of 9 on this phone · your server is resting until 21:40',
            'Workout',
            'Getting it on your server · 40 of 217 ready',
            'and 1 more',
          ].join('\n'));
    });

    test('no running job, no card', () {
      expect(liveCard(const [], words), isNull);
    });
  });

  group('the card of the app closed is dated and says no live reason', () {
    final at = DateTime(2026, 11, 24, 9, 3);

    test('one download still saving on the server: the drawn dated words', () {
      final card = datedCard([
        download('playlist:p1', 'Prog snob',
            '12 of 217 on this phone · your server is resting until 21:40',
            songs: 214, onPhone: 12, ready: 150),
      ], at, words)!;

      expect(card.title, 'Prog snob is still saving on your server');
      expect(card.body,
          '150 of 214 were ready at 9:03. Open Encore to see how far it is now.');
      expect(card.progress, isNull);
      expect(card.dated, isTrue);
      // nothing a later moment can make false: no "resting until", no "waiting for", no live count of the phone
      final said = '${card.title} ${card.body}'.toLowerCase();
      for (final live in ['resting', 'waiting', 'on this phone']) {
        expect(said, isNot(contains(live)));
      }
    });

    test(
        'several: the drawn title of several, the drawn sentence of the numbers',
        () {
      final card = datedCard([
        download('playlist:p1', 'Prog snob', 'x',
            songs: 214, onPhone: 12, ready: 150),
        download('playlist:f', 'Fairouz mornings', 'x',
            songs: 9, onPhone: 3, ready: 4),
      ], at, words)!;

      expect(card.title, '2 downloads');
      expect(card.body,
          '154 of 223 were ready at 9:03. Open Encore to see how far it is now.');
    });

    test(
        'an import counts what the server is going to hold, not what it was given',
        () {
      final card = datedCard([
        CardJob(
          key: 'import:im1',
          name: 'Prog snob',
          kind: CardJobKind.import,
          text: 'x',
          songs: 217,
          serverTotal: 214,
          ready: 150,
          saving: true,
        ),
      ], at, words)!;

      expect(card.body,
          '150 of 214 were ready at 9:03. Open Encore to see how far it is now.');
    });

    test(
        'a song on the phone is a song the server holds: never fewer than the phone has',
        () {
      // The server's answer is older than the phone's own table: 20 ready by the answer, 60 on the phone. "20 were ready" would be false.
      final one = datedCard([
        download('playlist:p1', 'Prog snob', 'x',
            songs: 214, onPhone: 60, ready: 20),
      ], at, words)!;
      expect(one.body,
          '60 of 214 were ready at 9:03. Open Encore to see how far it is now.');

      final several = datedCard([
        download('playlist:p1', 'Prog snob', 'x',
            songs: 214, onPhone: 60, ready: 20),
        download('playlist:f', 'Fairouz mornings', 'x',
            songs: 9, onPhone: 3, ready: 4),
      ], at, words)!;
      expect(several.body,
          '64 of 223 were ready at 9:03. Open Encore to see how far it is now.');
    });

    test(
        'a download the server has finished with has nothing to say outside the app',
        () {
      expect(
          datedCard([
            download('playlist:p1', 'Prog snob', 'x',
                songs: 217, onPhone: 100, ready: 217, saving: false),
          ], at, words),
          isNull);
    });
  });

  group('the card of a job that is over', () {
    final before = [
      download('playlist:p1', 'Prog snob', 'x', songs: 217, onPhone: 214),
    ];

    test('every song on the phone: ready offline, posted once', () {
      final after = [
        download('playlist:p1', 'Prog snob', 'x',
            songs: 217, onPhone: 217, ready: 217, phase: CardPhase.ready),
      ];
      final results = resultsBetween(before, after, words);

      expect(results, hasLength(1));
      expect(results.single.title, 'Prog snob is ready offline');
      expect(results.single.body, '217 songs are on this phone.');
      expect(results.single.route, '/library/downloaded');
      expect(resultsBetween(after, after, words), isEmpty,
          reason: 'a job that was already over made no card now');
    });

    test('some songs did not come: S-16\'s own words, and where to see why',
        () {
      final after = [
        download('playlist:p1', 'Prog snob', 'x',
            songs: 217,
            onPhone: 214,
            ready: 214,
            phase: CardPhase.partly,
            failed: 3),
      ];
      final results = resultsBetween(before, after, words);

      expect(results.single.title, 'Prog snob: 3 songs did not come');
      expect(results.single.body, '214 of 217 on this phone. Tap to see why.');
    });

    test('an import: the words the app already uses for its end', () {
      CardJob import(CardPhase phase, {int inLibrary = 40}) => CardJob(
            key: 'import:im1',
            name: 'Road trip',
            kind: CardJobKind.import,
            text: 'x',
            songs: 40,
            inLibrary: inLibrary,
            phase: phase,
            importRoute: '/library/playlist/pl_9',
          );
      final results = resultsBetween(
          [import(CardPhase.running)], [import(CardPhase.ready)], words);

      expect(results.single.title, '“Road trip” is ready');
      expect(results.single.body, '40 of 40 songs are in your library now.');
      expect(results.single.route, '/library/playlist/pl_9');
    });

    test('an import stopped somewhere else replaces the running card', () {
      final stopped = CardJob(
        key: 'import:im1',
        name: 'Prog snob',
        kind: CardJobKind.import,
        text: 'x',
        songs: 217,
        inLibrary: 24,
        phase: CardPhase.stopped,
      );
      final running = CardJob(
        key: 'import:im1',
        name: 'Prog snob',
        kind: CardJobKind.import,
        text: 'x',
        songs: 217,
      );
      final results = resultsBetween([running], [stopped], words);

      expect(results.single.title, 'Import stopped');
      expect(results.single.body,
          'Prog snob: 24 songs stay in your library. The rest were not fetched.');
    });

    test('a download the person removed leaves no card', () {
      expect(resultsBetween(before, const [], words), isEmpty);
    });

    // N-39 (S-95 "A download was stopped"): a Download's Stop is a pause that waits for the person, so it leaves ONE result card in S-16's words.
    group('a Download the person stopped (N-39)', () {
      CardJob stopped({int onPhone = 12, int songs = 217}) =>
          download('playlist:p1', 'Prog snob', 'x',
              songs: songs, onPhone: onPhone, phase: CardPhase.stopped);

      test(
          "N-39: the running card ends and ONE card says what is kept and that Resume continues, in the words drawn",
          () {
        final results = resultsBetween(before, [stopped()], words);

        expect(results, hasLength(1));
        expect(results.single.title, 'Prog snob is stopped');
        expect(results.single.body,
            '12 of 217 stay on this phone. Resume continues from there.');
        expect(results.single.route, '/library/downloaded',
            reason: 'the tap opens Downloaded, where Resume stands');
      });

      test(
          "N-39: it is not an import's card: a stopped download never says the rest were not fetched",
          () {
        final result = resultsBetween(before, [stopped()], words).single;

        expect(result.title, isNot('Import stopped'));
        expect(result.body, isNot(contains('library')));
        expect(result.body, isNot(contains('not fetched')));
      });

      test(
          "N-39: it names no clock time and no live count, so it stays true when it freezes",
          () {
        final result = resultsBetween(before, [stopped()], words).single;

        expect('${result.title} ${result.body}', isNot(matches(r'\d:\d\d')));
        expect(result.body, isNot(contains('ready on your server')));
        expect(result.body, isNot(contains('Downloading')));
      });

      test(
          "N-39: posted once: a download that was already stopped when the app opened, or that stays stopped, makes no card",
          () {
        expect(resultsBetween(const [], [stopped()], words), isEmpty,
            reason: 'not posted again at the next start of the app');
        expect(resultsBetween([stopped()], [stopped()], words), isEmpty);
        expect(resultsBetween([stopped()], const [], words), isEmpty,
            reason: 'Remove after a Stop leaves no card either');
      });

      test(
          "N-39: Resume makes the job run again and posts nothing; a second Stop is a second card",
          () {
        final running = download('playlist:p1', 'Prog snob', 'x');

        expect(resultsBetween([stopped()], [running], words), isEmpty);
        expect(resultsBetween([running], [stopped(onPhone: 80)], words),
            hasLength(1));
      });

      test(
          "N-39: several downloads: each stopped one leaves its own card, the others go on",
          () {
        final other = download('playlist:p2', 'Workout', 'x');
        final results = resultsBetween(
          [before.single, other],
          [
            stopped(),
            download('playlist:p3', 'Third', 'x', phase: CardPhase.stopped),
            other
          ],
          words,
        );

        expect(results.map((r) => r.title), ['Prog snob is stopped']);
        final both = resultsBetween(
          [
            before.single,
            download('playlist:p3', 'Third', 'x'),
          ],
          [
            stopped(),
            download('playlist:p3', 'Third', 'x', phase: CardPhase.stopped),
          ],
          words,
        );
        expect(both.map((r) => r.title),
            ['Prog snob is stopped', 'Third is stopped']);
        expect(both.map((r) => resultCardId(r.key)).toSet(), hasLength(2),
            reason: 'one card of its own per job');
      });

      test("N-39: the words choose their plural inside the sentence", () {
        expect(words.downloadStoppedBody(onPhone: 1, total: 217),
            '1 of 217 stays on this phone. Resume continues from there.');
        expect(words.downloadStoppedBody(onPhone: 0, total: 217),
            '0 of 217 stay on this phone. Resume continues from there.');
        expect(words.downloadStoppedTitle(name: 'Prog snob'),
            'Prog snob is stopped');
      });

      test(
          "N-39: a stopped job is no part of the live card, the dated card or the bar",
          () {
        final live = download('playlist:p2', 'Workout', 'x');
        expect(liveCard([stopped()], words), isNull);
        expect(datedCard([stopped()], DateTime(2026, 11, 17, 9, 41), words),
            isNull,
            reason: 'its phone copy is paused: nothing of it is saving');
        // The card with only a stopped job left ENDS: the next card starts from zero.
        final bar = CardBar();
        expect(bar.apply([live, before.single]), greaterThan(0));
        expect(bar.apply([stopped()]), 0);
        // With another job still running, the live card is that job's alone.
        expect(
            liveCard([stopped(), live], words)!.title, 'Downloading Workout');
      });
    });

    test('a liked-songs import says so in the words the app already has', () {
      CardJob liked(CardPhase p) => CardJob(
            key: 'import:l',
            name: 'Liked Songs',
            kind: CardJobKind.import,
            text: 'x',
            songs: 300,
            inLibrary: 290,
            liked: true,
            phase: p,
          );
      final results = resultsBetween(
          [liked(CardPhase.running)], [liked(CardPhase.ready)], words);
      expect(results.single.title, 'Your liked songs are imported');
    });
  });

  group('the words', () {
    test('every sentence is one whole message, a count never glued', () {
      expect(words.andMore(count: 1), 'and 1 more');
      expect(words.andMore(count: 12), 'and 12 more');
      expect(words.songsOnThisPhone(count: 1), '1 song is on this phone.');
      expect(words.songsOnThisPhone(count: 2), '2 songs are on this phone.');
      expect(words.importStoppedBody(name: 'A', kept: 1),
          'A: 1 song stays in your library. The rest were not fetched.');
      expect(
          words.didNotComeTitle(name: 'A', count: 1), 'A: 1 song did not come');
    });

    test('the time is written the way the drawing writes it', () {
      expect(
          words.readyAt(ready: 1, total: 2, time: DateTime(2026, 1, 1, 21, 5)),
          '1 of 2 were ready at 21:05. Open Encore to see how far it is now.');
      expect(
          words.readyAt(ready: 1, total: 2, time: DateTime(2026, 1, 1, 9, 3)),
          '1 of 2 were ready at 9:03. Open Encore to see how far it is now.');
    });
  });
}
