import 'package:encore/domain/audio_quality.dart';
import 'package:encore/domain/storage_guard.dart';
import 'package:flutter_test/flutter_test.dart';

const _mb = 1024 * 1024;
const _gb = 1024 * _mb;

void main() {
  group('StorageGuard', () {
    test('no cap and plenty of space: ok', () {
      const guard = StorageGuard();
      expect(
        guard.check(
            usedBytes: 20 * _gb,
            inFlightBytes: 100 * _mb,
            nextBytes: 30 * _mb,
            freeBytes: 50 * _gb),
        StorageVerdict.ok,
      );
    });

    test('the cap counts finished, running and the next file', () {
      const guard = StorageGuard(limitBytes: 5 * _gb);
      expect(
        guard.check(
            usedBytes: 4 * _gb + 1000 * _mb,
            inFlightBytes: 80 * _mb,
            nextBytes: 30 * _mb,
            freeBytes: 50 * _gb),
        StorageVerdict.limitReached,
      );
      expect(
        guard.check(
            usedBytes: 4 * _gb,
            inFlightBytes: 80 * _mb,
            nextBytes: 30 * _mb,
            freeBytes: 50 * _gb),
        StorageVerdict.ok,
      );
    });

    test('a nearly full phone stops downloads even without a cap', () {
      const guard = StorageGuard();
      expect(
        guard.check(
            usedBytes: 0,
            inFlightBytes: 0,
            nextBytes: 30 * _mb,
            freeBytes: 1 * _gb + 40 * _mb),
        StorageVerdict.ok,
      );
      expect(
        guard.check(
            usedBytes: 0,
            inFlightBytes: 0,
            nextBytes: 30 * _mb,
            freeBytes: 1 * _gb + 20 * _mb),
        StorageVerdict.lowSpace,
      );
    });

    test('running transfers also eat into the free-space floor', () {
      const guard = StorageGuard();
      expect(
        guard.check(
            usedBytes: 0,
            inFlightBytes: 400 * _mb,
            nextBytes: 30 * _mb,
            freeBytes: 1 * _gb + 300 * _mb),
        StorageVerdict.lowSpace,
      );
    });

    test('unknown free space: only the cap applies', () {
      const guard = StorageGuard(limitBytes: 1 * _gb);
      expect(
        guard.check(usedBytes: 10, inFlightBytes: 0, nextBytes: 10),
        StorageVerdict.ok,
      );
      expect(
        guard.check(usedBytes: 1 * _gb, inFlightBytes: 0, nextBytes: 1),
        StorageVerdict.limitReached,
      );
    });

    test('the cap is reported before low space when both apply', () {
      const guard = StorageGuard(limitBytes: 1 * _gb);
      expect(
        guard.check(
            usedBytes: 1 * _gb,
            inFlightBytes: 0,
            nextBytes: 1,
            freeBytes: 100 * _mb),
        StorageVerdict.limitReached,
      );
    });
  });

  group('estimateDownloadBytes', () {
    test('original uses the known file size', () {
      expect(
        estimateDownloadBytes(
            quality: AudioQuality.original, sourceSize: 31 * _mb),
        31 * _mb,
      );
    });

    test('a transcode is bit rate x length', () {
      // 160 kbit/s for 200 s = 160 * 125 * 200 bytes.
      expect(
        estimateDownloadBytes(
            quality: AudioQuality.high, durationSec: 200, sourceBitRate: 900),
        160 * 125 * 200,
      );
    });

    test('a source below the cap is not inflated', () {
      expect(
        estimateDownloadBytes(
            quality: AudioQuality.high, durationSec: 200, sourceBitRate: 128),
        128 * 125 * 200,
      );
    });

    test('unknown size and length fall back to a typical song', () {
      expect(estimateDownloadBytes(quality: AudioQuality.original), 8 * _mb);
      expect(estimateDownloadBytes(quality: AudioQuality.high), 8 * _mb);
    });
  });
}
