/// Reading the files a person can get out of Spotify and Google (docs/39 F1,
/// F9; ADR-101 item 4): the way in for what a link cannot give, a playlist
/// longer than the first hundred songs Spotify shows, and the liked songs.
///
/// Three layouts are understood, all as plain text so nothing here needs a
/// file system:
///
/// * **Spotify "Download your data"** (`YourLibrary.json`, `Playlist1.json`):
///   JSON with the person's liked songs and their playlists.
/// * **Exportify** (a free site that exports one playlist, or the liked songs,
///   of a Spotify account as CSV): `Track Name`, `Artist Name(s)`,
///   `Album Name`, `Duration (ms)`.
/// * **Google Takeout, YouTube Music** ("music library songs.csv"): `Song
///   Title`, `Album Title`, `Artist Name 1`... A file with only video ids
///   (the "videos" playlists) cannot be used and is said so.
///
/// Anything else that has a title column and an artist column works too.
library;

import 'dart:convert';

import '../data/fetch/import_models.dart';

/// One list found in a file: a playlist to make, or the liked songs.
class ImportFileEntry {
  const ImportFileEntry({
    required this.name,
    required this.tracks,
    this.liked = false,
  });

  final String name;
  final List<ImportedTrack> tracks;

  /// The person's liked / saved songs: they are liked here, no playlist.
  final bool liked;
}

/// What a file held. [problem] is a sentence for the person when nothing
/// usable was found.
class ImportFileResult {
  const ImportFileResult(this.entries, {this.problem, this.skipped = 0});

  final List<ImportFileEntry> entries;
  final String? problem;

  /// Rows that had no title or no artist and were left out.
  final int skipped;

  int get songs => entries.fold(0, (sum, e) => sum + e.tracks.length);
}

const String _unreadable =
    'That file does not look like a list of songs. Use the file Spotify '
    'sends you (YourLibrary.json or a Playlist file), an Exportify CSV, or '
    'a YouTube Music songs CSV from Google Takeout.';

const String _onlyIds =
    'That file lists only YouTube video numbers, no song titles, so the '
    'songs cannot be found by name. Use "music library songs.csv" from '
    'Google Takeout, or paste the playlist link.';

/// Reads [text] (the whole file); [fileName] names a CSV's playlist.
ImportFileResult parseImportFile(String text, {String fileName = ''}) {
  var body = text;
  if (body.startsWith('﻿')) body = body.substring(1);
  final trimmed = body.trimLeft();
  if (trimmed.isEmpty) return const ImportFileResult([], problem: _unreadable);
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    return _fromJson(trimmed);
  }
  return _fromCsv(body, fileName);
}

// ------------------------------------------------------------------ JSON

ImportFileResult _fromJson(String text) {
  final Object? data;
  try {
    data = jsonDecode(text);
  } on FormatException {
    return const ImportFileResult([], problem: _unreadable);
  }
  final entries = <ImportFileEntry>[];
  var skipped = 0;

  ImportedTrack? track({String? title, String? artist, String? album}) {
    final t = _clean(title);
    final a = _clean(artist);
    if (t == null || a == null) {
      skipped++;
      return null;
    }
    return ImportedTrack(title: t, artist: a, album: _clean(album));
  }

  if (data is Map) {
    // Playlist1.json: {"playlists": [{"name": ..., "items": [{"track": {...}}]}]}
    final playlists = data['playlists'];
    if (playlists is List) {
      for (final p in playlists) {
        if (p is! Map) continue;
        final songs = <ImportedTrack>[];
        for (final item in (p['items'] as List? ?? const [])) {
          final t = item is Map ? item['track'] : null;
          if (t is! Map) continue; // an episode or a local file
          final made = track(
              title: t['trackName'] as String?,
              artist: t['artistName'] as String?,
              album: t['albumName'] as String?);
          if (made != null) songs.add(made);
        }
        if (songs.isNotEmpty) {
          entries.add(ImportFileEntry(
              name: _clean(p['name'] as String?) ?? 'Imported playlist',
              tracks: songs));
        }
      }
    }
    // YourLibrary.json: {"tracks": [{"artist": ..., "album": ..., "track": ...}]}
    final liked = data['tracks'];
    if (liked is List) {
      final songs = <ImportedTrack>[];
      for (final t in liked) {
        if (t is! Map) continue;
        final made = track(
            title: t['track'] as String?,
            artist: t['artist'] as String?,
            album: t['album'] as String?);
        if (made != null) songs.add(made);
      }
      if (songs.isNotEmpty) {
        entries.insert(0,
            ImportFileEntry(name: 'Liked songs', tracks: songs, liked: true));
      }
    }
  } else if (data is List) {
    // A bare list of {track, artist} (or the same keys as above).
    final songs = <ImportedTrack>[];
    for (final t in data) {
      if (t is! Map) continue;
      final made = track(
          title: (t['track'] ?? t['trackName'] ?? t['title']) as String?,
          artist: (t['artist'] ?? t['artistName']) as String?,
          album: (t['album'] ?? t['albumName']) as String?);
      if (made != null) songs.add(made);
    }
    if (songs.isNotEmpty) {
      entries.add(ImportFileEntry(name: 'Imported playlist', tracks: songs));
    }
  }
  if (entries.isEmpty) {
    return ImportFileResult(const [], problem: _unreadable, skipped: skipped);
  }
  return ImportFileResult(entries, skipped: skipped);
}

