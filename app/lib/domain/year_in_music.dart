/// "Year in Music": what a person's play history says about them (ADR-064).
///
/// Pure Dart: the history and the songs' facts go in, numbers come out. Nothing
/// here knows where the history came from (the music server's own record of
/// every play, per person, or the app's own log) or how it is drawn.
library;

/// One completed play of a song.
class Listen {
  const Listen(this.trackId, this.at);

  final String trackId;

  /// When it was played, in the person's own time zone (days and hours are
  /// counted as the person lived them).
  final DateTime at;
}

/// What is known of a song when the year is counted. A song that has since
/// left the library has no facts and can only be counted as a play.
class SongFacts {
  const SongFacts({
    required this.id,
    required this.title,
    this.artist,
    this.album,
    this.genre,
    this.year,
    this.durationSec,
    this.coverArt,
    this.albumId,
    this.artistId,
  });

  final String id;
  final String title;
  final String? artist;
  final String? album;
  final String? genre;
  final int? year;
  final int? durationSec;
  final String? coverArt;
  final String? albumId;
  final String? artistId;
}

/// A stretch of time: [start] belongs to it, [end] does not.
class Period {
  const Period({required this.start, required this.end});

  /// The calendar month [moment] is in.
  factory Period.monthOf(DateTime moment) => Period(
        start: DateTime(moment.year, moment.month),
        end: DateTime(moment.year, moment.month + 1),
      );

  /// The calendar year [moment] is in.
  factory Period.yearOf(DateTime moment) =>
      Period(start: DateTime(moment.year), end: DateTime(moment.year + 1));

  /// Everything up to and including [now].
  factory Period.allTime(DateTime now) =>
      Period(start: DateTime(1970), end: now.add(const Duration(days: 1)));

  final DateTime start;
  final DateTime end;

  bool contains(DateTime moment) =>
      !moment.isBefore(start) && moment.isBefore(end);

  @override
  bool operator ==(Object other) =>
      other is Period && other.start == start && other.end == end;

  @override
  int get hashCode => Object.hash(start, end);
}

/// A song and how often it was played.
class RankedSong {
  const RankedSong(this.song, this.plays);

  final SongFacts song;
  final int plays;
}

/// An artist, an album or a genre and how much it was played.
class RankedName {
  const RankedName({
    required this.name,
    required this.plays,
    required this.minutes,
    this.artist,
    this.coverArt,
    this.id,
  });

  final String name;
  final int plays;
  final int minutes;

  /// The artist of an album (two artists can have an album of the same name).
  final String? artist;
  final String? coverArt;

  /// The library id of the artist or album, when the songs know it.
  final String? id;
}

/// A song at a moment (the first and the last of the period).
class PlayedSong {
  const PlayedSong(this.song, this.at);

  final SongFacts song;
  final DateTime at;
}

/// The few kinds of listener the rules below can tell apart. Each is chosen by
/// a rule the screen states in words (see [PersonalityResult.reason]); nothing
/// is invented.
enum Personality {
  nightOwl('Night Owl'),
  earlyBird('Early Bird'),
  timeTraveller('Time Traveller'),
  explorer('Explorer'),
  steady('Steady listener');

  const Personality(this.title);

  final String title;
}

class PersonalityResult {
  const PersonalityResult(this.kind, this.reason);

  final Personality kind;

  /// The rule, with the person's own numbers ("71% of your listening was
  /// between 10 pm and 4 am.").
  final String reason;
}

/// The year (or month, or all time) of one person.
class YearInMusic {
  const YearInMusic._({
    required this.period,
    required this.plays,
    required this.minutes,
    required this.distinctSongs,
    required this.distinctArtists,
    required this.topSongs,
    required this.topArtists,
    required this.topAlbums,
    required this.topGenres,
    required this.busiestDay,
    required this.longestStreak,
    required this.clock,
    required this.firstSong,
    required this.lastSong,
    required this.newArtists,
    required this.personality,
  });

  final Period period;
  final int plays;

  /// Minutes of the songs played, each counted whole: the server records that
  /// a song was played, not for how long (ADR-064).
  final int minutes;
  final int distinctSongs;
  final int distinctArtists;
  final List<RankedSong> topSongs;
  final List<RankedName> topArtists;
  final List<RankedName> topAlbums;
  final List<RankedName> topGenres;
  final ({DateTime day, int plays})? busiestDay;

