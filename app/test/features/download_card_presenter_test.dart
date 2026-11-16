import 'package:encore/domain/download_card.dart';
import 'package:encore/features/downloads/download_card_presenter.dart';
import 'package:flutter_test/flutter_test.dart';

/// docs/design S-95 (P2-29): WHEN the one card is posted, refreshed, switched to its dated form, ended. A recorder stands in for the notification
/// manager: nothing here touches a phone.
class _Sink implements DownloadCardSink {
  bool allowed = true;
  final List<CardPost> posts = [];
  final List<int> cancels = [];

  @override
  Future<bool> canPost() async => allowed;

  @override
  Future<void> post(CardPost card) async => posts.add(card);

  @override
  Future<void> cancel(int id) async => cancels.add(id);

  List<CardPost> get running => [
        for (final p in posts)
          if (p.kind == CardKind.running) p
      ];
  List<CardPost> get results => [
        for (final p in posts)
          if (p.kind == CardKind.result) p
      ];
}

CardJob _job(
  String key,
  String name, {
  String text = '12 of 217 on this phone · 40 ready on your server',
  int songs = 217,
  int onPhone = 12,
  int ready = 40,
  bool saving = true,
  CardPhase phase = CardPhase.running,
  bool starting = false,
}) {
  final bar = downloadBar(songs: songs, onPhone: onPhone, ready: ready);
  return CardJob(
    key: key,
    name: name,
    text: text,
    songs: songs,
    onPhone: onPhone,
    ready: ready,
    saving: saving,
    phase: phase,
    starting: starting,
    progressDone: bar.done,
    progressOf: bar.of,
  );
}

