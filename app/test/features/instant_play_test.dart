import 'package:encore/core/result.dart';
import 'package:encore/data/catalogue/catalogue_models.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/fetch/fetch_client.dart';
import 'package:encore/features/instant/instant_controller.dart';
import 'package:encore/features/instant/instant_play.dart';
import 'package:encore/features/jam/jam_providers.dart';
import 'package:encore/features/player/playback_facade.dart';
import 'package:encore/features/requests/request_providers.dart';
import 'package:encore/playback/queue_model.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';

import '../support/factories.dart';
import '../support/fake_catalogue.dart';
import '../support/test_app.dart';

/// Scripted service: each started song walks through [script] one step per
/// status call, then ends in `ready` (or the given failure).
class _FakeBackend implements InstantPlayBackend {
  _FakeBackend({
    this.latency = Duration.zero,
    this.streams = false,
    this.streamWhileDownloading = false,
    this.fail,
    this.songIdFor = _songIdFor,
    this.busy = 0,
    this.busyCode = 'rate_limited',
    this.refused = 0,
  });

  /// How many songs YouTube refuses the server before it lets one through.
  int refused;

  /// How many times the service answers "too many songs at once" (HTTP 429)
  /// before it accepts the song.
  int busy;
  final String busyCode;
  int asks = 0;

  static const script = [FetchState.searching, FetchState.downloading];

  /// How long each call to the service takes.
  final Duration latency;

  /// The finished job can be streamed from the service.
  final bool streams;

  /// The service offers the audio as soon as it starts to arrive.
  final bool streamWhileDownloading;
  final FetchJob? fail;
  final String? Function(String title) songIdFor;
  final List<FetchRequest> started = [];
  final List<FetchRequest> prepared = [];

  @override
  Future<void> prepare(FetchRequest request) async => prepared.add(request);
  final Map<String, int> _steps = {};
  final Map<String, FetchRequest> _byId = {};
  int _n = 0;

  static String? _songIdFor(String title) => 'song-$title';

  @override
  Future<Result<FetchJob>> start(FetchRequest request) async {
    if (latency > Duration.zero) await Future<void>.delayed(latency);
    asks++;
    if (busy > 0) {
      busy--;
      return Err(ServerFailure(
        busyCode == 'daily_limit'
            ? 'That is all the songs for today.'
            : 'Too many songs at once. Try again in a minute.',
        statusCode: 429,
        code: busyCode,
      ));
    }
    started.add(request);
    final id = 'job${_n++}';
    _byId[id] = request;
    _steps[id] = 0;
    return Ok(FetchJob(id: id, state: FetchState.queued));
  }

  /// Where a song can be played straight from YouTube (the service can stream); `null` = it cannot.
  Uri? streamingAt;
  final List<FetchRequest> streamAsked = [];

  @override
  Uri? streamUrlFor(FetchRequest request) {
    streamAsked.add(request);
    return streamingAt;
  }

  @override
  Uri? streamUri(FetchJob job) =>
      job.stream == null ? null : Uri.parse('http://svc${job.stream}');

  @override
  Future<Result<FetchJob>> status(String id) async {
    if (latency > Duration.zero) await Future<void>.delayed(latency);
    final step = _steps[id] = (_steps[id] ?? 0) + 1;
    if (step <= script.length) {
      return Ok(FetchJob(
        id: id,
        state: script[step - 1],
        stream:
            streamWhileDownloading && script[step - 1] == FetchState.downloading
                ? '/api/play/$id/audio'
                : null,
      ));
    }
    if (refused > 0) {
      refused--;
      return const Ok(FetchJob(
        id: 'refused',
        state: FetchState.failed,
        error: 'blocked',
        message:
            'The server could not get this song just now. Try again in a few minutes.',
      ));
    }
    if (fail != null) return Ok(fail!);
    final request = _byId[id]!;
    return Ok(FetchJob(
      id: id,
      state: FetchState.ready,
      songId: songIdFor(request.title),
      stream: streams ? '/api/play/$id/audio' : null,
    ));
  }
}

CatalogueTrack _t(String id, String title, {int? no}) => CatalogueTrack(
      id: id,
      title: title,
      artistName: 'Opeth',
      albumTitle: 'Damnation',
      albumId: '5',
      duration: const Duration(minutes: 4),
      previewUrl: 'https://cdn/p.mp3',
      trackNumber: no,
    );

