import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/logger.dart';
import '../../data/catalogue/catalogue_models.dart';
import '../../domain/text_match.dart';

/// "Beach House Space Song" names an artist and a song, but the catalogue's text search answers with songs whose *title* has all those
/// words (covers, tributes, an uploader's "Beach House Space Song") and never lists Beach House's own song (measured 2026-10-22: not in the
/// first 11 results). Spotify finds it because it knows who the artist is.
///
/// So when none of the results is a song by an artist named at one end of what was typed, the typed words are read as an artist and a
/// title in every way that makes sense (the first or the last one to three words are the artist), the artist is looked up by that name,
/// and its popular songs are searched for the title. A hit is put first, with the artist. Costs nothing when the normal results already
/// answer (the usual case), and a handful of small requests when they do not.

/// How many words an artist's name may take at one end of the query.
const int _longestArtistName = 3;

/// The artists with fewer fans than this are not taken to be "who the person meant" by a name that is also an ordinary word.
const int _fewestFans = 1000;

/// Most songs added per artist, and most artists tried.
const int _songsPerArtist = 3;
const int _artistsTried = 2;

/// One way to read the typed words: [artist] then [title] words, or the other way round.
class ArtistTitleSplit {
  const ArtistTitleSplit(this.artist, this.title);

  final String artist;
  final List<String> title;

  @override
  String toString() => '[$artist] [${title.join(' ')}]';
}

/// Every way to read [query] as an artist at one end and the rest as a title; none for fewer than three words (two words are as
/// likely to be one name or one title as both, and the plain search is good at those).
List<ArtistTitleSplit> artistTitleSplits(String query) {
  final words = normalizeForMatch(query, dropEdition: false)
      .split(' ')
      .where((w) => w.isNotEmpty)
      .toList();
  if (words.length < 3) return const [];
  final longest = words.length - 1 < _longestArtistName
      ? words.length - 1
      : _longestArtistName;
  final seen = <String>{};
  final splits = <ArtistTitleSplit>[];
  void add(List<String> artist, List<String> title) {
    final split = ArtistTitleSplit(artist.join(' '), title);
    if (seen.add('${split.artist}|${title.join(' ')}')) splits.add(split);
  }

  for (var k = 1; k <= longest; k++) {
    add(words.sublist(0, k), words.sublist(k));
    add(words.sublist(words.length - k), words.sublist(0, words.length - k));
  }
  return splits;
}

/// Whether every word of [title] begins a word of [songTitle] (so "space song" is found in "Space Song (Remastered)").
bool _titleCovered(List<String> title, String songTitle) {
  final have = normalizeForMatch(songTitle).split(' ');
  return title.every((w) => have.any((h) => h.startsWith(w)));
}

/// Whether [tracks] already hold a song by an artist named at one end of the query with the rest of the words in its title.
bool _answered(List<ArtistTitleSplit> splits, List<CatalogueTrack> tracks) {
  for (final t in tracks) {
    final artist = normalizeForMatch(t.artistName, dropEdition: false);
    for (final s in splits) {
      if (s.artist == artist && _titleCovered(s.title, t.title)) return true;
    }
  }
  return false;
}

/// Remembers what the catalogue said about an artist name and about an artist's popular songs, so the pauses of one person typing a long
/// query do not ask the same thing again and again (the catalogue allows about ten requests a second). An answer is kept ten minutes;
/// an answer of nothing only half a minute (most guessed names have no artist, but a request that failed looks the same).
class ArtistLookupCache {
  ArtistLookupCache({DateTime Function()? now}) : _now = now ?? DateTime.now;

  static const int _most = 100;
  static const Duration _keepAnswer = Duration(minutes: 10);
  static const Duration _keepNothing = Duration(seconds: 30);

  final DateTime Function() _now;
  final Map<String, _Remembered<CatalogueArtist>> _artists = {};
  final Map<String, _Remembered<CatalogueTrack>> _tops = {};

  Future<List<CatalogueArtist>> artists(CatalogueClient client, String name) =>
      _remember(_artists, name, () => client.searchArtists(name, limit: 5));

