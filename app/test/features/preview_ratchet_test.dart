import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

/// D-24 (AUDIT F33): a 30-second preview must never start from a tap by accident. The ONE place that decides what a tap does is
/// `features/instant/tap_play.dart`; a preview from a long-press goes through its `playExplicitPreview`. `playPreviewRun` itself is only
/// called from those two files (and defined in `catalogue_widgets.dart`). A new screen that calls it directly fails here.
void main() {
  test('only the tap helper starts a preview run', () {
    final allowed = {
      'features/catalogue/catalogue_widgets.dart',
      'features/instant/tap_play.dart',
    };
    final offenders = <String>[];
    for (final file in Directory('lib')
        .listSync(recursive: true)
        .whereType<File>()
        .where((f) => f.path.endsWith('.dart'))) {
      final path = file.path.replaceAll('\\', '/').replaceFirst('lib/', '');
      if (allowed.contains(path)) continue;
      if (file.readAsStringSync().contains('playPreviewRun(')) {
        offenders.add(path);
      }
    }
    expect(offenders, isEmpty,
        reason:
            'call tapPlayRun for a tap and playExplicitPreview for a long-press (features/instant/tap_play.dart)');
  });
}