  /// The most days in a row with at least one play.
  final int longestStreak;

  /// Plays in each hour of the day (24 numbers).
  final List<int> clock;
  final PlayedSong? firstSong;
  final PlayedSong? lastSong;

  /// Artists first heard in this period, the most played first.
  final List<RankedName> newArtists;
  final PersonalityResult personality;

  bool get isEmpty => plays == 0;

  /// How many of each list are kept.
  static const top = 5;

  /// Counts [listens] that fall in [period]. Earlier plays in [listens] are
  /// not counted, but tell which artists are new in the period.
  static YearInMusic compute({
    required Iterable<Listen> listens,
    required Map<String, SongFacts> songs,
    required Period period,
  }) {
    final all = [...listens]..sort((a, b) => a.at.compareTo(b.at));
    final inPeriod = [
      for (final l in all)
        if (period.contains(l.at)) l
    ];

    final firstHeard = <String, DateTime>{}; // artist -> first play ever
    for (final l in all) {
      final artist = songs[l.trackId]?.artist;
      if (artist != null) firstHeard.putIfAbsent(artist, () => l.at);
    }

    final songPlays = _Tally<String>();
    final artistPlays = _Tally<String>();
    final albumPlays = _Tally<String>();
    final genrePlays = _Tally<String>();
    final albumFacts = <String, SongFacts>{};
    final artistFacts = <String, SongFacts>{};
    final days = <DateTime, int>{};
    final clock = List<int>.filled(24, 0);
    final distinctTracks = <String>{};
    var seconds = 0;
    PlayedSong? first;
    PlayedSong? last;

    for (final l in inPeriod) {
      distinctTracks.add(l.trackId);
      final day = DateTime(l.at.year, l.at.month, l.at.day);
      days[day] = (days[day] ?? 0) + 1;
      clock[l.at.hour]++;
      final song = songs[l.trackId];
      if (song == null) continue;
      final length = song.durationSec ?? 0;
      seconds += length;
      songPlays.add(l.trackId, l.at, length);
      final artist = song.artist;
      if (artist != null) {
        artistPlays.add(artist, l.at, length);
        artistFacts.putIfAbsent(artist, () => song);
      }
      final album = song.album;
      if (album != null) {
        final key = '${artist ?? ''}|$album';
        albumPlays.add(key, l.at, length);
        albumFacts.putIfAbsent(key, () => song);
      }
      final genre = song.genre;
      if (genre != null) genrePlays.add(genre, l.at, length);
      first ??= PlayedSong(song, l.at);
      last = PlayedSong(song, l.at);
    }

    RankedName named(String key, _Count c,
            {SongFacts? facts, bool album = false}) =>
        RankedName(
          name: album ? (facts?.album ?? key) : key,
          plays: c.plays,
          minutes: (c.seconds / 60).round(),
          artist: album ? facts?.artist : null,
          coverArt: facts?.coverArt,
          id: facts == null ? null : (album ? facts.albumId : facts.artistId),
        );

    // "New to you" needs something to be new against: someone whose history
    // starts in the period has only just begun, and everything is new.
    final hadEarlier = all.any((l) => l.at.isBefore(period.start));
    final newArtists = [
      if (hadEarlier)
        for (final e in artistPlays.ranked())
          if (!firstHeard[e.key]!.isBefore(period.start))
            named(e.key, e.value, facts: artistFacts[e.key]),
    ];

    final dayList = days.entries.toList()
      ..sort((a, b) {
        final byPlays = b.value.compareTo(a.value);
        return byPlays != 0 ? byPlays : a.key.compareTo(b.key);
      });

    final topArtists = [
      for (final e in artistPlays.ranked().take(top))
        named(e.key, e.value, facts: artistFacts[e.key]),
    ];

    return YearInMusic._(
      period: period,
      plays: inPeriod.length,
      minutes: (seconds / 60).round(),
      distinctSongs: distinctTracks.length,
      distinctArtists: artistPlays.length,
      topSongs: [
        for (final e in songPlays.ranked().take(top))
          RankedSong(songs[e.key]!, e.value.plays),
      ],
      topArtists: topArtists,
      topAlbums: [
        for (final e in albumPlays.ranked().take(top))
          named(e.key, e.value, facts: albumFacts[e.key], album: true),
      ],
      topGenres: [
        for (final e in genrePlays.ranked().take(top)) named(e.key, e.value),
      ],
      busiestDay: dayList.isEmpty
          ? null
          : (day: dayList.first.key, plays: dayList.first.value),
      longestStreak: _longestStreak(days.keys),
      clock: clock,
      firstSong: first,
      lastSong: last,
      newArtists: newArtists,
      personality: _personality(
        inPeriod: inPeriod,
        songs: songs,
        period: period,
        clock: clock,
        distinctArtists: artistPlays.length,
        newArtists: newArtists.length,
      ),
    );
  }

