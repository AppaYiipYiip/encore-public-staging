import 'package:encore/data/downloads/download_verify.dart';
import 'package:flutter_test/flutter_test.dart';

List<int> _ascii(String s) => s.codeUnits;

void main() {
  test('a real file of each kind passes', () {
    final cases = {
      'a/t.flac': _ascii('fLaC....'),
      'a/t.opus': _ascii('OggS....'),
      'a/t.ogg': _ascii('OggS....'),
      'a/t.mp3': _ascii('ID3.....'),
      'a/t2.mp3': [0xFF, 0xFB, 0x90, 0x00],
      'a/padded.mp3': [0, 0, 0, 0, 0xFF, 0xFB],
      'a/t.m4a': [0, 0, 0, 0x20, ..._ascii('ftypM4A ')],
      'a/t.wav': _ascii('RIFF....'),
    };
    cases.forEach((path, head) {
      expect(verifyDownload(path: path, size: 5000, head: head), isNull,
          reason: path);
    });
  });

  test('an empty or tiny file is refused', () {
    expect(verifyDownload(path: 'a/t.flac', size: 10, head: _ascii('fLaC')),
        'Downloaded file is empty');
  });

  test('a web page saved as a song is refused', () {
    final html = _ascii('<!DOCTYPE html><html>sign in');
    for (final ext in ['flac', 'opus', 'mp3', 'm4a', 'wav']) {
      expect(verifyDownload(path: 'a/t.$ext', size: 5000, head: html),
          contains('did not send audio'),
          reason: ext);
    }
  });

  test('an original that is shorter than the server said is incomplete', () {
    final reason = verifyDownload(
      path: 'a/t.flac',
      size: 4000,
      head: _ascii('fLaC'),
      expectedBytes: 9000,
      original: true,
    );
    expect(reason, contains('incomplete'));
  });

  test('size is only compared for originals, and bigger is accepted', () {
    // A transcode has no predictable size.
    expect(
        verifyDownload(
            path: 'a/t.opus',
            size: 4000,
            head: _ascii('OggS'),
            expectedBytes: 9000),
        isNull);
    // The file was re-tagged on the server since the last sync.
    expect(
        verifyDownload(
            path: 'a/t.flac',
            size: 9500,
            head: _ascii('fLaC'),
            expectedBytes: 9000,
            original: true),
        isNull);
  });

  test('an unknown extension is not judged', () {
    expect(
        verifyDownload(path: 'a/t.audio', size: 5000, head: _ascii('whatever')),
        isNull);
  });
}
