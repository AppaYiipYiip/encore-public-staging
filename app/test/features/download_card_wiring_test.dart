import 'package:encore/app/app_in_front.dart';
import 'package:encore/app/providers.dart';
import 'package:encore/core/clock.dart';
import 'package:encore/domain/download_card.dart';
import 'package:encore/features/downloads/download_card_jobs.dart';
import 'package:encore/features/downloads/download_card_wiring.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

/// docs/design S-95 (P2-29): the card follows the jobs and the person's place: every change of the jobs and every leaving or coming back of the app is
/// a look; with the permission refused nothing is posted.
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
}

class _Jobs extends Notifier<List<CardJob>> {
  @override
  List<CardJob> build() => const [];

  void set(List<CardJob> jobs) => state = jobs;
}

class _Front extends AppInFront {
  @override
  bool build() => true;

  void set(bool value) => state = value;
}

final _jobsSource = NotifierProvider<_Jobs, List<CardJob>>(_Jobs.new);

CardJob _job({int onPhone = 12, CardPhase phase = CardPhase.running}) {
  final bar = downloadBar(songs: 217, onPhone: onPhone, ready: 40);
  return CardJob(
    key: 'pin:playlist:pl_1',
    name: 'Prog snob',
    text: '$onPhone of 217 on this phone · 40 ready on your server',
    songs: 217,
    onPhone: onPhone,
    ready: 40,
    saving: true,
    phase: phase,
    progressDone: bar.done,
    progressOf: bar.of,
  );
}

void main() {
  late _Sink sink;
  late ProviderContainer c;

  setUp(() {
    sink = _Sink();
    c = ProviderContainer(overrides: [
      downloadCardSinkProvider.overrideWithValue(sink),
      downloadCardPaceProvider.overrideWithValue(Duration.zero),
      downloadCardJobsProvider.overrideWith((ref) => ref.watch(_jobsSource)),
      appInFrontProvider.overrideWith(_Front.new),
      clockProvider.overrideWithValue(FakeClock(DateTime(2026, 11, 24, 9, 3))),
    ]);
    addTearDown(c.dispose);
    c.listen(downloadCardProvider, (_, __) {});
  });

  Future<void> turn() => Future<void>.delayed(const Duration(milliseconds: 20));

  test('nothing running, nothing posted', () async {
    await turn();
    expect(sink.posts, isEmpty);
  });

  test('a download that starts is a card; its changes refresh the same card',
      () async {
    c.read(_jobsSource.notifier).set([_job(onPhone: 12)]);
    await turn();
    c.read(_jobsSource.notifier).set([_job(onPhone: 13)]);
    await turn();

    expect(sink.posts.map((p) => p.id).toSet(), {kRunningCardId});
    expect(sink.posts.last.spec.body, startsWith('13 of 217'));
  });

  test('leaving the app makes the card dated; coming back makes it live again',
      () async {
    c.read(_jobsSource.notifier).set([_job()]);
    await turn();
    (c.read(appInFrontProvider.notifier) as _Front).set(false);
    await turn();

    expect(sink.posts.last.spec.dated, isTrue);
    expect(sink.posts.last.timeoutAfter, isNull);

    (c.read(appInFrontProvider.notifier) as _Front).set(true);
    await turn();
    expect(sink.posts.last.spec.dated, isFalse);
    expect(sink.posts.last.timeoutAfter, isNotNull);
    expect(sink.posts.map((p) => p.id).toSet(), {kRunningCardId});
  });

  test('when the job is over the card is replaced by its result', () async {
    c.read(_jobsSource.notifier).set([_job()]);
    await turn();
    c
        .read(_jobsSource.notifier)
        .set([_job(onPhone: 217, phase: CardPhase.ready)]);
    await turn();

    expect(sink.cancels, [kRunningCardId]);
    expect(sink.posts.last.kind, CardKind.result);
    expect(sink.posts.last.spec.title, 'Prog snob is ready offline');
  });

  test('with the permission refused nothing is posted', () async {
    sink.allowed = false;
    c.read(_jobsSource.notifier).set([_job()]);
    await turn();
    c
        .read(_jobsSource.notifier)
        .set([_job(onPhone: 217, phase: CardPhase.ready)]);
    await turn();

    expect(sink.posts, isEmpty);
  });
}
