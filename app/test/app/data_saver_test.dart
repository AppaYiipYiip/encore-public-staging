import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:encore/app/playback_providers.dart' show prepareAheadSongs;
import 'package:encore/app/providers.dart';
import 'package:encore/core/cover_sizes.dart';
import 'package:encore/data/db/app_database.dart' show ServerRow;
import 'package:encore/domain/audio_quality.dart';
import 'package:encore/features/settings/settings_controller.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class _Settings extends SettingsController {
  _Settings(this.initial);
  final AppSettings initial;

  @override
  AppSettings build() => initial;
}

/// P4-24: ONE switch and ONE derived value, "Data saver is in force" (the switch is on AND the phone is on mobile data). The advisor's rulings
/// (14 Nov 2026): only a mobile-data link makes it true; Ethernet, no connection and a VPN over Wi-Fi do not.
void main() {
  group('the one rule', () {
    test('only the switch on AND a mobile link make it true', () {
      for (final kind in NetworkKind.values) {
        expect(dataSaverInForce(switchOn: true, network: kind),
            kind == NetworkKind.mobile,
            reason: 'switch on, $kind');
        expect(dataSaverInForce(switchOn: false, network: kind), isFalse,
            reason: 'switch off, $kind: nothing changes');
      }
    });
  });

  group('what the platform says about the link', () {
    test('a mobile link is mobile, with or without a VPN over it', () {
      expect(networkKindOf([ConnectivityResult.mobile]), NetworkKind.mobile);
      expect(networkKindOf([ConnectivityResult.mobile, ConnectivityResult.vpn]),
          NetworkKind.mobile);
    });

    test('Wi-Fi, Ethernet and a VPN over Wi-Fi are never mobile', () {
      expect(networkKindOf([ConnectivityResult.wifi]), NetworkKind.wifi);
      expect(networkKindOf([ConnectivityResult.ethernet]), NetworkKind.wifi);
      expect(networkKindOf([ConnectivityResult.vpn, ConnectivityResult.wifi]),
          NetworkKind.wifi);
      expect(
          networkKindOf([ConnectivityResult.mobile, ConnectivityResult.wifi]),
          NetworkKind.wifi,
          reason: 'Wi-Fi wins when both are up');
    });

    test('a VPN alone, or something the app does not know, is not mobile', () {
      expect(networkKindOf([ConnectivityResult.vpn]), NetworkKind.wifi);
      expect(networkKindOf([ConnectivityResult.other]), NetworkKind.wifi);
    });

    test('no connection is none', () {
      expect(networkKindOf([]), NetworkKind.none);
      expect(networkKindOf([ConnectivityResult.none]), NetworkKind.none);
    });
  });

  group('the platform can report mobile data', () {
    test('Android and iOS can; a browser and a desktop cannot', () {
      expect(
          mobileDataReportable(TargetPlatform.android, isWeb: false), isTrue);
      expect(mobileDataReportable(TargetPlatform.iOS, isWeb: false), isTrue);
      expect(mobileDataReportable(TargetPlatform.android, isWeb: true), isFalse,
          reason: 'a browser reports no connection type');
      expect(
          mobileDataReportable(TargetPlatform.windows, isWeb: false), isFalse);
      expect(mobileDataReportable(TargetPlatform.macOS, isWeb: false), isFalse);
      expect(mobileDataReportable(TargetPlatform.linux, isWeb: false), isFalse);
    });
  });

  group('the providers', () {
    Future<ProviderContainer> make({
      required bool switchOn,
      required NetworkKind network,
      AudioQuality wifi = AudioQuality.original,
      AudioQuality mobile = AudioQuality.high,
    }) async {
      final container = ProviderContainer(overrides: [
        settingsProvider.overrideWith(() => _Settings(AppSettings(
              dataSaver: switchOn,
              streamQualityWifi: wifi,
              streamQualityMobile: mobile,
            ))),
        networkKindProvider.overrideWith((ref) => Stream.value(network)),
      ]);
      addTearDown(container.dispose);
      container.listen(networkKindProvider, (_, __) {});
      await container.read(networkKindProvider.future);
      return container;
    }

    test('in force: the switch on, on mobile data', () async {
      final c = await make(switchOn: true, network: NetworkKind.mobile);
      expect(c.read(dataSaverInForceProvider), isTrue);
    });

    test('not in force: on Wi-Fi, offline, or with the switch off', () async {
      for (final (on, kind) in [
        (true, NetworkKind.wifi),
        (true, NetworkKind.none),
        (false, NetworkKind.mobile),
        (false, NetworkKind.wifi),
      ]) {
        final c = await make(switchOn: on, network: kind);
        expect(c.read(dataSaverInForceProvider), isFalse,
            reason: 'switch $on on $kind');
      }
    });

    test('before the first answer about the link it is not in force', () {
      final container = ProviderContainer(overrides: [
        settingsProvider
            .overrideWith(() => _Settings(const AppSettings(dataSaver: true))),
        networkKindProvider.overrideWith((ref) => const Stream.empty()),
      ]);
      addTearDown(container.dispose);
      expect(container.read(dataSaverInForceProvider), isFalse);
    });

    group('the quality the next stream is asked at', () {
      test('Wi-Fi: the Wi-Fi choice, whatever the switch says', () async {
        final c = await make(
            switchOn: true,
            network: NetworkKind.wifi,
            wifi: AudioQuality.original);
        expect(c.read(streamQualityProvider), AudioQuality.original);
      });

      test('mobile data, switch off: the mobile choice, as before', () async {
        final c = await make(
            switchOn: false,
            network: NetworkKind.mobile,
            mobile: AudioQuality.high);
        expect(c.read(streamQualityProvider), AudioQuality.high);
      });

      test('mobile data, switch on: the mobile choice held to Data saver',
          () async {
        final c = await make(
            switchOn: true,
            network: NetworkKind.mobile,
            mobile: AudioQuality.high);
        expect(c.read(streamQualityProvider), AudioQuality.dataSaver);
      });

      test('mobile data, switch on, a person who chose Compatible: still MP3',
          () async {
        final c = await make(
            switchOn: true,
            network: NetworkKind.mobile,
            mobile: AudioQuality.compatible);
        expect(c.read(streamQualityProvider), AudioQuality.compatible,
            reason: 'the cap never changes the codec');
      });

      test('the person\'s own choice is not touched', () async {
        final c = await make(
            switchOn: true,
            network: NetworkKind.mobile,
            mobile: AudioQuality.high);
        c.read(streamQualityProvider);
        expect(c.read(settingsProvider).streamQualityMobile, AudioQuality.high);
      });
    });
  });

  group(
      'the pictures: one derived value picks the budget of every cover widget',
      () {
    final server = ServerRow(
      id: 1,
      name: 'Home',
      username: 'tester',
      endpointsJson: '[]',
      capabilitiesJson: '{}',
      createdAtMs: 0,
      lastUsedAtMs: 0,
    );

    Future<CoverBudget?> budget({
      required bool switchOn,
      required NetworkKind network,
    }) async {
      final container = ProviderContainer(overrides: [
        settingsProvider
            .overrideWith(() => _Settings(AppSettings(dataSaver: switchOn))),
        networkKindProvider.overrideWith((ref) => Stream.value(network)),
        activeServerProvider.overrideWith((ref) => Stream.value(server)),
        sessionProvider.overrideWith((ref) => Future.value(null)),
      ]);
      addTearDown(container.dispose);
      container.listen(networkKindProvider, (_, __) {});
      container.listen(activeServerProvider, (_, __) {});
      await container.read(networkKindProvider.future);
      await container.read(activeServerProvider.future);
      return container.read(coverArtResolverProvider)?.budget;
    }

    test('in force: every widget asks for the small picture', () async {
      expect(await budget(switchOn: true, network: NetworkKind.mobile),
          CoverBudget.mobile);
    });

    test('not in force: the pictures are what they were', () async {
      for (final (on, kind) in [
        (true, NetworkKind.wifi),
        (false, NetworkKind.mobile),
        (false, NetworkKind.wifi),
      ]) {
        expect(await budget(switchOn: on, network: kind), CoverBudget.full,
            reason: 'switch $on on $kind');
      }
    });
  });

  test(
      'nothing is prepared beyond the next song while it is in force, two otherwise',
      () {
    expect(prepareAheadSongs(dataSaverInForce: true), 1);
    expect(prepareAheadSongs(dataSaverInForce: false), 2);
  });
}
