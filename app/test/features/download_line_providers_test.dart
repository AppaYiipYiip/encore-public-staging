import 'dart:async';

import 'package:dio/dio.dart';
import 'package:encore/app/connection.dart'
    show ServerReachability, serverReachabilityProvider;
import 'package:encore/app/providers.dart';
import 'package:encore/core/clock.dart';
import 'package:encore/data/encore/encore_api.dart';
import 'package:encore/data/encore/encore_live.dart';
import 'package:encore/data/encore/encore_models.dart';
import 'package:encore/data/repos/downloads_repository.dart';
import 'package:encore/domain/download_line.dart';
import 'package:encore/domain/storage_guard.dart';
import 'package:encore/features/downloads/download_line_providers.dart';
import 'package:encore/features/downloads/download_providers.dart';
import 'package:encore/features/downloads/keep_providers.dart';
import 'package:encore/features/instant/release_save.dart';
import 'package:encore/features/settings/settings_controller.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';

import '../support/fake_encore_server.dart';
import '../support/reachability.dart';

class _Settings extends SettingsController {
  _Settings({required this.wifiOnly});
  final bool wifiOnly;

  @override
  AppSettings build() => AppSettings(wifiOnlyDownloads: wifiOnly);
}

/// The line under a download, put together from the phone's table, the server's answer and the phone's reason to wait (P2-22 part 2, docs/design S-16).
void main() {
  late FakeEncoreServer server;
  late EncoreApi api;
  late StreamController<LiveEvent> events;
  late StreamController<bool> connection;
  late FakeClock clock;

  const playlist = DownloadTarget.pin(PinTargetType.playlist, 'pl_1');

  Map<String, Object?> groupJson(String kind, String id,
          {int total = 217,
          int ready = 0,
          int keeping = 0,
          int queued = 0,
          int failed = 0}) =>
      {
        'kind': kind,
        'id': id,
        'total': total,
        'ready': ready,
        'keeping': keeping,
        'queued': queued,
        'failed': failed,
        'retryable': failed,
        'failures': <Object?>[],
      };

  setUp(() {
    server = FakeEncoreServer();
    api = EncoreApi(
      dio: Dio()..httpClientAdapter = server.adapter,
      baseUrl: () => Uri.parse('http://home.test:4540'),
      auth: () => {'u': 'tester', 't': 'tok', 's': 's'},
      deviceId: 'dv_phone',
    );
    events = StreamController<LiveEvent>.broadcast();
    connection = StreamController<bool>.broadcast();
    clock = FakeClock(DateTime(2026, 11, 6, 20, 0));
  });

  tearDown(() async {
    await events.close();
    await connection.close();
  });

  Future<ProviderContainer> start({
    required PinState phone,
    bool onEncore = true,
    bool away = false,
    ServerReachability? reach,
    NetworkKind network = NetworkKind.wifi,
    bool wifiOnly = false,
    StorageVerdict verdict = StorageVerdict.ok,
    List<KeepGroupKey> groups = const [KeepGroupKey('playlist', 'pl_1')],
    List<Override> more = const [],
  }) async {
    final c = ProviderContainer(overrides: [
      // The storage guard belongs to the real download manager, which these tests do not build.
      downloadVerdictProvider.overrideWith((ref) => Stream.value(verdict)),
      keepApiProvider.overrideWithValue(onEncore ? api : null),
      keepEventsProvider.overrideWithValue(events.stream),
      keepConnectionProvider.overrideWithValue(connection.stream),
      keepGroupsProvider.overrideWithValue(groups),
      keepDebounceProvider.overrideWithValue(Duration.zero),
      clockProvider.overrideWithValue(clock),
      pinStateProvider.overrideWith((ref, arg) => Stream.value(phone)),
      serverReachabilityProvider.overrideWith(() => FixedReachability(reach ??
          (away ? ServerReachability.serverAway : ServerReachability.ok))),
      networkKindProvider.overrideWith((ref) => Stream.value(network)),
      settingsProvider.overrideWith(() => _Settings(wifiOnly: wifiOnly)),
      ...more,
    ]);
    addTearDown(c.dispose);
    c.listen(keepProvider, (_, __) {});
    c.listen(networkKindProvider, (_, __) {});
    c.listen(downloadVerdictProvider, (_, __) {});
    await c.read(downloadVerdictProvider.future);
    c.listen(pinStateProvider((PinTargetType.playlist, 'pl_1')), (_, __) {});
    await c.read(networkKindProvider.future);
    await c.read(pinStateProvider((PinTargetType.playlist, 'pl_1')).future);
    for (var i = 0; i < 200; i++) {
      final k = c.read(keepProvider);
      if (k.answered || (onEncore && k.supported == false && i > 20)) break;
      if (!onEncore) break;
      await Future<void>.delayed(const Duration(milliseconds: 5));
    }
    return c;
  }

  PinState phone({int done = 0, int total = 217, int active = 0}) =>
      PinState(pinned: true, total: total, done: done, active: active);

  group('a server that keeps songs', () {
    test('both numbers: the phone\'s own table and what the server says',
        () async {
      server.keepGroups['playlist:pl_1'] =
          groupJson('playlist', 'pl_1', ready: 40, keeping: 1, queued: 176);

      final c = await start(phone: phone(done: 12, active: 3));

      expect(c.read(downloadLineProvider(playlist))?.text,
          '12 of 217 on this phone · 40 ready on your server');
    });

    test(
        'the phone\'s reason replaces the server\'s half, for the whole screen',
        () async {
      server.keepGroups['playlist:pl_1'] =
          groupJson('playlist', 'pl_1', ready: 40, queued: 177);

      final wifi = await start(
          phone: phone(done: 12, active: 3),
          network: NetworkKind.mobile,
          wifiOnly: true);
      expect(wifi.read(downloadLineProvider(playlist))?.text,
          '12 of 217 on this phone · waiting for Wi-Fi');

      final none = await start(
          phone: phone(done: 12, active: 3), network: NetworkKind.none);
      expect(none.read(downloadLineProvider(playlist))?.text,
          '12 of 217 on this phone · waiting for a connection');

      final silent = await start(phone: phone(done: 12, active: 3), away: true);
      expect(silent.read(downloadLineProvider(playlist))?.text,
          '12 of 217 on this phone · waiting for your server');
    });

    test(
        'while YouTube rests the time is the one the server gave, worked out once',
        () async {
      server.keepGroups['playlist:pl_1'] =
          groupJson('playlist', 'pl_1', total: 9, ready: 3, queued: 6);
      server.keepYoutube = {'state': 'resting', 'resumesInSec': 5400};

      final c = await start(phone: phone(done: 3, total: 9, active: 1));
      expect(c.read(downloadLineProvider(playlist))?.text,
          '3 of 9 on this phone · your server is resting until 21:30');

      clock.advance(const Duration(minutes: 20));
      c.invalidate(downloadLineProvider(playlist));
      expect(c.read(downloadLineProvider(playlist))?.text,
          '3 of 9 on this phone · your server is resting until 21:30',
          reason: 'the clock moving on does not move the time the rest ends');
    });

    test('before the server has answered the phone says only what it has',
        () async {
      final c = await start(phone: phone(done: 12, active: 3));
      // the fake knows no such download: it is left out, as on the real server
      expect(c.read(downloadLineProvider(playlist))?.text,
          '12 of 217 on this phone');
      expect(c.read(keepProvider).missing,
          {const KeepGroupKey('playlist', 'pl_1')});
    });

    test('a catalogue release is one download made of the pins of its songs',
        () async {
      server.keepGroups['release:cat:9'] =
          groupJson('release', 'cat:9', total: 2, ready: 2);
      const release = DownloadTarget.release('cat:9', ['sr_a', 'sr_b']);

      final c = await start(
        phone: phone(),
        groups: const [
          KeepGroupKey('release', 'cat:9', refs: ['sr_a', 'sr_b'])
        ],
        more: [
          releasePinStateProvider.overrideWith((ref, joined) =>
              const PinState(pinned: true, total: 2, done: 1, active: 1)),
        ],
      );

      expect(c.read(downloadLineProvider(release))?.text,
          'Downloading to this phone · 1 of 2');
    });

    test(
        'what the server does not keep for the person keeps the lines it always had',
        () async {
      final c = await start(phone: phone(done: 4, total: 10, active: 3));

      const album = DownloadTarget.pin(PinTargetType.album, 'al_1');
      c.listen(pinStateProvider((PinTargetType.album, 'al_1')), (_, __) {});
      await c.read(pinStateProvider((PinTargetType.album, 'al_1')).future);
      expect(c.read(downloadLineProvider(album))?.text, 'Downloading 4 of 10');
    });
  });

  test('a download the person has not made has no line', () async {
    final c = await start(phone: PinState.none);

    expect(c.read(downloadLineProvider(playlist)), isNull);
  });

  group('a plain music server', () {
    test('shows exactly the lines the app has always shown', () async {
      final c = await start(
          phone: phone(done: 4, total: 10, active: 3), onEncore: false);

      expect(
          c.read(downloadLineProvider(playlist))?.text, 'Downloading 4 of 10');
    });

    test('and its waiting words', () async {
      final c = await start(
          phone: phone(done: 4, total: 10, active: 3),
          onEncore: false,
          network: NetworkKind.none);

      expect(c.read(downloadLineProvider(playlist))?.text,
          'Waiting for a connection • 4 of 10');
    });

    test('a silent server is not a reason a plain server ever gave', () async {
      final c = await start(
          phone: phone(done: 4, total: 10, active: 3),
          onEncore: false,
          away: true);

      expect(
          c.read(downloadLineProvider(playlist))?.text, 'Downloading 4 of 10');
    });
  });

  group('a server that keeps songs but does not list it', () {
    test('is treated as a plain one', () async {
      server.hasKeep = false;

      final c = await start(phone: phone(done: 4, total: 10, active: 3));
      await Future<void>.delayed(const Duration(milliseconds: 50));

      expect(
          c.read(downloadLineProvider(playlist))?.text, 'Downloading 4 of 10');
    });
  });

  test(
      'a paused queue is the phone reason too, after the connection and the server',
      () async {
    final limited = await start(
        phone: phone(done: 12, active: 3),
        verdict: StorageVerdict.limitReached);
    expect(limited.read(phoneWaitProvider), PhoneWait.limit);

    final full = await start(
        phone: phone(done: 12, active: 3), verdict: StorageVerdict.lowSpace);
    expect(full.read(phoneWaitProvider), PhoneWait.space);

    final away = await start(
        phone: phone(done: 12, active: 3),
        away: true,
        verdict: StorageVerdict.limitReached);
    expect(away.read(phoneWaitProvider), PhoneWait.server,
        reason: 'one cause: the server first');
  });

  test('the phone\'s reason is the same test the strip uses', () async {
    final c =
        await start(phone: phone(), network: NetworkKind.none, away: true);

    expect(c.read(phoneWaitProvider), PhoneWait.connection,
        reason:
            'no network at all is "a connection", before it is "your server"');
  });

  test(
      'a network on which Android found no internet (4G with no data) is "a connection", the word of the strip, and not "your server"',
      () async {
    final c = await start(phone: phone(), reach: ServerReachability.noInternet);

    expect(c.read(phoneWaitProvider), PhoneWait.connection,
        reason:
            'the strip says offline there; the line under a download must not say "waiting for your server"');
  });
}
