import 'dart:async';

import 'package:encore/core/result.dart';
import 'package:encore/data/people/activity_publisher.dart';
import 'package:encore/data/people/people_client.dart';
import 'package:flutter_test/flutter_test.dart';

/// Tells the friends what I am listening to (docs/35, section 4), but only
/// when I chose to, only once I have settled on a song, and never anything
/// that points into my library. (What counts as a song worth sharing, and
/// which picture may go with it, is decided before this: `listeningFrom`.)

class _ManualTimer implements Timer {
  _ManualTimer(this.delay, this._callback);
  final Duration delay;
  final void Function() _callback;
  bool cancelled = false;
  bool fired = false;

  void fire() {
    fired = true;
    _callback();
  }

  @override
  void cancel() => cancelled = true;
  @override
  bool get isActive => !cancelled && !fired;
  @override
  int get tick => 0;
}

class _Timers {
  final all = <_ManualTimer>[];

  Timer create(Duration delay, void Function() callback) {
    final timer = _ManualTimer(delay, callback);
    all.add(timer);
    return timer;
  }

  /// The timer that is waiting right now, if any.
  _ManualTimer? get live {
    final waiting = all.where((t) => t.isActive).toList();
    expect(waiting.length, lessThanOrEqualTo(1),
        reason: 'one timer at a time: a new one replaces the old');
    return waiting.isEmpty ? null : waiting.single;
  }

  Future<void> fire() async {
    live!.fire();
    await pumpEventQueue();
  }
}

class _Sink implements ActivitySink {
  /// Every call in order: a [NowPlayingReport] or the word `clear`.
  final calls = <Object>[];
  bool fail = false;

  List<NowPlayingReport> get reports =>
      calls.whereType<NowPlayingReport>().toList();

  Result<void> get _answer => fail
      ? const Result<void>.err(NetworkFailure('down'))
      : const Result<void>.ok(null);

  @override
  Future<Result<void>> report(NowPlayingReport report) async {
    calls.add(report);
    return _answer;
  }

  @override
  Future<Result<void>> clear() async {
    calls.add('clear');
    return _answer;
  }
}

ListeningState song(
  String id, {
  bool playing = true,
  String? coverUrl,
}) =>
    ListeningState(
      id: id,
      title: 'Song $id',
      artist: 'Pink Floyd',
      album: 'Animals',
      coverUrl: coverUrl,
      playing: playing,
    );

