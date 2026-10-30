import 'package:encore/core/result.dart';
import 'package:encore/data/encore/encore_models.dart';
import 'package:encore/features/instant/release_save.dart';
import 'package:flutter_test/flutter_test.dart';

/// Saving or downloading a catalogue release on an Encore server (D-21, docs/17 "Saving a release"): the songs are resolved, ONE call asks
/// the server to save the release and keep them, and only what the server confirmed is pinned on the phone. Never silence.
void main() {
  const titles = {'sr_1': 'Weird Fishes', 'sr_2': 'Nude', 'sr_3': 'Reckoner'};

  late List<String> events;
  late Map<String, String> keep; // by ref: the state the server answers with
  late Result<EncoreReleaseSave> Function() answer;

  ReleaseSaver saver({Set<String> unresolved = const {}}) => ReleaseSaver(
        resolve: (id, title) async {
          events.add('resolve $title');
          return unresolved.contains(id) ? null : id;
        },
        save: (releaseId, refIds) async {
          events.add('save $releaseId ${refIds.join(",")}');
          return answer();
        },
        pin: (refId) async => events.add('pin $refId'),
      );

  final songs = [
    for (final e in titles.entries) (id: e.key, title: e.value),
  ];

  setUp(() {
    events = [];
    keep = {for (final id in titles.keys) id: 'queued'};
    answer = () => Result.ok(EncoreReleaseSave(changed: true, keep: {
          for (final e in keep.entries) e.key: EncoreKeep(e.value),
        }));
  });

  test(
      'PB-33: adding to the library resolves the songs, makes one call naming them in order, and pins nothing',
      () async {
    final outcome =
        await saver().run(releaseId: 'cat:1', songs: songs, download: false);

    expect(events, [
      'resolve Weird Fishes',
      'resolve Nude',
      'resolve Reckoner',
      'save cat:1 sr_1,sr_2,sr_3',
    ]);
    expect(outcome.saved, ['sr_1', 'sr_2', 'sr_3']);
    expect(outcome.problem, isNull);
    expect(outcome.message, isNull);
  });

  test(
      'PB-34: a download pins each song only after the server confirmed the save, so it survives the app being killed',
      () async {
    await saver().run(releaseId: 'cat:1', songs: songs, download: true);

    final save = events.indexWhere((e) => e.startsWith('save '));
    final pins = [
      for (var i = 0; i < events.length; i++)
        if (events[i].startsWith('pin ')) i
    ];
    expect(pins, hasLength(3));
    expect(pins.every((i) => i > save), isTrue);
    expect(events.where((e) => e.startsWith('pin ')),
        ['pin sr_1', 'pin sr_2', 'pin sr_3']);
  });

  test(
      'PB-37: a song that cannot be resolved is named in words; the others are still saved',
      () async {
    final outcome = await saver(unresolved: {'sr_2'})
        .run(releaseId: 'cat:1', songs: songs, download: true);

    expect(events.firstWhere((e) => e.startsWith('save ')),
        'save cat:1 sr_1,sr_3');
    expect(outcome.saved, ['sr_1', 'sr_3']);
    expect(outcome.message, "Couldn't get 1 song: Nude.");
    expect(events.where((e) => e.startsWith('pin ')), ['pin sr_1', 'pin sr_3']);
  });

  test(
      'PB-37: a song the server could not keep is named in words with its reason',
      () async {
    keep['sr_3'] = 'failed';
    answer = () => Result.ok(EncoreReleaseSave(changed: true, keep: {
          'sr_1': const EncoreKeep('queued'),
          'sr_2': const EncoreKeep('queued'),
          'sr_3': const EncoreKeep('failed', reason: 'YouTube is resting'),
        }));

    final outcome =
        await saver().run(releaseId: 'cat:1', songs: songs, download: false);

    expect(
        outcome.message, "Couldn't get 1 song: Reckoner (YouTube is resting).");
    expect(outcome.saved, ['sr_1', 'sr_2', 'sr_3'],
        reason: 'the save itself stands; the person is told about the song');
  });

  test(
      'PB-36: a server that does not answer saves nothing, pins nothing, and says so in words',
      () async {
    answer = () => Result.err(const NetworkFailure('Network error'));

    final outcome =
        await saver().run(releaseId: 'cat:1', songs: songs, download: true);

    expect(outcome.saved, isEmpty);
    expect(events.where((e) => e.startsWith('pin ')), isEmpty);
    expect(outcome.problem, "Can't reach your server. Nothing was saved.");
    expect(outcome.message, outcome.problem);
  });

  test('PB-36: a server that does not know a song refuses in words', () async {
    answer = () => Result.err(const NotFoundFailure('Not found'));

    final outcome =
        await saver().run(releaseId: 'cat:1', songs: songs, download: false);

    expect(outcome.saved, isEmpty);
    expect(outcome.problem,
        'Your server did not know one of these songs. Nothing was saved. Try again.');
  });

  test('PB-36: when no song could be resolved the server is not asked at all',
      () async {
    final outcome = await saver(unresolved: {'sr_1', 'sr_2', 'sr_3'})
        .run(releaseId: 'cat:1', songs: songs, download: true);

    expect(events.where((e) => e.startsWith('save ')), isEmpty);
    expect(outcome.saved, isEmpty);
    expect(
        outcome.problem, "Couldn't get any of these songs. Nothing was saved.");
  });
}
