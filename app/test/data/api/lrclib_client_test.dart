import 'package:encore/core/result.dart';
import 'package:encore/data/api/lrclib_client.dart';
import 'package:encore/domain/lyrics.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_http.dart';

/// Audit B-103 (the owner, 7 Nov 2026, Opeth "Benighted"): the exact record LRCLIB returns for the song is plain only, and the old lookup
/// stopped there; the 8 synced records of the same song, at the same length, were never looked at, so no line could be tapped.
void main() {
  late FakeHttpAdapter http;

  Map<String, Object?> record(int id, int seconds,
          {String? synced,
          String plain = 'Come into this night\nHere we\'ll be gone',
          String name = 'Benighted'}) =>
      {
        'id': id,
        'trackName': name,
        'artistName': 'Opeth',
        'albumName': 'Still Life',
        'duration': seconds,
        'syncedLyrics': synced,
        'plainLyrics': plain,
      };

  const syncedText =
      '[00:01.00] Come into this night\n[00:05.00] Here we\'ll be gone';

  LrcLibClient client() => LrcLibClient(dio: fakeDio(http));

  Future<Result<TrackLyrics?>> find(LrcLibClient c,
          {String title = 'Benighted', bool syncedOnly = false}) =>
      c.find(
          title: title,
          artist: 'Opeth',
          album: 'Still Life',
          durationSec: 300,
          syncedOnly: syncedOnly);

  setUp(() {
    http = FakeHttpAdapter(routes: {
      'get': (_) => FakeResponse.json(record(1918075, 300)),
      'search': (_) =>
          FakeResponse.json([record(1135050, 300, synced: syncedText)]),
    });
  });

  test(
      'an exact record that is plain does not end the search: a synced record of the same song wins',
      () async {
    final result = await find(client());

    final lyrics = result.valueOrNull!;
    expect(lyrics.synced, isTrue,
        reason: 'a person can only tap a line of a synced record');
    expect(lyrics.lines.first.text, 'Come into this night');
    expect(http.count('search'), 1);
  });

  test('an exact record that is synced ends the search at once', () async {
    http.routes['get'] =
        (_) => FakeResponse.json(record(1135050, 300, synced: syncedText));

    final result = await find(client());

    expect(result.valueOrNull!.synced, isTrue);
    expect(http.count('search'), 0);
  });

  test(
      'the plain exact record is the answer when no synced record is near enough in length',
      () async {
    http.routes['search'] =
        (_) => FakeResponse.json([record(33017369, 600, synced: syncedText)]);

    final result = await find(client());

    final lyrics = result.valueOrNull!;
    expect(lyrics.synced, isFalse);
    expect(lyrics.lines.first.text, 'Come into this night');
  });

  test(
      'a synced record of a version of another length (a live cut, a remix) is not used',
      () async {
    http.routes['search'] =
        (_) => FakeResponse.json([record(1, 120, synced: syncedText)]);

    final result = await find(client());

    expect(result.valueOrNull!.synced, isFalse);
  });

  test('with no exact record, the nearest synced record is used (as before)',
      () async {
    http.routes['get'] =
        (_) => const FakeResponse.json({'error': 'nothing'}, status: 404);

    final result = await find(client());

    expect(result.valueOrNull!.synced, isTrue);
  });

  test(
      'a title with a bracketed tail is searched again without it when nothing synced was found',
      () async {
    http.routes['search'] = (r) {
      final name = r.param('track_name');
      return FakeResponse.json(name == 'Benighted'
          ? [record(1135050, 300, synced: syncedText)]
          : [record(1918075, 300, name: 'Benighted (Remastered)')]);
    };

    final result = await find(client(), title: 'Benighted (Remastered)');

    expect(result.valueOrNull!.synced, isTrue);
    expect(http.count('search'), 2);
  });

  test('a title with no bracketed tail is searched once', () async {
    http.routes['search'] = (_) => FakeResponse.json([record(1918075, 300)]);

    await find(client());

    expect(http.count('search'), 1);
  });

  test('syncedOnly: a plain exact record and nothing synced near is null',
      () async {
    http.routes['search'] = (_) => FakeResponse.json([record(1918075, 300)]);

    final result = await find(client(), syncedOnly: true);

    expect(result.valueOrNull, isNull);
  });

  test(
      'the repaired text of the record that decided is what comes back (B-102)',
      () async {
    http.routes['get'] = (_) => FakeResponse.json(record(1918075, 300,
        plain: 'Come into this night\nHere weÂ´ll be gone'));
    http.routes['search'] = (_) => FakeResponse.json(const <Object>[]);

    final result = await find(client());

    expect(result.valueOrNull!.lines.map((l) => l.text),
        ['Come into this night', 'Here we´ll be gone']);
  });
}