  static int _longestStreak(Iterable<DateTime> days) {
    final sorted = days.toList()..sort();
    var best = 0;
    var run = 0;
    DateTime? previous;
    for (final day in sorted) {
      // Calendar arithmetic, not 24-hour arithmetic: a day with a clock change
      // is 23 or 25 hours long.
      final next = previous == null
          ? null
          : DateTime(previous.year, previous.month, previous.day + 1);
      run = (next != null && next == day) ? run + 1 : 1;
      if (run > best) best = run;
      previous = day;
    }
    return best;
  }

  /// A person with fewer plays than this has no habits yet.
  static const _minPlays = 5;

  static PersonalityResult _personality({
    required List<Listen> inPeriod,
    required Map<String, SongFacts> songs,
    required Period period,
    required List<int> clock,
    required int distinctArtists,
    required int newArtists,
  }) {
    const steady = PersonalityResult(
        Personality.steady, 'No habit stands out in your listening yet.');
    final plays = inPeriod.length;
    if (plays < _minPlays) return steady;
    int percent(int part, int whole) => (100 * part / whole).round();

    final night = [22, 23, 0, 1, 2, 3].fold<int>(0, (a, h) => a + clock[h]);
    if (night / plays >= 0.35) {
      return PersonalityResult(Personality.nightOwl,
          '${percent(night, plays)}% of your listening was between 10 pm and 4 am.');
    }
    final morning = [5, 6, 7, 8].fold<int>(0, (a, h) => a + clock[h]);
    if (morning / plays >= 0.35) {
      return PersonalityResult(Personality.earlyBird,
          '${percent(morning, plays)}% of your listening was between 5 and 9 in the morning.');
    }

    final lastDay = period.end.subtract(const Duration(days: 1));
    var old = 0;
    int? oldest;
    for (final l in inPeriod) {
      final year = songs[l.trackId]?.year;
      if (year == null) continue;
      if (lastDay.year - year > 20) {
        old++;
        if (oldest == null || year < oldest) oldest = year;
      }
    }
    if (old / plays > 0.5) {
      return PersonalityResult(Personality.timeTraveller,
          '${percent(old, plays)}% of what you played was more than 20 years old; the oldest is from $oldest.');
    }

    if (distinctArtists >= 3 && newArtists / distinctArtists >= 0.5) {
      return PersonalityResult(Personality.explorer,
          '$newArtists of the $distinctArtists artists you played were new to you.');
    }
    return steady;
  }
}

class _Count {
  _Count(this.firstAt);

  final DateTime firstAt;
  int plays = 0;
  int seconds = 0;
}

/// Counts plays per key and ranks them: most plays first, and of equal plays
/// the one heard first (a fair, explainable rule).
class _Tally<K> {
  final Map<K, _Count> _counts = {};

  int get length => _counts.length;

  void add(K key, DateTime at, int seconds) {
    final c = _counts.putIfAbsent(key, () => _Count(at));
    c.plays++;
    c.seconds += seconds;
  }

  List<MapEntry<K, _Count>> ranked() => _counts.entries.toList()
    ..sort((a, b) {
      final byPlays = b.value.plays.compareTo(a.value.plays);
      return byPlays != 0
          ? byPlays
          : a.value.firstAt.compareTo(b.value.firstAt);
    });
}
