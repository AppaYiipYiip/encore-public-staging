/// Single place for the product identity (ADR-020). Changing the name later is
/// an edit here plus the Android label/applicationId.
abstract final class AppBranding {
  static const String name = 'Encore';
  static const String tagline = 'Your music, always with you.';
  static const String version = '0.1.0';

  /// Injected when the APK is built: `--dart-define=BUILD_NUMBER=123 --dart-define=GIT_SHA=abc1234` (docs/tasks/RELEASE-CANDIDATE.md). A build
  /// made without them says so.
  static const String buildNumber = String.fromEnvironment('BUILD_NUMBER');
  static const String commit = String.fromEnvironment('GIT_SHA');

  /// `0.1.0 (build 123 · abc1234)`: what About, Diagnostics and the copied report show (AUDIT F34, D-25).
  static String get versionLine =>
      describeVersion(version: version, build: buildNumber, commit: commit);
}

/// The version line for a version, a build number and a commit; an empty number or commit is said, never left out.
String describeVersion({
  required String version,
  required String build,
  required String commit,
}) =>
    '$version (build ${build.isEmpty ? 'unknown' : build} · ${commit.isEmpty ? 'commit unknown' : commit})';