// ------------------------------------------------------------------- CSV

const _titleColumns = [
  'track name',
  'song title',
  'track',
  'title',
  'song',
  'name',
];
const _artistColumns = [
  'artist name(s)',
  'artist name 1',
  'artist name',
  'artist(s)',
  'artists',
  'artist',
];
const _albumColumns = ['album name', 'album title', 'album'];
const _durationColumns = ['duration (ms)', 'duration_ms', 'duration'];

ImportFileResult _fromCsv(String text, String fileName) {
  final rows = parseCsv(text);
  if (rows.length < 2) {
    return const ImportFileResult([], problem: _unreadable);
  }
  final header = [for (final h in rows.first) h.trim().toLowerCase()];
  int? find(List<String> names) {
    for (final n in names) {
      final i = header.indexOf(n);
      if (i >= 0) return i;
    }
    return null;
  }

  final titleAt = find(_titleColumns);
  final artistAt = find(_artistColumns);
  if (titleAt == null || artistAt == null) {
    final onlyIds = header.contains('video id') || header.contains('videoid');
    return ImportFileResult(const [],
        problem: onlyIds ? _onlyIds : _unreadable);
  }
  final albumAt = find(_albumColumns);
  final durationAt = find(_durationColumns);
  final durationIsMs = durationAt != null && header[durationAt].contains('ms');

  final songs = <ImportedTrack>[];
  var skipped = 0;
  for (final row in rows.skip(1)) {
    if (row.every((c) => c.trim().isEmpty)) continue;
    String? at(int? i) => i == null || i >= row.length ? null : row[i];
    final title = _clean(at(titleAt));
    // "Artist A;Artist B" or "Artist A, Artist B": the first is the artist.
    final artist = _clean(at(artistAt)?.split(RegExp(r'[;|]')).first);
    if (title == null || artist == null) {
      skipped++;
      continue;
    }
    int? seconds;
    final raw = double.tryParse(at(durationAt)?.trim() ?? '');
    if (raw != null && raw > 0) {
      seconds = (durationIsMs || raw > 20000 ? raw / 1000 : raw).round();
    }
    songs.add(ImportedTrack(
      title: title,
      artist: artist,
      album: _clean(at(albumAt)),
      durationSec: seconds,
    ));
  }
  if (songs.isEmpty) {
    return ImportFileResult(const [], problem: _unreadable, skipped: skipped);
  }
  final name = _nameFromFile(fileName);
  final liked = RegExp(r'liked|saved|favou?rite|your.?library|gillade',
          caseSensitive: false)
      .hasMatch(fileName);
  return ImportFileResult(
    [ImportFileEntry(name: name, tracks: songs, liked: liked)],
    skipped: skipped,
  );
}

String _nameFromFile(String fileName) {
  var name = fileName.split(RegExp(r'[\\/]')).last;
  name = name.replaceFirst(RegExp(r'\.[A-Za-z0-9]{1,5}$'), '');
  name = name.replaceAll(RegExp(r'[_]+'), ' ').trim();
  return name.isEmpty ? 'Imported playlist' : name;
}

String? _clean(String? value) {
  if (value == null) return null;
  final text = value.replaceAll(RegExp(r'\s+'), ' ').trim();
  return text.isEmpty ? null : text;
}

/// A small RFC 4180 reader: quoted fields with commas, doubled quotes and
/// line breaks inside, `\r\n` or `\n`, and a `;` or tab as the separator when
/// the first line uses that instead of a comma.
List<List<String>> parseCsv(String text) {
  final firstLine = text.split(RegExp(r'\r?\n')).first;
  var separator = ',';
  for (final candidate in const [';', '\t']) {
    if (_count(firstLine, candidate) > _count(firstLine, separator)) {
      separator = candidate;
    }
  }
  final rows = <List<String>>[];
  var row = <String>[];
  final field = StringBuffer();
  var quoted = false;
  var fieldStarted = false;
  void endField() {
    row.add(field.toString());
    field.clear();
    fieldStarted = false;
  }

  void endRow() {
    endField();
    rows.add(row);
    row = <String>[];
  }

  for (var i = 0; i < text.length; i++) {
    final ch = text[i];
    if (quoted) {
      if (ch == '"') {
        if (i + 1 < text.length && text[i + 1] == '"') {
          field.write('"');
          i++;
        } else {
          quoted = false;
        }
      } else {
        field.write(ch);
      }
      continue;
    }
    if (ch == '"' && !fieldStarted) {
      quoted = true;
      fieldStarted = true;
    } else if (ch == separator) {
      endField();
    } else if (ch == '\n') {
      endRow();
    } else if (ch == '\r') {
      if (i + 1 < text.length && text[i + 1] == '\n') i++;
      endRow();
    } else {
      field.write(ch);
      fieldStarted = true;
    }
  }
  if (fieldStarted || field.isNotEmpty || row.isNotEmpty) endRow();
  return rows;
}

int _count(String text, String char) => char.allMatches(text).length;
