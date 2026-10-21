import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

/// Android's Auto Backup must not touch this app (ADR-063, docs/22 4.1):
/// the database is rebuilt from the server, downloads are gigabytes (Auto
/// Backup gives up above 25 MB, silently) and the saved login is encrypted
/// with a key that never leaves the phone, so a restored copy cannot open.
/// What a person wants back after a reinstall lives on their own server.
void main() {
  final manifest =
      File('android/app/src/main/AndroidManifest.xml').readAsStringSync();
  final extraction =
      File('android/app/src/main/res/xml/data_extraction_rules.xml')
          .readAsStringSync();
  final legacy =
      File('android/app/src/main/res/xml/backup_rules.xml').readAsStringSync();

  const domains = ['root', 'file', 'database', 'sharedpref', 'external'];

  test('the manifest switches backup off and names both rule files', () {
    expect(manifest, contains('android:allowBackup="false"'));
    expect(
        manifest,
        contains('android:dataExtractionRules='
            '"@xml/data_extraction_rules"'));
    expect(manifest, contains('android:fullBackupContent="@xml/backup_rules"'));
  });

  test('cloud backup and device transfer both exclude every domain', () {
    final cloud = extraction.substring(extraction.indexOf('<cloud-backup>'),
        extraction.indexOf('</cloud-backup>'));
    final transfer = extraction.substring(
        extraction.indexOf('<device-transfer>'),
        extraction.indexOf('</device-transfer>'));
    for (final domain in domains) {
      expect(cloud, contains('<exclude domain="$domain" path="." />'),
          reason: 'cloud backup keeps "$domain"');
      expect(transfer, contains('<exclude domain="$domain" path="." />'),
          reason: 'device transfer keeps "$domain"');
    }
    expect(cloud, isNot(contains('<include')));
    expect(transfer, isNot(contains('<include')));
  });

  test('the Android 11 rule file excludes every domain too', () {
    for (final domain in domains) {
      expect(legacy, contains('<exclude domain="$domain" path="." />'));
    }
    expect(legacy, isNot(contains('<include')));
  });
}
