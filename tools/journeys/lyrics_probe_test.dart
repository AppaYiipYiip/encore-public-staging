// Asks the real LRCLIB for one song with the app's own client and prints what came back. Not part of the normal suite:
//
//   flutter test tool/journeys/lyrics_probe_test.dart
import 'package:flutter_test/flutter_test.dart';
import 'package:encore/data/api/lrclib_client.dart';

void main() {
  test('Burden by Opeth, 462 s, an album title that differs', () async {
    final client = LrcLibClient();
    for (final syncedOnly in [false, true]) {
      final result = await client.find(
        title: 'Burden',
        artist: 'Opeth',
        album: 'Watershed (Special Edition)',
        durationSec: 462,
        syncedOnly: syncedOnly,
      );
      final lyrics = result.valueOrNull;
      final sw = result.failureOrNull;
      // ignore: avoid_print
      print(
          'syncedOnly=$syncedOnly failure=${sw?.message} -> ${lyrics == null ? 'none' : '${lyrics.lines.length} lines, synced=${lyrics.synced}, first="${lyrics.lines.first.text}"'}');
    }
  });
}
