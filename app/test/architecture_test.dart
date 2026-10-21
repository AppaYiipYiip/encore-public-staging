import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

/// Layering and error-handling rules, enforced on the source text of `lib/`
/// (docs/23-engineering-review.md, C10; docs/02-architecture.md principles).
///
/// How the rules stay honest without turning the gate red on day one: each
/// rule has a **baseline** of known violations. A *new* violation fails the
/// test. A baseline entry that has been *fixed* also fails, with the message to
/// lower the number, so cleanup is always recorded and can never silently
/// regress. The goal of every baseline is an empty map.
void main() {
  final files = _libFiles();

  test('the scan sees the code (guards against a silent no-op)', () {
    expect(files.length, greaterThan(100));
    expect(files.keys, contains('lib/main.dart'));
  });

  group('layering', () {
    test('core, data, domain and playback do not import features/', () {
      _ratchet(
        rule: 'lower layers must not depend on the UI layer (docs/23 D1)',
        actual: _countByFile(
          files,
          dirs: const [
            'lib/core/',
            'lib/data/',
            'lib/domain/',
            'lib/playback/'
          ],
          pattern: RegExp(
              r'''^import\s+['"](?:\.\./)+features/|^import\s+['"]package:encore/features/'''),
        ),
        // The playback layer imports the facade types from features/player/.
        // Fix: move playback_facade.dart to lib/playback/ (docs/23 D1).
        baseline: const {
          'lib/playback/encore_audio_handler.dart': 1,
          'lib/playback/playback_engine.dart': 1,
        },
      );
    });

    test('domain is pure Dart (no package:flutter)', () {
      _ratchet(
        rule:
            'domain must be testable on the plain Dart VM (docs/02 principle 6)',
        actual: _countByFile(
          files,
          dirs: const ['lib/domain/'],
          pattern: RegExp(r'''^import\s+['"]package:flutter/'''),
        ),
        // HSLColor only; port the few lines of colour maths to plain Dart.
        baseline: const {'lib/domain/artwork_color.dart': 1},
      );
    });

    test(
        'the session package is pure Dart: it also runs in the hub and the browser',
        () {
      final pubspec =
          File('../packages/encore_session/pubspec.yaml').readAsStringSync();
      expect(pubspec, isNot(contains('flutter')),
          reason:
              'packages/encore_session must not depend on Flutter (docs/29)');
      final offenders = <String>[];
      for (final f in Directory('../packages/encore_session/lib')
          .listSync(recursive: true)
          .whereType<File>()) {
        for (final line in f.readAsLinesSync()) {
          if (RegExp(
                  r'''^(import|export)\s+['"](dart:io|dart:ui|package:flutter|package:dio|package:encore)''')
              .hasMatch(line)) {
            offenders.add('${f.path}: $line');
          }
        }
      }
      expect(offenders, isEmpty);
    });

    test('only data/ and the app composition root use dio', () {
      _ratchet(
        rule: 'screens and engines must not talk HTTP directly (docs/23 D3)',
        actual: _countByFile(
          files,
          dirs: const [
            'lib/core/',
            'lib/domain/',
            'lib/playback/',
            'lib/features/',
            'lib/design/',
          ],
          pattern: RegExp(r'''^import\s+['"]package:dio/'''),
        ),
        baseline: const {},
      );
    });
  });

  group('error handling', () {
    // A catch that ignores the error object cannot log it, which breaks the
    // project rule "no silent failure" (docs/README.md working agreement 5).
    // Catch a typed exception, or bind the error and log it with `Log.warn`.
    final ignoring = RegExp(
      r'on Object\s*\{|catch\s*\(_\)|catchError\(\(Object _\)\s*\{\}\)|onError:\s*\(_\)',
    );

    test('no new catch-all that ignores the error', () {
      _ratchet(
        rule: 'errors are typed and logged, never swallowed (docs/23 B27)',
        actual: _countByFile(files, dirs: const ['lib/'], pattern: ignoring),
        baseline: const {
          'lib/app/background_sync.dart': 1,
          'lib/app/navigation.dart': 1,
          'lib/core/perf_overlay.dart': 2,
          'lib/data/diagnostics/listening_log.dart': 2,
          'lib/data/fetch/fetch_client.dart': 2,
          'lib/data/requests/portal_discovery.dart': 2,
          'lib/data/sync/playlist_mutations.dart': 1,
          'lib/features/downloads/download_providers.dart': 1,
          'lib/features/instant/instant_controller.dart': 1,
          'lib/features/player/lyrics_screen.dart': 1,
          'lib/features/requests/download_service_sheet.dart': 1,
          'lib/features/search/search_screen.dart': 3,
          'lib/features/settings/import_screen.dart': 1,
          'lib/features/settings/server_addresses.dart': 1,
          'lib/features/settings/settings_controller.dart': 3,
          'lib/playback/playback_engine.dart': 2,
        },
      );
    });
  });
}

/// `relative/path.dart` (forward slashes) -> contents, for every hand-written
/// Dart file under `lib/`.
Map<String, String> _libFiles() {
  final root = Directory('lib');
  if (!root.existsSync()) {
    fail(
        'run from the project root (lib/ not found in ${Directory.current.path})');
  }
  final result = <String, String>{};
  for (final entity in root.listSync(recursive: true)) {
    if (entity is! File || !entity.path.endsWith('.dart')) continue;
    final path = entity.path.replaceAll('\\', '/');
    if (path.endsWith('.g.dart') || path.endsWith('.freezed.dart')) continue;
    result[path] = entity.readAsStringSync();
  }
  return result;
}

/// How many non-comment lines per file match [pattern], for files under any of
/// [dirs]. Files with no match are omitted.
Map<String, int> _countByFile(
  Map<String, String> files, {
  required List<String> dirs,
  required RegExp pattern,
}) {
  final counts = <String, int>{};
  files.forEach((path, text) {
    if (!dirs.any(path.startsWith)) return;
    var n = 0;
    for (final line in text.split('\n')) {
      final code = line.trimLeft();
      if (code.startsWith('//')) continue;
      n += pattern.allMatches(code).length;
    }
    if (n > 0) counts[path] = n;
  });
  return counts;
}

/// Fails on a violation that is not in [baseline] (new debt) and on a baseline
/// entry that is no longer true (paid-off debt that must be recorded).
void _ratchet({
  required String rule,
  required Map<String, int> actual,
  required Map<String, int> baseline,
}) {
  final worse = <String>[];
  final better = <String>[];
  for (final path in {...actual.keys, ...baseline.keys}) {
    final a = actual[path] ?? 0;
    final b = baseline[path] ?? 0;
    if (a > b) worse.add('$path: $a found, $b allowed');
    if (a < b) better.add('$path: $a found, baseline says $b');
  }
  expect(
    worse,
    isEmpty,
    reason: 'NEW violation of "$rule". Fix it instead of adding to the '
        'baseline:\n${worse.join('\n')}',
  );
  expect(
    better,
    isEmpty,
    reason: 'Good news: debt was paid off for "$rule". Lower the baseline in '
        'test/architecture_test.dart so it cannot regress:\n${better.join('\n')}',
  );
}
