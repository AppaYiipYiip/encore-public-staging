import 'package:encore/domain/year_in_music.dart';
import 'package:flutter_test/flutter_test.dart';

/// What a person's year in music says about them, from their play history
/// (ADR-064). Every rule on the screen is stated by a test here, with the
/// songs of a real library.
void main() {
  SongFacts song(
    String id,
    String title,
    String artist, {
    String? album,
    String? genre,
    int? year,
    int seconds = 240,
  }) =>
      SongFacts(
        id: id,
        title: title,
        artist: artist,
        album: album ?? '$artist album',
        genre: genre,
        year: year,
        durationSec: seconds,
      );

  final songs = {
    for (final s in [
      song('s1', 'Pigs on the Wing 1', 'Pink Floyd',
          album: 'Animals', genre: 'Rock', year: 1977, seconds: 85),
      song('s2', 'Dogs', 'Pink Floyd',
          album: 'Animals', genre: 'Rock', year: 1977, seconds: 1020),
      song('s3', 'Small Worlds', 'Mac Miller',
          album: 'Swimming', genre: 'Hip-Hop', year: 2018, seconds: 175),
      song('s4', 'Spiritual Healing', 'Death',
          album: 'Spiritual Healing', genre: 'Metal', year: 1990, seconds: 270),
      song('s5', 'Sommaire', 'Raid',
          album: 'Lmorphine', genre: 'Rap', year: 2023, seconds: 200),
    ])
      s.id: s,
  };

  // A local-time moment on a given day.
  DateTime at(int month, int day, [int hour = 12, int minute = 0]) =>
      DateTime(2026, month, day, hour, minute);

  final year = Period(start: DateTime(2026), end: DateTime(2027));

  Listen play(String id, DateTime when) => Listen(id, when);

  group('the totals', () {
    test('count plays and minutes of the songs played, in the period only', () {
      final stats = YearInMusic.compute(
        listens: [
          play('s3', at(3, 1)), // 175 s
          play('s3', at(3, 2)),
          play('s4', at(3, 2)), // 270 s
          play('s4', DateTime(2025, 12, 31, 23, 59)), // last year: not counted
        ],
        songs: songs,
        period: year,
      );

      expect(stats.plays, 3);
      expect(stats.minutes, ((175 + 175 + 270) / 60).round());
      expect(stats.distinctSongs, 2);
      expect(stats.distinctArtists, 2);
    });

    test('a play of a song the library does not know still counts as a play',
        () {
      final stats = YearInMusic.compute(
        listens: [play('gone', at(1, 5)), play('s3', at(1, 5))],
        songs: songs,
        period: year,
      );

      expect(stats.plays, 2);
      expect(stats.minutes, (175 / 60).round(),
          reason: 'nothing is known of its length, so it adds no minutes');
      expect(stats.topSongs.map((r) => r.song.id), ['s3'],
          reason: 'and it cannot be named, so it is not a favourite');
    });

    test('no plays at all is an empty year, not an error', () {
      final stats =
          YearInMusic.compute(listens: [], songs: songs, period: year);

      expect(stats.isEmpty, isTrue);
      expect(stats.topSongs, isEmpty);
      expect(stats.busiestDay, isNull);
      expect(stats.longestStreak, 0);
      expect(stats.clock, List.filled(24, 0));
    });
  });

  group('the favourites', () {
    final listens = [
      for (var i = 0; i < 5; i++) play('s3', at(2, 1 + i)),
      for (var i = 0; i < 3; i++) play('s1', at(2, 10 + i)),
      for (var i = 0; i < 2; i++) play('s2', at(2, 20 + i)),
      play('s4', at(2, 25)),
    ];

    test('songs are ranked by plays, ties broken by the one heard first', () {
      final stats =
          YearInMusic.compute(listens: listens, songs: songs, period: year);

      expect(stats.topSongs.map((r) => (r.song.title, r.plays)), [
        ('Small Worlds', 5),
        ('Pigs on the Wing 1', 3),
        ('Dogs', 2),
        ('Spiritual Healing', 1),
      ]);
    });

    test('artists are ranked by plays and carry the minutes too', () {
      final stats =
          YearInMusic.compute(listens: listens, songs: songs, period: year);

      expect(stats.topArtists.first.name, 'Mac Miller');
      expect(stats.topArtists.first.plays, 5);
      final floyd = stats.topArtists.firstWhere((a) => a.name == 'Pink Floyd');
      expect(floyd.plays, 5);
      expect(floyd.minutes, ((3 * 85 + 2 * 1020) / 60).round());
      expect(stats.topArtists.map((a) => a.name),
          ['Mac Miller', 'Pink Floyd', 'Death'],
          reason: 'five plays each: the one heard first goes first');
    });

    test('albums and genres are ranked too, and at most five are listed', () {
      final many = [
        for (var i = 0; i < 7; i++)
          play('x$i', at(3, 1 + i)), // seven different songs of seven artists
      ];
      final bigLibrary = {
        for (var i = 0; i < 7; i++) 'x$i': song('x$i', 'T$i', 'Artist $i'),
      };

      final stats =
          YearInMusic.compute(listens: many, songs: bigLibrary, period: year);
      expect(stats.topArtists, hasLength(5));
      expect(stats.topAlbums, hasLength(5));

      final withGenres =
          YearInMusic.compute(listens: listens, songs: songs, period: year);
      expect(
          withGenres.topGenres.map((g) => g.name), ['Hip-Hop', 'Rock', 'Metal'],
          reason: 'five plays each: the one heard first goes first');
      expect(withGenres.topAlbums.first.name, 'Swimming');
    });
  });

  group('the days', () {
    test('the busiest day is the one with most plays', () {
      final stats = YearInMusic.compute(
        listens: [
          play('s3', at(4, 1)),
          play('s3', at(4, 9, 8)),
          play('s4', at(4, 9, 13)),
          play('s5', at(4, 9, 22)),
        ],
        songs: songs,
        period: year,
      );

      expect(stats.busiestDay!.day, DateTime(2026, 4, 9));
      expect(stats.busiestDay!.plays, 3);
    });

    test('the longest streak counts days in a row with at least one play', () {
      final stats = YearInMusic.compute(
        listens: [
          play('s3', at(5, 1)),
          play('s3', at(5, 2)),
          play('s3', at(5, 2, 20)), // two plays one day: still one day
          play('s3', at(5, 3)),
          // a gap on the 4th
          play('s3', at(5, 5)),
          play('s3', at(5, 6)),
        ],
        songs: songs,
        period: year,
      );

      expect(stats.longestStreak, 3);
    });

    test('a streak runs across the end of a month and the clock change', () {
      final stats = YearInMusic.compute(
        listens: [
          play('s3', DateTime(2026, 3, 28, 23)),
          play('s3', DateTime(2026, 3, 29, 23)), // the night the clocks go on
          play('s3', DateTime(2026, 3, 30, 23)),
          play('s3', DateTime(2026, 3, 31, 23)),
          play('s3', DateTime(2026, 4, 1, 23)),
        ],
        songs: songs,
        period: year,
      );

      expect(stats.longestStreak, 5);
    });

    test('the listening clock counts plays in each hour of the day', () {
      final stats = YearInMusic.compute(
        listens: [
          play('s3', at(6, 1, 7, 15)),
          play('s3', at(6, 1, 7, 45)),
          play('s3', at(6, 1, 23, 59)),
        ],
        songs: songs,
        period: year,
      );

      expect(stats.clock[7], 2);
      expect(stats.clock[23], 1);
      expect(stats.clock.fold<int>(0, (a, b) => a + b), 3);
    });

    test('the first and the last song of the period', () {
      final stats = YearInMusic.compute(
        listens: [
          play('s4', at(8, 20)),
          play('s3', at(1, 2, 0, 5)), // newest-first or not, order is by time
          play('s5', at(11, 30)),
        ],
        songs: songs,
        period: year,
      );

      expect(stats.firstSong!.song.title, 'Small Worlds');
      expect(stats.lastSong!.song.title, 'Sommaire');
    });
  });

  group('new to you', () {
    test('artists first heard in the period, most played first', () {
      final stats = YearInMusic.compute(
        listens: [
          play('s1', DateTime(2025, 6, 1)), // Pink Floyd: heard before
          play('s1', at(1, 3)),
          play('s3', at(1, 4)),
          play('s3', at(1, 5)),
          play('s5', at(1, 6)),
        ],
        songs: songs,
        period: year,
      );

      expect(stats.newArtists.map((a) => a.name), ['Mac Miller', 'Raid']);
    });
  });

  group('"new" needs something to be new against', () {
    test('a history that starts in the period has no new artists', () {
      final stats = YearInMusic.compute(
        listens: [
          play('s1', at(1, 3)),
          play('s3', at(1, 4)),
          play('s4', at(1, 5)),
          play('s5', at(1, 6)),
          play('s5', at(1, 7)),
        ],
        songs: songs,
        period: year,
      );

      expect(stats.newArtists, isEmpty,
          reason: 'everything is new to someone who has only just begun');
      expect(stats.personality.kind, isNot(Personality.explorer));
    });
  });

  group('the personality is a rule you can read', () {
    List<Listen> at22(int n) =>
        [for (var i = 0; i < n; i++) play('s3', at(7, 1 + i, 23))];

    test('Night Owl: more than a third of the listening after 10 pm', () {
      final stats = YearInMusic.compute(
        listens: [...at22(5), play('s3', at(7, 20, 14)), play('s3', at(7, 21))],
        songs: songs,
        period: year,
      );

      expect(stats.personality.kind, Personality.nightOwl);
      expect(stats.personality.reason, contains('71%'));
      expect(stats.personality.reason, contains('10 pm'));
    });

    test('Early Bird: more than a third between 5 and 9 in the morning', () {
      final stats = YearInMusic.compute(
        listens: [
          for (var i = 0; i < 4; i++) play('s3', at(7, 1 + i, 6)),
          play('s3', at(7, 20, 15)),
          play('s3', at(7, 21, 16)),
        ],
        songs: songs,
        period: year,
      );

      expect(stats.personality.kind, Personality.earlyBird);
    });

    test('Time Traveller: most of what you play is more than 20 years old', () {
      final stats = YearInMusic.compute(
        listens: [
          for (var i = 0; i < 6; i++) play('s2', at(7, 1 + i, 15)),
          play('s3', at(7, 10, 15)),
        ],
        songs: songs,
        period: year,
      );

      expect(stats.personality.kind, Personality.timeTraveller);
      expect(stats.personality.reason, contains('1977'));
    });

    test('Explorer: at least half of your artists were new to you', () {
      final stats = YearInMusic.compute(
        listens: [
          play('s1', DateTime(2025, 1, 1)), // Pink Floyd: heard before
          play('s1', at(7, 1, 15)),
          play('s3', at(7, 2, 15)),
          play('s4', at(7, 3, 15)),
          play('s5', at(7, 4, 15)),
          play('s5', at(7, 5, 15)),
        ],
        songs: songs,
        period: year,
      );

      // Four artists played, three of them new: Mac Miller, Death and Raid.
      expect(stats.personality.kind, Personality.explorer);
      expect(stats.personality.reason, contains('3 of the 4 artists'));
    });

    test('a few plays are too few to say anything about a person', () {
      final stats = YearInMusic.compute(
        listens: [for (var i = 0; i < 4; i++) play('s3', at(7, 1 + i, 23))],
        songs: songs,
        period: year,
      );

      expect(stats.personality.kind, Personality.steady,
          reason: 'four plays, all after 10 pm, are not yet a habit');
    });

    test('otherwise a steady listener, with nothing invented', () {
      final stats = YearInMusic.compute(
        listens: [
          play('s3', at(7, 1, 15)),
          play('s3', at(7, 2, 15)),
          play('s3', at(7, 3, 15)),
        ],
        songs: songs,
        period: year,
      );

      expect(stats.personality.kind, Personality.steady);
    });
  });

  group('periods', () {
    test('a month, a year and all time have the right edges', () {
      final now = DateTime(2026, 10, 17, 15);

      final month = Period.monthOf(now);
      expect(
          (month.start, month.end), (DateTime(2026, 10), DateTime(2026, 11)));
      final december = Period.monthOf(DateTime(2026, 12, 31, 23));
      expect(december.end, DateTime(2027));
      final thisYear = Period.yearOf(now);
      expect((thisYear.start, thisYear.end), (DateTime(2026), DateTime(2027)));
      final all = Period.allTime(now);
      expect(all.contains(DateTime(1999)), isTrue);
      expect(all.contains(now), isTrue);
    });

    test('the end is not part of the period', () {
      final p = Period.yearOf(DateTime(2026, 5));
      expect(p.contains(DateTime(2026)), isTrue);
      expect(p.contains(DateTime(2027)), isFalse);
    });
  });
}
