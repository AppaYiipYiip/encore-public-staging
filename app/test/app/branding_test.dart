import 'package:encore/app/branding.dart';
import 'package:flutter_test/flutter_test.dart';

/// AUDIT F34 / D-25: every build since 2026-10-22 said "0.1.0", so neither the owner nor anyone else could say which APK a bug was on.
/// The version line names the build number and the commit; a build made without them says so, never nothing.
void main() {
  test('F34: the version line names the build and the commit', () {
    expect(describeVersion(version: '0.1.0', build: '123', commit: 'abc1234'),
        '0.1.0 (build 123 · abc1234)');
  });

  test('a build made without the numbers says so, never nothing', () {
    expect(describeVersion(version: '0.1.0', build: '', commit: ''),
        '0.1.0 (build unknown · commit unknown)');
    expect(describeVersion(version: '0.1.0', build: '123', commit: ''),
        '0.1.0 (build 123 · commit unknown)');
  });

  test('the running app uses the same line', () {
    expect(
        AppBranding.versionLine, startsWith('${AppBranding.version} (build '));
    expect(AppBranding.versionLine, contains('·'));
  });
}