  Future<List<CatalogueTrack>> topTracks(CatalogueClient client, String id) =>
      _remember(_tops, id, () => client.artistTopTracks(id, limit: 50));

  Future<List<T>> _remember<T>(Map<String, _Remembered<T>> memory, String key,
      Future<List<T>> Function() ask) {
    final known = memory[key];
    if (known != null && !known.expired(_now())) return known.future;
    if (memory.length >= _most) memory.clear();
    final entry =
        _Remembered<T>(ask().then((list) => list, onError: (Object e) {
      Log.debug('search', 'a catalogue look-up failed: ${e.runtimeType}');
      return <T>[];
    }));
    memory[key] = entry;
    // The time is counted from when the answer arrived.
    unawaited(entry.future.then((list) {
      entry.until = _now().add(list.isEmpty ? _keepNothing : _keepAnswer);
    }));
    return entry.future;
  }
}

class _Remembered<T> {
  _Remembered(this.future);

  final Future<List<T>> future;

  /// `null` while the answer is awaited.
  DateTime? until;

  bool expired(DateTime now) => until != null && !now.isBefore(until!);
}

final artistLookupCacheProvider =
    Provider<ArtistLookupCache>((ref) => ArtistLookupCache());

/// [base] (the catalogue's text search for [query]) with the artist's own songs added when the typed words are an artist and a song
/// and the text search did not find it. Never throws: a failed look-up just leaves [base] as it was.
Future<CatalogueResults> withArtistSongs(
  CatalogueClient client,
  String query,
  CatalogueResults base, {
  ArtistLookupCache? cache,
}) async {
  final memory = cache ?? ArtistLookupCache();
  final splits = artistTitleSplits(query);
  if (splits.isEmpty || _answered(splits, base.tracks)) return base;

  // The artists the text search already found are known; the other names are asked for, all at once.
  final known = <String, List<CatalogueArtist>>{};
  for (final a in base.artists) {
    known
        .putIfAbsent(normalizeForMatch(a.name, dropEdition: false), () => [])
        .add(a);
  }
  final names = {for (final s in splits) s.artist}
      .where((n) => !known.containsKey(n))
      .toList();
  final asked = await Future.wait([
    for (final n in names) memory.artists(client, n),
  ]);
  for (var i = 0; i < names.length; i++) {
    known[names[i]] = [
      for (final a in asked[i])
        if (normalizeForMatch(a.name, dropEdition: false) == names[i]) a,
    ];
  }

  // The best known artist of each way of reading it, the best known readings first.
  final chosen = <(CatalogueArtist, ArtistTitleSplit)>[];
  final taken = <String>{};
  for (final s in splits) {
    final named = [...?known[s.artist]]
      ..sort((a, b) => (b.fans ?? 0).compareTo(a.fans ?? 0));
    if (named.isEmpty || (named.first.fans ?? 0) < _fewestFans) continue;
    if (taken.add(named.first.id)) chosen.add((named.first, s));
  }
  chosen.sort((a, b) => (b.$1.fans ?? 0).compareTo(a.$1.fans ?? 0));

  final songs = <CatalogueTrack>[];
  final artists = <CatalogueArtist>[];
  for (final (artist, split) in chosen.take(_artistsTried)) {
    final top = await memory.topTracks(client, artist.id);
    final found = [
      for (final t in top)
        if (_titleCovered(split.title, t.title)) t,
    ].take(_songsPerArtist).toList();
    if (found.isEmpty) continue;
    songs.addAll(found);
    artists.add(artist);
  }
  if (songs.isEmpty) return base;

  final knownTracks = {for (final t in songs) t.id};
  final knownArtists = {for (final a in artists) a.id};
  return CatalogueResults(
    artists: [
      ...artists,
      for (final a in base.artists)
        if (!knownArtists.contains(a.id)) a,
    ],
    albums: base.albums,
    tracks: [
      ...songs,
      for (final t in base.tracks)
        if (!knownTracks.contains(t.id)) t,
    ],
    ownedArtists: base.ownedArtists,
  );
}
