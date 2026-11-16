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

    test('it only moves forward while the same jobs run', () {
      final floor = ProgressFloor();
      expect(floor.apply({'a'}, 0.40), 0.40);
      expect(floor.apply({'a'}, 0.25), 0.40, reason: 'a reason to wait');
      expect(floor.apply({'a'}, 0.55), 0.55);
      // another download joins: the share is of another whole, and may start again
      expect(floor.apply({'a', 'b'}, 0.30), 0.30);
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
