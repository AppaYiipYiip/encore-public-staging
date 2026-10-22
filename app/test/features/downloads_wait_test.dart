import 'package:encore/app/providers.dart';
import 'package:encore/features/downloads/download_providers.dart';
import 'package:encore/features/settings/settings_controller.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class _Settings extends SettingsController {
  _Settings({required this.wifiOnly});
  final bool wifiOnly;

  @override
  AppSettings build() => AppSettings(wifiOnlyDownloads: wifiOnly);
}

/// Owner, 2026-10-22: a download that did not move said "Downloading 0 of 10" for ever. It was waiting for Wi-Fi (the phone was on mobile
/// data and the person had chosen Wi-Fi only): say so.
void main() {
  Future<String?> waitFor({
    required bool wifiOnly,
    required NetworkKind network,
  }) async {
    final container = ProviderContainer(overrides: [
      settingsProvider.overrideWith(() => _Settings(wifiOnly: wifiOnly)),
      networkKindProvider.overrideWith((ref) => Stream.value(network)),
    ]);
    addTearDown(container.dispose);
    container.listen(networkKindProvider, (_, __) {});
    await container.read(networkKindProvider.future);
    return container.read(downloadsWaitProvider);
  }

  test('Wi-Fi only on mobile data waits for Wi-Fi', () async {
    expect(await waitFor(wifiOnly: true, network: NetworkKind.mobile),
        'Waiting for Wi-Fi');
  });

  test('Wi-Fi only on Wi-Fi does not wait', () async {
    expect(await waitFor(wifiOnly: true, network: NetworkKind.wifi), isNull);
  });

  test('mobile data allowed does not wait', () async {
    expect(await waitFor(wifiOnly: false, network: NetworkKind.mobile), isNull);
  });

  test('no connection at all waits for one, whatever the setting', () async {
    expect(await waitFor(wifiOnly: false, network: NetworkKind.none),
        'Waiting for a connection');
  });
}
