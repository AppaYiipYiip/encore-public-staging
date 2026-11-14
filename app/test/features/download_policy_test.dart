import 'package:encore/app/providers.dart';
import 'package:encore/data/downloads/download_manager.dart';
import 'package:encore/domain/audio_quality.dart';
import 'package:encore/features/downloads/download_providers.dart';
import 'package:encore/features/settings/settings_controller.dart';
import 'package:flutter_test/flutter_test.dart';

/// The glue between Settings, the link the phone is on and the download manager: the settings and `NetworkKind` become one `DownloadPolicy`
/// each time the manager schedules work. (The manager's own behaviour for each policy is in `data/downloads/download_manager_test.dart`.)
///
/// Owner, 13 Nov 2026: "downloads over Wi-Fi only, or also over mobile data (his choice)". Both cases, on Wi-Fi and on mobile data.
void main() {
  DownloadPolicy policy({
    required bool wifiOnly,
    required NetworkKind network,
    bool dataSaverInForce = false,
  }) =>
      downloadPolicyFor(
        settings: AppSettings(wifiOnlyDownloads: wifiOnly),
        network: network,
        dataSaverInForce: dataSaverInForce,
      );

  group('Download over Wi-Fi only', () {
    test('on: a download waits on mobile data and goes on Wi-Fi', () {
      expect(policy(wifiOnly: true, network: NetworkKind.mobile).mayTransfer,
          isFalse);
      expect(policy(wifiOnly: true, network: NetworkKind.wifi).mayTransfer,
          isTrue);
    });

    test('off: a download goes on mobile data too, and on Wi-Fi', () {
      expect(policy(wifiOnly: false, network: NetworkKind.mobile).mayTransfer,
          isTrue);
      expect(policy(wifiOnly: false, network: NetworkKind.wifi).mayTransfer,
          isTrue);
    });

    test(
        'it is on by default: nobody spends mobile data on downloads by accident',
        () {
      expect(const AppSettings().wifiOnlyDownloads, isTrue);
    });

    test('Ethernet is Wi-Fi for this rule, as it always was', () {
      // `networkKindOf` maps Ethernet to Wi-Fi: it is not metered.
      expect(policy(wifiOnly: true, network: NetworkKind.wifi).onWifi, isTrue);
    });
  });

  group('P4-24: Data saver reaches the download manager as one value', () {
    test('in force: the policy carries it; not in force: it does not', () {
      expect(
          policy(
                  wifiOnly: false,
                  network: NetworkKind.mobile,
                  dataSaverInForce: true)
              .dataSaver,
          isTrue);
      expect(policy(wifiOnly: false, network: NetworkKind.mobile).dataSaver,
          isFalse);
    });

    test(
        'the cap it carries holds Original to Data saver and leaves Compatible',
        () {
      final capped = policy(
          wifiOnly: false, network: NetworkKind.mobile, dataSaverInForce: true);
      final open = policy(wifiOnly: false, network: NetworkKind.mobile);
      expect(capped.qualityFor(AudioQuality.original).id, 'opus48');
      expect(capped.qualityFor(AudioQuality.compatible).id, 'mp3_192');
      expect(open.qualityFor(AudioQuality.original).id, 'original');
    });
  });
}
