import 'package:drift/drift.dart' show Value;
import 'package:drift/native.dart';
import 'package:encore/data/api/lrclib_client.dart';
import 'package:encore/data/api/opensubsonic/opensubsonic_client.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/repos/lyrics_repository.dart';
import 'package:encore/domain/lyrics.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_http.dart';
import '../../support/test_app.dart';

/// Found on a friend's phone (2026-10-17): the lyrics of "Burden" by Opeth were
/// not tappable. The song's file carries plain lyrics, which the server hands
/// over and which then won without LRCLIB ever being asked for the synced
/// version it has; and LRCLIB was only asked for an exact match (artist, title,
/// album and length all identical), so a different album title found nothing.
void main() {
  late AppDatabase db;
  late int serverId;
  late FakeHttpAdapter subsonic;
  late FakeHttpAdapter lrclib;

  const plain = ['Every line', 'of the plain text'];

  Map<String, Object?> serverLyrics({required bool synced}) => subsonicOk({
        'lyricsList': {
          'structuredLyrics': [
            {
              'synced': synced,
              'line': [
                for (var i = 0; i < plain.length; i++)
                  {'start': synced ? i * 3000 : 0, 'value': plain[i]},
              ],
            },
          ],
        },
      });

  Map<String, Object?> entry(int seconds,
          {String? synced, String plainText = 'plain only'}) =>
      {
        'trackName': 'Burden',
        'artistName': 'Opeth',
        'albumName': 'Watershed',
        'duration': seconds,
        'syncedLyrics': synced,
        'plainLyrics': plainText,
      };

  setUp(() async {
    db = AppDatabase(NativeDatabase.memory());
    serverId = await Seed.library(db);
    subsonic = FakeHttpAdapter(routes: {
      'getLyricsBySongId': (_) =>
          FakeResponse.json(serverLyrics(synced: false)),
    });
    lrclib = FakeHttpAdapter(routes: {
      'get': (_) => const FakeResponse.json({'error': 'nothing'}, status: 404),
      'search': (_) => FakeResponse.json([
            entry(254, synced: '[00:01.00] short one'),
            entry(461,
                synced: '[00:02.00] the right one\n[00:06.00] second line'),
            entry(864, synced: '[00:03.00] far too long'),
          ]),
    });
  });

  tearDown(() => db.close());

  LyricsRepository repo() => LyricsRepository(
        db: db,
        serverId: serverId,
        server: OpenSubsonicClient(
          dio: fakeDio(subsonic),
          baseUrl: () => Uri.parse('http://server'),
          credentials:
              const SubsonicCredentials(username: 'marwa', password: 'x'),
        ),
        lrclib: LrcLibClient(dio: fakeDio(lrclib)),
      );

  Future<TrackLyrics?> load(LyricsRepository r, {int seconds = 462}) => r.load(
        trackId: 'al4-t2',
        title: 'Burden',
        artist: 'Opeth',
        album: 'Watershed (Special Edition)',
        durationSec: seconds,
      );

  test(
      'plain lyrics on the server are replaced by the synced ones LRCLIB has '
      '(so a line can be tapped)', () async {
    final lyrics = await load(repo());

    expect(lyrics!.synced, isTrue);
    expect(lyrics.lines.first.text, 'the right one');
    expect(lyrics.source, 'lrclib');
  });

  test('when LRCLIB has nothing synced, the server\'s plain lyrics stay',
      () async {
    lrclib.routes['search'] =
        (_) => FakeResponse.json([entry(461), entry(257)]);

    final lyrics = await load(repo());

    expect(lyrics!.synced, isFalse);
    expect(lyrics.lines.map((l) => l.text), plain);
    expect(lyrics.source, 'server');
  });

  test('synced lyrics on the server are kept and LRCLIB is not asked',
      () async {
    subsonic.routes['getLyricsBySongId'] =
        (_) => FakeResponse.json(serverLyrics(synced: true));

    final lyrics = await load(repo());

    expect(lyrics!.synced, isTrue);
    expect(lyrics.source, 'server');
    expect(lrclib.requests, isEmpty);
  });

  test('a version of another length (a live cut, a remix) is not used',
      () async {
    final lyrics = await load(repo(), seconds: 120);

    expect(lyrics!.source, 'server',
        reason: 'nothing near 2 minutes: the server\'s own text is the answer');
  });

  test('with no lyrics on the server, the nearest synced version is used',
      () async {
    subsonic.routes['getLyricsBySongId'] =
        (_) => FakeResponse.json(subsonicOk({'lyricsList': {}}));

    final lyrics = await load(repo());

    expect(lyrics!.lines.first.text, 'the right one');
  });

  test('a lookup that works the old way (exact match) still wins first',
      () async {
    lrclib.routes['get'] =
        (_) => FakeResponse.json(entry(462, synced: '[00:01.00] exact line'));

    final lyrics = await load(repo());

    expect(lyrics!.lines.first.text, 'exact line');
    expect(lrclib.count('search'), 0);
  });

  group(
      'plain lyrics that are kept are looked at again for a synced copy (the owner\'s Opeth "Benighted", 7 Nov 2026)',
      () {
    Future<void> cachePlain({required Duration ago}) =>
        db.into(db.lyrics).insertOnConflictUpdate(LyricsCompanion.insert(
              serverId: serverId,
              trackId: 'al4-t2',
              kind: 'plain',
              body: 'Every line\nof the plain text',
              source: const Value('lrclib'),
              fetchedAtMs:
                  DateTime.now().millisecondsSinceEpoch - ago.inMilliseconds,
            ));

    test(
        'plain lyrics cached two hours ago are replaced by a synced copy LRCLIB has now',
        () async {
      await cachePlain(ago: const Duration(hours: 2));

      final lyrics = await load(repo());

      expect(lyrics!.synced, isTrue, reason: 'a person can tap a line of it');
      expect(lyrics.lines.first.text, 'the right one');
      expect((await repo().cached('al4-t2'))!.synced, isTrue,
          reason: 'and it is kept');
    });

    test('plain lyrics cached five minutes ago are not asked about again',
        () async {
      await cachePlain(ago: const Duration(minutes: 5));

      final lyrics = await load(repo());

      expect(lyrics!.synced, isFalse);
      expect(
          lyrics.lines.map((l) => l.text), ['Every line', 'of the plain text']);
      expect(lrclib.requests, isEmpty);
      expect(subsonic.requests, isEmpty);
    });

    test(
        'a look that finds nothing synced is remembered: the next play does not ask again',
        () async {
      lrclib.routes['search'] = (_) => FakeResponse.json([entry(461)]);
      await cachePlain(ago: const Duration(hours: 2));

      final first = await load(repo());
      final asked = lrclib.requests.length;
      final second = await load(repo());

      expect(first!.synced, isFalse);
      expect(second!.synced, isFalse);
      expect(asked, greaterThan(0), reason: 'the first play looked');
      expect(lrclib.requests.length, asked, reason: 'the second did not');
    });

    test(
        'a service that cannot be reached keeps the plain text, and nothing is thrown',
        () async {
      lrclib.routes['get'] = (_) => const FakeResponse.connectionError();
      lrclib.routes['search'] = (_) => const FakeResponse.connectionError();
      await cachePlain(ago: const Duration(hours: 2));

      final lyrics = await load(repo());

      expect(lyrics!.synced, isFalse);
      expect(lyrics.lines.first.text, 'Every line');
    });

    test(
        'offline (no network allowed) the cached plain text is returned as it is',
        () async {
      await cachePlain(ago: const Duration(hours: 2));

      final lyrics = await repo().load(
          trackId: 'al4-t2',
          title: 'Burden',
          artist: 'Opeth',
          album: 'Watershed',
          durationSec: 462,
          allowNetwork: false);

      expect(lyrics!.synced, isFalse);
      expect(lrclib.requests, isEmpty);
    });
  });
}
