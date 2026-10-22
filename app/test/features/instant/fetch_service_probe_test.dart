import 'package:encore/app/providers.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/fetch/fetch_client.dart';
import 'package:encore/features/instant/instant_controller.dart';
import 'package:encore/features/settings/settings_controller.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

/// Owner, 2026-10-22: "when I click a song, only a snippet is working". One look for the instant-play service that failed (the server was busy with a
/// 130-song import) was remembered for the whole session, so every song fell back to its 30-second preview. A failed look is not an answer.

class _Settings extends SettingsController {
  _Settings(this._saved);
  final String? _saved;

  @override
  AppSettings build() => AppSettings(fetchServiceUrl: _saved);

  @override
  void setFetchServiceUrl(String? url) =>
      state = state.copyWith(fetchServiceUrl: url);
}

const _server = ServerRow(
  id: 1,
  name: 'Home',
  username: 'tester',
  endpointsJson: '[{"label":"Home","url":"http://192.168.1.2:4533"}]',
  capabilitiesJson: '{}',
  createdAtMs: 0,
  lastUsedAtMs: 0,
);

ProviderContainer containerWith({
  String? saved,
  required Future<FetchServiceInfo?> Function(Uri) probe,
  ServerRow server = _server,
}) {
  final container = ProviderContainer(overrides: [
    settingsProvider.overrideWith(() => _Settings(saved)),
    activeServerProvider.overrideWith((ref) => Stream.value(server)),
    fetchProbeProvider.overrideWithValue(probe),
    fetchProbeRetryProvider
        .overrideWithValue((misses) => const Duration(milliseconds: 50)),
  ]);
  // Nobody watches the provider in a test, so it is kept alive by hand (a provider with no listener is paused).
  container.listen(fetchServiceProvider, (_, __) {});
  container.listen(activeServerProvider, (_, __) {});
  addTearDown(container.dispose);
  return container;
}

const _canPlay = FetchServiceInfo(features: ['play-now', 'stream']);

void main() {
  test(
      'an Encore server is its own instant-play service: nothing is looked for',
      () async {
    var looks = 0;
    final container = containerWith(
      server: _server.copyWith(capabilitiesJson: '{"encore":true}'),
      probe: (uri) async {
        looks++;
        return null;
      },
    );

    final found = await container.read(fetchServiceProvider.future);

    expect(found.toString(), 'http://192.168.1.2:4533');
    expect(looks, 0);
  });

  test('a service that answers is found and remembered', () async {
    final container =
        containerWith(probe: (uri) async => uri.port == 8701 ? _canPlay : null);

    final found = await container.read(fetchServiceProvider.future);

    expect(found.toString(), 'http://192.168.1.2:8701');
    await Future<void>.delayed(Duration.zero);
    expect(container.read(settingsProvider).fetchServiceUrl,
        'http://192.168.1.2:8701');
  });

  test('a look that fails does not take away a service that was found before',
      () async {
    final container = containerWith(
        saved: 'http://192.168.1.2:8701', probe: (uri) async => null);

    final found = await container.read(fetchServiceProvider.future);

    expect(found.toString(), 'http://192.168.1.2:8701',
        reason:
            'the server is busy, not gone: songs must not fall back to 30-second previews');
  });

  test(
      'a service that never answered is looked for again, with pauses, and found when it comes up',
      () async {
    var up = false;
    var looks = 0;
    final container = containerWith(probe: (uri) async {
      looks++;
      return up && uri.port == 8701 ? _canPlay : null;
    });

    expect(await container.read(fetchServiceProvider.future), isNull);
    final firstRound = looks;
    up = true;
    await Future<void>.delayed(const Duration(milliseconds: 150));
    await container.read(fetchServiceProvider.future);

    expect(looks, greaterThan(firstRound), reason: 'it looked again by itself');
    expect(container.read(fetchServiceProvider).value.toString(),
        'http://192.168.1.2:8701');
  });

  test(
      'a service that answers but cannot play now (an older one) is not assumed',
      () async {
    final container = containerWith(
      saved: 'http://192.168.1.2:8701',
      probe: (uri) async => const FetchServiceInfo(features: ['request']),
    );

    expect(await container.read(fetchServiceProvider.future), isNull);
  });

  test('the pause before looking again grows to two minutes and stays there',
      () {
    expect([for (var i = 0; i < 7; i++) fetchProbeRetryAfter(i).inSeconds],
        [8, 16, 32, 64, 120, 120, 120]);
  });
}
