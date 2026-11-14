import 'package:encore/domain/audio_quality.dart';
import 'package:flutter_test/flutter_test.dart';

/// P4-24: what Data saver holds a person's own quality choice to while it is in force. The rules are the advisor's (14 Nov 2026): the cap is
/// the lowest level of the SAME codec that exists, it never changes the codec, and no new level is invented.
void main() {
  test('Original has no codec of its own: Data saver is its cap', () {
    expect(AudioQuality.original.cappedForDataSaver(), AudioQuality.dataSaver);
  });

  test('Opus levels go down to the lowest Opus level, which is Data saver', () {
    expect(AudioQuality.high.cappedForDataSaver(), AudioQuality.dataSaver);
    expect(AudioQuality.normal.cappedForDataSaver(), AudioQuality.dataSaver);
  });

  test('Data saver itself is not lowered', () {
    expect(AudioQuality.dataSaver.cappedForDataSaver(), AudioQuality.dataSaver);
  });

  test(
      'Compatible (MP3) is never turned into Opus: it has no lower MP3 level, so it stays as it is',
      () {
    // If this fails because a lower MP3 level was added, the cap must pick it; the codec must stay MP3 either way.
    final capped = AudioQuality.compatible.cappedForDataSaver();
    expect(capped.format, AudioQuality.compatible.format);
    expect(capped, AudioQuality.compatible,
        reason: 'no MP3 level below 192 kbps exists today');
    expect(AudioQuality.compatible.isLoweredByDataSaver, isFalse);
  });

  test('a cap never raises a level and never changes the codec', () {
    for (final q in AudioQuality.values) {
      final capped = q.cappedForDataSaver();
      expect(capped.rank <= q.rank, isTrue, reason: '${q.id} -> ${capped.id}');
      if (!q.isOriginal) {
        expect(capped.format, q.format, reason: '${q.id} -> ${capped.id}');
      }
    }
  });

  test('isLoweredByDataSaver says whether the cap changes anything', () {
    expect(AudioQuality.original.isLoweredByDataSaver, isTrue);
    expect(AudioQuality.high.isLoweredByDataSaver, isTrue);
    expect(AudioQuality.normal.isLoweredByDataSaver, isTrue);
    expect(AudioQuality.dataSaver.isLoweredByDataSaver, isFalse);
    expect(AudioQuality.compatible.isLoweredByDataSaver, isFalse);
  });
}
