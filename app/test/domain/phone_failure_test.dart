import 'package:encore/domain/download_line.dart';
import 'package:flutter_test/flutter_test.dart';

/// A song the phone could not take is named with a reason in plain words (docs/design S-16, PB-37). The raw text the downloader recorded (an exception
/// class, a path, an HTTP status) is never shown.
void main() {
  test('the server no longer has it', () {
    expect(phoneFailureWords('Track is no longer on the server'),
        'The server no longer has this song.');
  });

  test('no room on the phone', () {
    for (final raw in [
      'FileSystemException: No space left on device, path = /data/user/0/app/x.opus',
      'ENOSPC',
      'Not enough space',
    ]) {
      expect(phoneFailureWords(raw), 'There is no room on this phone.',
          reason: raw);
    }
  });

  test('anything else is said plainly, and the raw text stays out of it', () {
    final words = phoneFailureWords(
        "SocketException: Connection reset by peer, uri=http://192.168.1.5:4533/rest/download?id=1&t=abc&s=def");

    expect(words, 'Could not be saved on this phone.');
    expect(words, isNot(contains('Socket')));
    expect(words, isNot(contains('192.168')));
    expect(phoneFailureWords(null), 'Could not be saved on this phone.');
    expect(phoneFailureWords(''), 'Could not be saved on this phone.');
  });
}
