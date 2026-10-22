import 'dart:async';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

/// Pictures of screens are compared with pictures drawn on the same operating system: Windows and Linux draw the same text a few pixels
/// apart, so one set of pictures fails on the other machine (the first run on GitHub failed 12 of them, which pass here). A test names
/// `goldens/home.png`; this reads `goldens/windows/home.png` on Windows and `goldens/linux/home.png` on Linux. The Linux ones are drawn
/// by the "Goldens (Linux)" workflow (`.github/workflows/goldens.yml`), never by hand.
Future<void> testExecutable(FutureOr<void> Function() testMain) async {
  final current = goldenFileComparator;
  if (current is LocalFileComparator) {
    goldenFileComparator =
        _PerSystemComparator(current.basedir.resolve('test.dart'));
  }
  await testMain();
}

class _PerSystemComparator extends LocalFileComparator {
  _PerSystemComparator(super.testFile);

  static String get _system => Platform.isWindows
      ? 'windows'
      : Platform.isMacOS
          ? 'macos'
          : 'linux';

  @override
  Uri getTestUri(Uri key, int? version) {
    final parts = key.pathSegments;
    final inSystemFolder = key.replace(pathSegments: [
      ...parts.sublist(0, parts.length - 1),
      _system,
      parts.last
    ]);
    return super.getTestUri(inSystemFolder, version);
  }
}