InstantPlayService _service(
  _FakeBackend backend, {
  Future<String?> Function(String, String)? finder,
  Future<TrackRow?> Function(String songId)? load,
}) =>
    InstantPlayService(
      backend: backend,
      matcher: null,
      loadSong: load ??
          (songId) async => trackRow(songId, title: songId.substring(5)),
      findSongId: finder,
      pollEvery: Duration.zero,
      timeout: const Duration(seconds: 150),
      delay: (_) async {},
    );

void main() {
  group('InstantPlayService', () {
    test('walks the job to a library track, with the catalogue details',
        () async {
      final backend = _FakeBackend();
      final events =
          await _service(backend).fetch(_t('1', 'Windowpane', no: 5)).toList();

      final stages = [for (final e in events) e.stage];
      expect(stages.first, FetchState.queued);
      expect(stages, contains(FetchState.searching));
      expect(stages, contains(FetchState.downloading));
      expect(events.last.isReady, isTrue);
      expect(events.last.track!.id, 'song-Windowpane');

      final sent = backend.started.single;
      expect(sent.artist, 'Opeth');
      expect(sent.album, 'Damnation');
      expect(sent.trackNumber, 5);
      expect(sent.durationSec, 240);
    });

    group('how often it asks whether the song is ready', () {
      test('quickly in the first seconds, calmly afterwards', () async {
        final waited = <Duration>[];
        final service = InstantPlayService(
          backend: _FakeBackend(),
          matcher: null,
          loadSong: (id) async => trackRow(id, title: id.substring(5)),
          delay: (d) async => waited.add(d),
        );

        await service.fetch(_t('1', 'Windowpane')).toList();

        expect(waited.first, const Duration(milliseconds: 300),
            reason: 'the person is waiting: ask again at once');
        expect(waited.every((d) => d <= const Duration(milliseconds: 1200)),
            isTrue);
      });

      test('later it asks calmly, and the timeout still ends the wait',
          () async {
        final waited = <Duration>[];
        final service = InstantPlayService(
          backend: _FakeBackend(
              fail: const FetchJob(id: 'x', state: FetchState.downloading)),
          matcher: null,
          loadSong: (id) async => trackRow(id, title: id.substring(5)),
          timeout: const Duration(seconds: 30),
          delay: (d) async => waited.add(d),
        );

        await service.fetch(_t('1', 'Never')).toList();

        expect(waited.where((d) => d == const Duration(milliseconds: 1200)),
            isNotEmpty,
            reason: 'after the first seconds the questions are 1.2 s apart');
        final total = waited.fold(Duration.zero, (a, b) => a + b);
        expect(total, lessThan(const Duration(seconds: 45)));
      });
    });

    group('when YouTube refuses the server for a while', () {
      InstantPlayService serviceWith(
              _FakeBackend backend, List<Duration> waited) =>
          InstantPlayService(
            backend: backend,
            matcher: null,
            loadSong: (id) async => trackRow(id, title: id.substring(5)),
            pollEvery: Duration.zero,
            delay: (d) async => waited.add(d),
          );

      test('a tapped song waits and is asked for again by itself', () async {
        final backend = _FakeBackend(refused: 2);
        final waited = <Duration>[];

        final events = await serviceWith(backend, waited)
            .fetch(_t('1', 'Windowpane'))
            .toList();

        expect(events.last.isReady, isTrue);
        expect(backend.started, hasLength(3),
            reason: 'refused twice, then it came');
        expect(waited.where((d) => d >= const Duration(seconds: 20)),
            hasLength(2));
        expect(events.where((e) => e.isFailed), isEmpty,
            reason: 'the person never saw "try again in a few minutes"');
      });

      test('after a few tries the person is told, in the service words',
          () async {
        final backend = _FakeBackend(refused: 100);
        final waited = <Duration>[];

        final events = await serviceWith(backend, waited)
            .fetch(_t('1', 'Windowpane'))
            .toList();

        expect(events.last.isFailed, isTrue);
        expect(events.last.message, contains('Try again in a few minutes'));
        expect(events.last.error, 'blocked');
        expect(backend.started, hasLength(4),
            reason: 'the first ask and three more');
      });
    });

    group('when the service is busy with the person\'s other songs', () {
      InstantPlayService serviceWith(
              _FakeBackend backend, List<Duration> waited) =>
          InstantPlayService(
            backend: backend,
            matcher: null,
            loadSong: (id) async => trackRow(id, title: id.substring(5)),
            pollEvery: Duration.zero,
            delay: (d) async => waited.add(d),
          );

      test('the app waits and asks again by itself, then the song arrives',
          () async {
        final backend = _FakeBackend(busy: 2);
        final waited = <Duration>[];

        final events = await serviceWith(backend, waited)
            .fetch(_t('1', 'Windowpane'))
            .toList();

        expect(events.last.isReady, isTrue);
        expect(backend.asks, 3, reason: 'two busy answers, then the song');
        expect(
            waited.where((d) => d >= const Duration(seconds: 5)), hasLength(2),
            reason: 'it waited between the asks, the person did nothing');
        expect(events.where((e) => e.isFailed), isEmpty,
            reason: 'the person never saw "try again in a minute"');
        expect(events.first.label, 'Waiting');
      });

      test('a service that stays busy is given up on, in its own words',
          () async {
        final backend = _FakeBackend(busy: 100);
        final waited = <Duration>[];

        final events = await serviceWith(backend, waited)
            .fetch(_t('1', 'Windowpane'))
            .toList();

        expect(events.last.isFailed, isTrue);
        expect(events.last.message,
            'Too many songs at once. Try again in a minute.');
        final total = waited.fold(Duration.zero, (a, b) => a + b);
        expect(total, lessThanOrEqualTo(const Duration(minutes: 3)));
        expect(total, greaterThanOrEqualTo(const Duration(minutes: 1)));
      });

      test(
          'the limit for the day is not waited out: it will not change in a '
          'minute', () async {
        final backend = _FakeBackend(busy: 1, busyCode: 'daily_limit');
        final waited = <Duration>[];

        final events = await serviceWith(backend, waited)
            .fetch(_t('1', 'Windowpane'))
            .toList();

        expect(events.last.isFailed, isTrue);
        expect(events.last.message, 'That is all the songs for today.');
        expect(backend.asks, 1);
        expect(waited, isEmpty);
      });
    });

    test('a failed job carries the service\'s own sentence', () async {
      final backend = _FakeBackend(
          fail: const FetchJob(
              id: 'x',
              state: FetchState.failed,
              error: 'not_found',
              message: 'Could not find that song on YouTube.'));
      final events = await _service(backend).fetch(_t('1', 'Nothing')).toList();
      expect(events.last.isFailed, isTrue);
      expect(events.last.error, 'not_found');
      expect(events.last.message, 'Could not find that song on YouTube.');
    });

    test('a song the server has not listed yet is looked up by name', () async {
      var asked = 0;
      final backend = _FakeBackend(songIdFor: (_) => null);
      final events = await _service(
        backend,
        finder: (artist, title) async => ++asked < 3 ? null : 'song-found',
        load: (id) async => trackRow(id, title: 'Windowpane'),
      ).fetch(_t('1', 'Windowpane')).toList();
      expect(asked, 3);
      expect(events.last.isReady, isTrue);
      expect(events.last.track!.id, 'song-found');
    });

    test('a song the library has not listed yet plays from the service',
        () async {
      final backend = _FakeBackend(songIdFor: (_) => null, streams: true);
      final events =
          await _service(backend).fetch(_t('1', 'Windowpane')).toList();
      expect(events.last.isReady, isTrue);
      expect(events.last.track, isNull);
      expect(
          events.last.streamUri.toString(), 'http://svc/api/play/job0/audio');
    });

    test('a song that is still downloading plays as soon as it can', () async {
      final backend =
          _FakeBackend(songIdFor: (_) => null, streamWhileDownloading: true);
      final events =
          await _service(backend).fetch(_t('1', 'Windowpane')).toList();
      expect(events.last.isReady, isTrue);
      expect(events.last.streamUri, isNotNull);
      // It did not wait for the job to finish: only the first states ran.
      expect(events.map((e) => e.stage), [
        FetchState.queued,
        FetchState.queued,
        FetchState.searching,
        FetchState.ready
      ]);
    });

    test('the library copy wins when both are there', () async {
      final backend = _FakeBackend(streams: true);
      final events =
          await _service(backend).fetch(_t('1', 'Windowpane')).toList();
      expect(events.last.track, isNotNull);
    });

    test('without any id the person is told it will arrive', () async {
      final backend = _FakeBackend(songIdFor: (_) => null);
      final events =
          await _service(backend).fetch(_t('1', 'Windowpane')).toList();
      expect(events.last.isFailed, isTrue);
      expect(events.last.error, 'indexing');
    });

    test('a service that cannot be started is a failed row, not an exception',
        () async {
      final events = await InstantPlayService(
        backend: _Broken(),
        matcher: null,
        loadSong: (id) async => null,
      ).fetch(_t('1', 'X')).toList();
      expect(events.last.isFailed, isTrue);
      expect(events.last.message, contains('Cannot reach'));
    });
  });

  group('a song too long to keep is streamed (P1-02)', () {
    CatalogueTrack long(Duration length) => CatalogueTrack(
          id: 'surah',
          title: 'Surat Al-Baqarah',
          artistName: 'Reciter',
          duration: length,
          videoId: 'dQw4w9WgXcQ',
        );

    test('a recitation of two hours plays from the stream: no job, no download',
        () async {
      final backend = _FakeBackend()
        ..streamingAt = Uri.parse('http://svc/api/stream?videoId=dQw4w9WgXcQ');

      final events = await _service(backend)
          .fetch(long(const Duration(hours: 2, minutes: 21)))
          .toList();

      expect(events.last.isReady, isTrue);
      expect(events.last.streamUri,
          Uri.parse('http://svc/api/stream?videoId=dQw4w9WgXcQ'));
      expect(events.last.track, isNull,
          reason: 'it is not in the library and is not put there');
      expect(backend.started, isEmpty,
          reason: 'no job: nothing is downloaded, so no length limit applies');
      expect(backend.streamAsked.single.videoId, 'dQw4w9WgXcQ');
      expect(backend.streamAsked.single.durationSec, 8460);
    });

    test('an ordinary song still goes through the library', () async {
      final backend = _FakeBackend()
        ..streamingAt = Uri.parse('http://svc/api/stream');

      await _service(backend).fetch(_t('1', 'Windowpane')).toList();

      expect(backend.started, hasLength(1));
      expect(backend.streamAsked, isEmpty);
    });

    test('a service that cannot stream falls back to the old way', () async {
      final backend = _FakeBackend(); // streamingAt stays null

      final events = await _service(backend)
          .fetch(long(const Duration(hours: 1)))
          .toList();

      expect(backend.started, hasLength(1));
      expect(events.last.isReady || events.last.isFailed, isTrue);
    });

    test('a song being added in the background is not streamed', () async {
      final backend = _FakeBackend()
        ..streamingAt = Uri.parse('http://svc/api/stream');

      await _service(backend)
          .fetch(long(const Duration(hours: 1)), bulk: true)
          .toList();

      expect(backend.streamAsked, isEmpty);
    });
  });

  test('a refused login is its own code and says what to do (P2-18)', () async {
    final events = await InstantPlayService(
      backend: _Broken(failure: const AuthFailure('refused')),
      matcher: null,
      loadSong: (id) async => null,
    ).fetch(_t('1', 'X')).toList();

    expect(events.last.isFailed, isTrue);
    expect(events.last.error, 'login');
    expect(events.last.message, contains('Sign in again'));
  });

  group('InstantController', () {
    Future<_Opened> open(WidgetTester tester, _FakeBackend backend,
        {List<Override> more = const []}) async {
      final app = await pumpApp(tester, overrides: [
        catalogueClientProvider.overrideWithValue(FakeCatalogue()),
        instantPlayServiceProvider
            .overrideWith((ref) async => _service(backend)),
        ...more,
      ]);
      final element = tester.element(find.byType(Scaffold).first);
      final container = ProviderScope.containerOf(element);
      return _Opened(
        db: app.db,
        facade: app.facade,
        backend: backend,
        controller: container.read(instantControllerProvider.notifier),
      );
    }

    group('in a Jam', () {
      testWidgets(
          'a tapped song is added to the Jam by name: nothing is fetched here '
          '(the phone that plays gets it)', (tester) async {
        final backend = _FakeBackend();
        final s = await open(tester, backend, more: [
          jamControllerProvider.overrideWith(_InAJam.new),
        ]);

        await tester.runAsync(() => s.controller.play(_t('1', 'Windowpane')));

        expect(backend.started, isEmpty, reason: 'no fetch on this phone');
        expect(s.facade.calls, ['previews(1, start=0)'],
            reason: 'handed to the player, which in a Jam is the Jam player');
        await closeApp(tester, s.db);
      });

      testWidgets(
          'the phone that makes the sound fetches a song of the Jam it does '
          'not have: it is not added to the Jam again', (tester) async {
        // Seen on two real phones (2026-10-17): the host's phone, asked to play
        // a friend's song it did not have, added it to the Jam instead, which
        // asked it to play it again, 500 times.
        final backend = _FakeBackend();
        final s = await open(tester, backend, more: [
          jamControllerProvider.overrideWith(_InAJam.new),
        ]);

        await tester.runAsync(() => s.controller.play(_t('1', 'Windowpane'),
            sourceName: 'Jam', sourceId: 'jam', onThisPhone: true));

        expect(backend.started, isNotEmpty, reason: 'fetched for this phone');
        expect(s.facade.calls.where((c) => c.startsWith('previews')), isEmpty,
            reason: 'nothing is sent to the Jam');
        await closeApp(tester, s.db);
      });

      testWidgets('a run (an album) adds only the tapped song', (tester) async {
        final backend = _FakeBackend();
        final s = await open(tester, backend, more: [
          jamControllerProvider.overrideWith(_InAJam.new),
        ]);

        await tester.runAsync(() => s.controller.playRun(
            [_t('1', 'One', no: 1), _t('2', 'Two', no: 2)],
            startIndex: 1, sourceName: 'Damnation', sourceId: 'catalogue:5'));

        expect(backend.started, isEmpty);
        expect(s.facade.calls, ['previews(2, start=0)']);
        await closeApp(tester, s.db);
      });
    });

    testWidgets('play starts the song once it is ready', (tester) async {
      final s = await open(tester, _FakeBackend());
      await tester.runAsync(() => s.controller.play(_t('1', 'Windowpane')));
      expect(s.facade.calls.where((c) => c.startsWith('playTracks')),
          ['playTracks(1, start=0, source=Damnation, shuffle=false)']);
      await closeApp(tester, s.db);
    });

    testWidgets(
        'a run starts with the tapped song and queues the rest in '
        'order', (tester) async {
      final s = await open(tester, _FakeBackend());
      final tracks = [
        _t('1', 'One', no: 1),
        _t('2', 'Two', no: 2),
        _t('3', 'Three', no: 3),
      ];
      await tester.runAsync(() => s.controller.playRun(tracks,
          startIndex: 1, sourceName: 'Damnation', sourceId: 'catalogue:5'));

      // Two, then Three, then One (the order of the album from the tap on).
      expect(s.facade.calls, [
        'playTracks(1, start=0, source=Damnation, shuffle=false)',
        'queue(song-Three)',
        'queue(song-One)',
      ]);
      await closeApp(tester, s.db);
    });

    testWidgets(
        'only the tapped song is asked for as "now"; the rest of the run is '
        'bulk', (tester) async {
      final s = await open(tester, _FakeBackend());
      final tracks = [
        _t('1', 'One', no: 1),
        _t('2', 'Two', no: 2),
        _t('3', 'Three', no: 3),
      ];
      await tester.runAsync(() => s.controller.playRun(tracks,
          startIndex: 1, sourceName: 'Damnation', sourceId: 'catalogue:5'));
      final byTitle = {for (final r in s.backend.started) r.title: r.bulk};
      expect(byTitle, {'Two': false, 'Three': true, 'One': true});
      await closeApp(tester, s.db);
    });

    testWidgets(
        'says that more songs are on their way while a run still fetches them',
        (tester) async {
      final s = await open(
          tester, _FakeBackend(latency: const Duration(milliseconds: 40)));
      final tracks = [
        _t('1', 'One', no: 1),
        _t('2', 'Two', no: 2),
        _t('3', 'Three', no: 3),
      ];
      expect(s.controller.fetchingMore, isFalse);

      await tester.runAsync(() async {
        final run = s.controller.playRun(tracks,
            startIndex: 0, sourceName: 'Damnation', sourceId: 'catalogue:5');
        await Future<void>.delayed(const Duration(milliseconds: 100));
        expect(s.controller.fetchingMore, isTrue,
            reason: 'song 1 is on, songs 2 and 3 are still being fetched');
        await run;
      });

      expect(s.controller.fetchingMore, isFalse, reason: 'the run is over');
      await closeApp(tester, s.db);
    });

    testWidgets('a song tapped on its own is not a run still in progress',
        (tester) async {
      final s = await open(
          tester, _FakeBackend(latency: const Duration(milliseconds: 40)));
      await tester.runAsync(() async {
        final run = s.controller.playRun(
            [_t('1', 'One', no: 1), _t('2', 'Two', no: 2)],
            startIndex: 0, sourceName: 'Damnation', sourceId: 'catalogue:5');
        await Future<void>.delayed(const Duration(milliseconds: 60));
        final other = s.controller.play(_t('9', 'Nine'));
        await Future<void>.delayed(const Duration(milliseconds: 10));
        expect(s.controller.fetchingMore, isFalse,
            reason: 'the person chose something else: nothing more is coming');
        await Future.wait([run, other]);
      });
      await closeApp(tester, s.db);
    });

    testWidgets('adding a whole album to the library is all bulk',
        (tester) async {
      final s = await open(tester, _FakeBackend());
      await tester.runAsync(() =>
          s.controller.addAll([_t('1', 'One', no: 1), _t('2', 'Two', no: 2)]));
      expect(s.backend.started.map((r) => r.bulk), [true, true]);
      await closeApp(tester, s.db);
    });

    group('a run only fetches as far ahead as the queue needs', () {
      final tracks = [for (var i = 1; i <= 6; i++) _t('$i', 'Song$i', no: i)];

      Future<void> settle() =>
          Future<void>.delayed(const Duration(milliseconds: 40));

      testWidgets('two songs wait behind the one playing', (tester) async {
        final s = await open(tester, _FakeBackend());
        s.facade.simulateQueue = true;
        late Future<void> run;
        await tester.runAsync(() async {
          run = s.controller.playRun(tracks,
              startIndex: 0, sourceName: 'Album', sourceId: 'catalogue:1');
          await settle();
          // Song 1 playing, songs 2 and 3 waiting: nothing more asked for.
          expect(s.backend.started.map((r) => r.title),
              ['Song1', 'Song2', 'Song3']);

          s.facade.advance(); // song 2 now playing -> one more is needed
          await settle();
          expect(s.backend.started, hasLength(4));

          for (var i = 0; i < 3; i++) {
            s.facade.advance();
            await settle();
          }
          await run;
        });
        expect(s.backend.started, hasLength(6));
        expect(s.facade.queue.items.map((q) => q.title).toList(),
            ['Song1', 'Song2', 'Song3', 'Song4', 'Song5', 'Song6']);
        await closeApp(tester, s.db);
      });

      testWidgets('the run ends when the person plays something else',
          (tester) async {
        final s = await open(tester, _FakeBackend());
        s.facade.simulateQueue = true;
        late Future<void> run;
        await tester.runAsync(() async {
          run = s.controller.playRun(tracks,
              startIndex: 0, sourceName: 'Album', sourceId: 'catalogue:1');
          await settle();
          expect(s.backend.started, hasLength(3));

          // A library song replaces the queue.
          s.facade.emitQueue(QueueSnapshot(
              items: [QueueItem.fromTrack(trackRow('other'), uid: 99)],
              currentIndex: 0));
          s.facade.advance();
          await settle();
          await run; // returned instead of waiting for ever
        });
        expect(s.backend.started, hasLength(3));
        await closeApp(tester, s.db);
      });

      testWidgets('the run ends when songs are taken out of the queue',
          (tester) async {
        final s = await open(tester, _FakeBackend());
        s.facade.simulateQueue = true;
        late Future<void> run;
        await tester.runAsync(() async {
          run = s.controller.playRun(tracks,
              startIndex: 0, sourceName: 'Album', sourceId: 'catalogue:1');
          await settle();
          final q = s.facade.queue;
          s.facade.emitQueue(
              QueueSnapshot(items: q.items.take(1).toList(), currentIndex: 0));
          await settle();
          await run;
        });
        expect(s.backend.started, hasLength(3));
        await closeApp(tester, s.db);
      });
    });

    testWidgets(
        'a song is prepared once, and the service is asked as the '
        'same song a tap would ask for', (tester) async {
      final s = await open(tester, _FakeBackend());
      await tester.runAsync(() async {
        await s.controller.prepare(_t('1', 'Windowpane', no: 5));
        await s.controller.prepare(_t('1', 'Windowpane', no: 5));
        await s.controller.prepare(_t('2', 'Hope Leaves', no: 6));
      });
      expect(s.backend.prepared.map((r) => r.title),
          ['Windowpane', 'Hope Leaves']);
      expect(s.backend.prepared.first.album, 'Damnation');
      expect(s.backend.started, isEmpty, reason: 'nothing is downloaded');
      await closeApp(tester, s.db);
    });

    test('the request tells the service when it is bulk', () {
      const now = FetchRequest(artist: 'A', title: 'T');
      const bulk = FetchRequest(artist: 'A', title: 'T', bulk: true);
      expect(now.toJson().containsKey('priority'), isFalse);
      expect(bulk.toJson()['priority'], 'bulk');
    });

    testWidgets('a song that only the service has plays from its stream',
        (tester) async {
      final s = await open(
          tester, _FakeBackend(songIdFor: (_) => null, streams: true));
      await tester.runAsync(() => s.controller.play(_t('1', 'Windowpane')));
      expect(s.facade.calls, ['previews(1, start=0)']);
      await closeApp(tester, s.db);
    });

    testWidgets('a run of stream-only songs queues the rest as streams',
        (tester) async {
      final s = await open(
          tester, _FakeBackend(songIdFor: (_) => null, streams: true));
      final tracks = [_t('1', 'One', no: 1), _t('2', 'Two', no: 2)];
      await tester.runAsync(() => s.controller.playRun(tracks,
          startIndex: 0, sourceName: 'Damnation', sourceId: 'catalogue:5'));
      expect(s.facade.calls, ['previews(1, start=0)', 'queueStream(2)']);
      await closeApp(tester, s.db);
    });

    testWidgets('a second run makes the first stop queueing', (tester) async {
      final s = await open(
          tester, _FakeBackend(latency: const Duration(milliseconds: 4)));
      final first = [for (var i = 1; i <= 8; i++) _t('a$i', 'A$i')];
      final second = [_t('b1', 'B1')];

      await tester.runAsync(() async {
        final run1 = s.controller
            .playRun(first, startIndex: 0, sourceName: 'A', sourceId: 'a');
        await Future<void>.delayed(const Duration(milliseconds: 30));
        await s.controller
            .playRun(second, startIndex: 0, sourceName: 'B', sourceId: 'b');
        await run1;
      });

      expect(s.facade.calls.where((c) => c.startsWith('queue(song-A')).length,
          lessThan(7));
      expect(s.facade.calls,
          contains('playTracks(1, start=0, source=B, shuffle=false)'));
      await closeApp(tester, s.db);
    });

    testWidgets('a song already being fetched is not started twice',
        (tester) async {
      final s = await open(tester, _FakeBackend());
      await tester.runAsync(() async {
        await Future.wait([
          s.controller.fetch(_t('1', 'Windowpane')),
          s.controller.fetch(_t('1', 'Windowpane')),
        ]);
      });
      expect(s.backend.started, hasLength(1));
      await closeApp(tester, s.db);
    });
  });
}

/// A person who is in a Jam.
class _InAJam extends JamController {
  @override
  JamSession build() => const JamSession(
        phase: JamPhase.active,
        code: 'AB23CD',
        me: 'owner',
      );
}

class _Opened {
  _Opened({
    required this.db,
    required this.facade,
    required this.backend,
    required this.controller,
  });

  final AppDatabase db;
  final FakePlaybackFacade facade;
  final _FakeBackend backend;
  final InstantController controller;
}

class _Broken implements InstantPlayBackend {
  _Broken({this.failure = const NetworkFailure('no route')});

  final AppFailure failure;

  @override
  Future<void> prepare(FetchRequest request) async {}

  @override
  Future<Result<FetchJob>> start(FetchRequest request) async => Err(failure);

  @override
  Future<Result<FetchJob>> status(String id) async => Err(failure);

  @override
  Uri? streamUrlFor(FetchRequest request) => null;

  @override
  Uri? streamUri(FetchJob job) => null;
}