void main() {
  late _Sink sink;
  late DateTime now;
  late DownloadCardPresenter presenter;

  setUp(() {
    sink = _Sink();
    now = DateTime(2026, 11, 24, 9, 3);
    presenter = DownloadCardPresenter(
      sink: sink,
      now: () => now,
      // The tests that look at time say so; the rest do not wait for it.
      minGap: Duration.zero,
    );
  });
  tearDown(() => presenter.dispose());

  group('the permission', () {
    test('with the notification permission refused nothing is posted',
        () async {
      sink.allowed = false;

      await presenter
          .update(jobs: [_job('playlist:p1', 'Prog snob')], foreground: true);
      await presenter
          .update(jobs: [_job('playlist:p1', 'Prog snob')], foreground: false);
      await presenter.update(jobs: const [], foreground: true);

      expect(sink.posts, isEmpty);
      expect(sink.cancels, isEmpty,
          reason: 'nothing was shown, so there is nothing to take away');
    });
  });

  group('the live card, while the app is open', () {
    test('it is one card, refreshed in place with the same id, never stacked',
        () async {
      await presenter.update(
          jobs: [_job('playlist:p1', 'Prog snob', onPhone: 12)],
          foreground: true);
      await presenter.update(jobs: [
        _job('playlist:p1', 'Prog snob',
            onPhone: 13,
            text: '13 of 217 on this phone · 41 ready on your server')
      ], foreground: true);

      expect(sink.running, hasLength(2));
      expect({for (final p in sink.running) p.id}, {kRunningCardId});
      expect(sink.running.last.spec.body,
          '13 of 217 on this phone · 41 ready on your server');
    });

    test('a look that changes nothing posts nothing', () async {
      final job = _job('playlist:p1', 'Prog snob');
      await presenter.update(jobs: [job], foreground: true);
      await presenter.update(jobs: [job], foreground: true);

      expect(sink.running, hasLength(1));
    });

    test(
        'it is posted with a time to live, so that a killed app leaves no frozen card',
        () async {
      await presenter
          .update(jobs: [_job('playlist:p1', 'Prog snob')], foreground: true);

      expect(sink.running.single.timeoutAfter, isNotNull);
      expect(sink.running.single.timeoutAfter, greaterThan(Duration.zero));
      expect(sink.running.single.spec.dated, isFalse);
    });

    test('several downloads are one card on the one id', () async {
      await presenter.update(jobs: [
        _job('playlist:p1', 'Prog snob'),
        _job('playlist:f', 'Fairouz mornings',
            songs: 9, onPhone: 3, ready: 4, text: 'x'),
      ], foreground: true);

      expect(sink.running, hasLength(1));
      expect(sink.running.single.spec.title, '2 downloads');
    });

    test('the bar never goes back while the same downloads run', () async {
      await presenter.update(
          jobs: [_job('playlist:p1', 'Prog snob', onPhone: 100, ready: 100)],
          foreground: true);
      await presenter.update(jobs: [
        _job('playlist:p1', 'Prog snob',
            onPhone: 50,
            ready: 50,
            text: '50 of 217 on this phone · waiting for a connection'),
      ], foreground: true);

      expect(sink.running.last.spec.progress, sink.running.first.spec.progress);
    });

    testWidgets(
        'a card nothing changes is refreshed now and then, so that it does not time out while the app is open',
        (tester) async {
      final timed = DownloadCardPresenter(
        sink: sink,
        now: () => now,
        minGap: Duration.zero,
        heartbeat: const Duration(seconds: 60),
      );
      await timed
          .update(jobs: [_job('playlist:p1', 'Prog snob')], foreground: true);
      expect(sink.running, hasLength(1));

      await tester.pump(const Duration(seconds: 61));
      expect(sink.running, hasLength(2),
          reason: 'the same card posted again with a new time to live');
      expect(
          sink.running.last.spec.signature, sink.running.first.spec.signature);
      await tester.pump(const Duration(seconds: 61));
      expect(sink.running, hasLength(3));
      // Timers still pending when the test body ends fail it: the card ends before then.
      timed.dispose();
    });

    testWidgets(
        'but leaving the app is posted at once, not held back by that pace',
        (tester) async {
      final slow = DownloadCardPresenter(
        sink: sink,
        now: () => now,
        minGap: const Duration(seconds: 30),
      );
      final job = _job('playlist:p1', 'Prog snob', songs: 214, ready: 150);
      await slow.update(jobs: [job], foreground: true);
      await slow.update(jobs: [job], foreground: false);

      expect(sink.running, hasLength(2));
      expect(sink.running.last.spec.dated, isTrue);
      slow.dispose();
    });

    testWidgets('cards are not posted faster than the phone allows',
        (tester) async {
      final slow = DownloadCardPresenter(
        sink: sink,
        now: () => now,
        minGap: const Duration(seconds: 1),
      );
      await slow.update(
          jobs: [_job('playlist:p1', 'Prog snob', onPhone: 1)],
          foreground: true);
      await slow.update(
          jobs: [_job('playlist:p1', 'Prog snob', onPhone: 2, text: 'two')],
          foreground: true);
      await slow.update(
          jobs: [_job('playlist:p1', 'Prog snob', onPhone: 3, text: 'three')],
          foreground: true);

      expect(sink.running, hasLength(1), reason: 'the others wait their turn');

      now = now.add(const Duration(seconds: 2));
      await tester.pump(const Duration(seconds: 2));
      expect(sink.running, hasLength(2));
      expect(sink.running.last.spec.body, 'three',
          reason: 'the last look is the one that is shown');
      slow.dispose();
    });
  });

  group('the app is left', () {
    test(
        'the card becomes the dated card, with no time to live, on the SAME id',
        () async {
      final job =
          _job('playlist:p1', 'Prog snob', songs: 214, onPhone: 12, ready: 150);
      await presenter.update(jobs: [job], foreground: true);
      await presenter.update(jobs: [job], foreground: false);

      final dated = sink.running.last;
      expect(dated.id, sink.running.first.id);
      expect(dated.timeoutAfter, isNull,
          reason:
              'it says when its numbers were true, so freezing leaves it true');
      expect(dated.spec.dated, isTrue);
      expect(dated.spec.title, 'Prog snob is still saving on your server');
      expect(dated.spec.body,
          '150 of 214 were ready at 9:03. Open Encore to see how far it is now.');
    });

    test('coming back brings the live card back on the same id', () async {
      final job = _job('playlist:p1', 'Prog snob');
      await presenter.update(jobs: [job], foreground: true);
      await presenter.update(jobs: [job], foreground: false);
      await presenter.update(jobs: [job], foreground: true);

      final ids = [for (final p in sink.running) p.id];
      expect(ids, [kRunningCardId, kRunningCardId, kRunningCardId]);
      expect(sink.running.last.spec.dated, isFalse);
      expect(sink.running.last.timeoutAfter, isNotNull);
      expect(sink.cancels, isEmpty,
          reason: 'replaced in place, never taken away and put back');
    });

    test(
        'the dated card is refreshed while the phone lets the app run, and says its time',
        () async {
      await presenter.update(
          jobs: [_job('playlist:p1', 'Prog snob', songs: 214, ready: 150)],
          foreground: false);
      now = DateTime(2026, 11, 24, 9, 30);
      await presenter.update(
          jobs: [_job('playlist:p1', 'Prog snob', songs: 214, ready: 180)],
          foreground: false);

      expect(sink.running.last.spec.body,
          '180 of 214 were ready at 9:30. Open Encore to see how far it is now.');
    });

    test('the same numbers a minute later are not a new card', () async {
      final job = _job('playlist:p1', 'Prog snob', songs: 214, ready: 150);
      await presenter.update(jobs: [job], foreground: false);
      now = DateTime(2026, 11, 24, 9, 4);
      await presenter.update(jobs: [job], foreground: false);

      expect(sink.running, hasLength(1),
          reason: '"150 of 214 were ready at 9:03" is still true');
    });

    test('no live reason and no timer outside the app', () async {
      await presenter.update(jobs: [
        _job('playlist:p1', 'Prog snob',
            text:
                '12 of 217 on this phone · your server is resting until 21:40'),
      ], foreground: false);

      final said =
          '${sink.running.single.spec.title} ${sink.running.single.spec.body}';
      expect(said, isNot(contains('resting')));
      expect(said, isNot(contains('waiting')));
    });

    test('a download the server is done with has no card outside the app',
        () async {
      final job = _job('playlist:p1', 'Prog snob', saving: false, ready: 217);
      await presenter.update(jobs: [job], foreground: true);
      await presenter.update(jobs: [job], foreground: false);

      expect(sink.cancels, [kRunningCardId]);
    });

    testWidgets('there is no refreshing timer outside the app', (tester) async {
      final timed = DownloadCardPresenter(
        sink: sink,
        now: () => now,
        minGap: Duration.zero,
        heartbeat: const Duration(seconds: 60),
      );
      await timed
          .update(jobs: [_job('playlist:p1', 'Prog snob')], foreground: false);
      final before = sink.running.length;

      await tester.pump(const Duration(minutes: 5));
      expect(sink.running, hasLength(before));
      timed.dispose();
    });
  });

  group('a job is over', () {
    test('the running card goes and one result card takes its place, once',
        () async {
      await presenter.update(
          jobs: [_job('playlist:p1', 'Prog snob', onPhone: 214, ready: 214)],
          foreground: true);
      final done = [
        _job('playlist:p1', 'Prog snob',
            onPhone: 217, ready: 217, phase: CardPhase.ready, saving: false),
      ];
      await presenter.update(jobs: done, foreground: true);
      await presenter.update(jobs: done, foreground: true);

      expect(sink.cancels, [kRunningCardId]);
      expect(sink.results, hasLength(1));
      expect(sink.results.single.spec.title, 'Prog snob is ready offline');
      expect(sink.results.single.id, isNot(kRunningCardId));
      expect(sink.results.single.id, resultCardId('playlist:p1'));
    });

    test('a result card is posted in the background too, and is not timed out',
        () async {
      await presenter.update(
          jobs: [_job('playlist:p1', 'Prog snob', onPhone: 214, ready: 214)],
          foreground: false);
      await presenter.update(jobs: [
        _job('playlist:p1', 'Prog snob',
            onPhone: 217, ready: 217, phase: CardPhase.ready, saving: false),
      ], foreground: false);

      expect(sink.results, hasLength(1));
      expect(sink.results.single.timeoutAfter, isNull);
    });

    test(
        'a download the person removed leaves no card and takes the running card away',
        () async {
      await presenter
          .update(jobs: [_job('playlist:p1', 'Prog snob')], foreground: true);
      await presenter.update(jobs: const [], foreground: true);

      expect(sink.results, isEmpty);
      expect(sink.cancels, [kRunningCardId]);
    });
  });

  group('the card ends', () {
    test('dispose cancels what waits and posts nothing more', () async {
      await presenter
          .update(jobs: [_job('playlist:p1', 'Prog snob')], foreground: true);
      presenter.dispose();
      final before = sink.posts.length;
      await presenter.update(
          jobs: [_job('playlist:p1', 'Prog snob', onPhone: 50)],
          foreground: true);

      expect(sink.posts, hasLength(before));
    });
  });
}