void main() {
  late StreamController<ListeningState?> listening;
  late _Timers timers;
  late _Sink sink;
  late bool sharing;
  late bool serviceThere;
  late ActivityPublisher publisher;

  setUp(() {
    listening = StreamController<ListeningState?>.broadcast(sync: true);
    timers = _Timers();
    sink = _Sink();
    sharing = true;
    serviceThere = true;
    publisher = ActivityPublisher(
      listening: listening.stream,
      sink: () => serviceThere ? sink : null,
      sharing: () => sharing,
      timer: timers.create,
    );
  });

  tearDown(() async {
    publisher.dispose();
    await listening.close();
  });

  test('nothing happens until the person chose to share', () async {
    sharing = false;

    listening.add(song('a'));
    await pumpEventQueue();

    expect(timers.live, isNull, reason: 'not even a timer is started');
    expect(sink.calls, isEmpty);
  });

  test('a song is reported once the person has settled on it', () async {
    listening.add(song('a'));
    await pumpEventQueue();

    expect(sink.calls, isEmpty, reason: 'not the instant it starts');
    expect(timers.live!.delay, const Duration(seconds: 2));

    await timers.fire();

    final report = sink.reports.single;
    expect(report.title, 'Song a');
    expect(report.artist, 'Pink Floyd');
    expect(report.album, 'Animals');
    expect(report.playing, isTrue);
    expect(report.coverUrl, isNull);
  });

  test('skipping through songs reports only where the person stops', () async {
    listening.add(song('a'));
    listening.add(song('b'));
    listening.add(song('c'));
    await pumpEventQueue();
    await timers.fire();

    expect(sink.reports.map((r) => r.title), ['Song c']);
    expect(timers.all.where((t) => t.cancelled), hasLength(2));
  });

  test('pausing is reported as paused', () async {
    listening.add(song('a'));
    await timers.fire();
    listening.add(song('a', playing: false));
    await timers.fire();

    expect(sink.reports.map((r) => r.playing), [true, false]);
  });

  test('the same state again changes nothing', () async {
    listening.add(song('a'));
    await timers.fire();
    final waiting = timers.live;

    listening.add(song('a'));
    await pumpEventQueue();

    expect(timers.live, same(waiting),
        reason: 'no new timer: the long-song reminder keeps counting');
    expect(sink.reports, hasLength(1));
  });

  test('a public picture goes with the song', () async {
    listening.add(song('b', coverUrl: 'https://cdn.example/b.jpg'));
    await timers.fire();

    expect(sink.reports.single.coverUrl, 'https://cdn.example/b.jpg');
  });

  test('nothing to share any more clears it, once', () async {
    listening.add(song('a'));
    await timers.fire();
    listening.add(null); // stopped, or a sample started
    await timers.fire();

    expect(sink.calls.last, 'clear');

    listening.add(null);
    await pumpEventQueue();
    expect(timers.live, isNull, reason: 'still nothing: nothing to say');
    expect(sink.calls.where((c) => c == 'clear'), hasLength(1));
  });

  test('turning sharing off forgets the song at once, and stays quiet',
      () async {
    listening.add(song('a'));
    await timers.fire();

    sharing = false; // or private listening switched on
    publisher.refresh();
    await pumpEventQueue();

    expect(sink.calls.last, 'clear');
    expect(timers.live, isNull);

    listening.add(song('b'));
    await pumpEventQueue();
    expect(timers.live, isNull);
    expect(sink.reports, hasLength(1));
  });

  test('turning sharing off with nothing shared sends nothing', () async {
    sharing = false;
    publisher.refresh();
    await pumpEventQueue();

    expect(sink.calls, isEmpty);
  });

  test('turning sharing on shares the song that is already playing', () async {
    sharing = false;
    listening.add(song('a'));
    await pumpEventQueue();
    expect(sink.calls, isEmpty);

    sharing = true;
    publisher.refresh();
    await timers.fire();

    expect(sink.reports.single.title, 'Song a');
  });

  test('a long song is kept alive, a paused one is left to fade', () async {
    listening.add(song('a'));
    await timers.fire();

    expect(timers.live!.delay, const Duration(minutes: 5));
    await timers.fire();
    expect(sink.reports.map((r) => r.title), ['Song a', 'Song a']);

    listening.add(song('a', playing: false));
    await timers.fire();
    expect(timers.live, isNull,
        reason: 'the service forgets a paused song by itself');
  });

  test('no service, no problem', () async {
    serviceThere = false;
    listening.add(song('a'));
    await timers.fire();
    expect(sink.calls, isEmpty);

    serviceThere = true;
    listening.add(song('b'));
    await timers.fire();
    expect(sink.reports.single.title, 'Song b');
  });

  test('a report that failed is tried again later', () async {
    sink.fail = true;
    listening.add(song('a'));
    await timers.fire();
    expect(sink.reports, hasLength(1));
    expect(timers.live!.delay, const Duration(minutes: 5));

    sink.fail = false;
    await timers.fire();
    expect(sink.reports.map((r) => r.title), ['Song a', 'Song a']);
  });

  test('closing forgets the song and stops listening', () async {
    listening.add(song('a'));
    await timers.fire();

    publisher.dispose();
    await pumpEventQueue();

    expect(sink.calls.last, 'clear');
    expect(timers.live, isNull);

    listening.add(song('b'));
    await pumpEventQueue();
    expect(timers.live, isNull);
  });
}
