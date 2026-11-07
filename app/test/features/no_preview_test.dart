import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

/// D-64 (7 Nov 2026, the owner): there is no 30-second preview anywhere in the app; every song that plays is the whole song. This fails the day
/// a preview comes back by a side door: a catalogue preview address, a play call that names one, or the "this is a clip" guess that kept lyrics
/// away from streamed songs. (`tap_play.dart` is the one place that decides what a tap does.)
void main() {
  final forbidden = <String, RegExp>{
    'a catalogue preview address': RegExp(r'previewUrl'),
    'a play call that names a preview':
        RegExp(r'play(Explicit)?Preview(Run|s)?'),
    'the clip guess (a whole song with only a cover address)':
        RegExp(r'fullSong'),
    'a preview plan': RegExp(r'TapPlan\.preview'),
  };

  test('nothing in lib/ can start a 30-second preview', () {
    final offenders = <String>[];
    for (final file in Directory('lib')
        .listSync(recursive: true)
        .whereType<File>()
        .where(
            (f) => f.path.endsWith('.dart') && !f.path.endsWith('.g.dart'))) {
      final path = file.path.replaceAll(r'\', '/');
      final text = file.readAsStringSync();
      forbidden.forEach((what, pattern) {
        if (pattern.hasMatch(text)) offenders.add('$path: $what');
      });
    }
    expect(offenders, isEmpty,
        reason:
            'previews are gone (D-64): play the whole song through tapPlayRun / tapPlayOne (features/instant/tap_play.dart)');
  });
}
