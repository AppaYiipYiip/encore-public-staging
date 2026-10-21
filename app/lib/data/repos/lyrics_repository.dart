import 'dart:convert';

import 'package:drift/drift.dart';

import '../../core/clock.dart';
import '../../core/logger.dart';
import '../../core/result.dart';
import '../../domain/lyrics.dart';
import '../api/lrclib_client.dart';
import '../api/opensubsonic/opensubsonic_client.dart';
import '../db/app_database.dart';

/// Lyrics lookup: local cache -> server -> LRCLIB, caching every hit so
/// lyrics work offline afterwards (and for downloaded tracks).
class LyricsRepository {
  LyricsRepository({
    required AppDatabase db,
    required int serverId,
    OpenSubsonicClient? server,
    LrcLibClient? lrclib,
    Clock clock = const SystemClock(),
  })  : _db = db,
        _serverId = serverId,
        _server = server,
        _lrclib = lrclib,
        _clock = clock;

  final AppDatabase _db;
  final int _serverId;
  final OpenSubsonicClient? _server;
  final LrcLibClient? _lrclib;
  final Clock _clock;

  /// Negative results are remembered for a day so a track without lyrics does
  /// not hit the network on every play.
  static const Duration _negativeTtl = Duration(days: 1);

  Future<TrackLyrics?> cached(String trackId) async {
    final row = await (_db.select(_db.lyrics)
          ..where(
              (l) => l.serverId.equals(_serverId) & l.trackId.equals(trackId)))
        .getSingleOrNull();
    if (row == null) return null;
    if (row.kind == 'none') return null;
    return _decode(row);
  }

  /// Per-track timing nudge (ms) chosen by the user.
  Future<int> offsetFor(String trackId) async {
    final row = await (_db.select(_db.lyrics)
          ..where(
              (l) => l.serverId.equals(_serverId) & l.trackId.equals(trackId)))
        .getSingleOrNull();
    return row?.offsetMs ?? 0;
  }

  Future<void> setOffset(String trackId, int offsetMs) async {
    await (_db.update(_db.lyrics)
          ..where(
              (l) => l.serverId.equals(_serverId) & l.trackId.equals(trackId)))
        .write(LyricsCompanion(offsetMs: Value(offsetMs)));
  }

  /// Best available lyrics for [track]; `null` when none exist anywhere.
  Future<TrackLyrics?> load({
    required String trackId,
    required String title,
    String? artist,
    String? album,
    int? durationSec,
    bool allowNetwork = true,
  }) async {
    final row = await (_db.select(_db.lyrics)
          ..where(
              (l) => l.serverId.equals(_serverId) & l.trackId.equals(trackId)))
        .getSingleOrNull();
    final nowMs = _clock.now().millisecondsSinceEpoch;

    if (row != null && row.kind != 'none') return _decode(row);
    if (row != null &&
        row.kind == 'none' &&
        nowMs - row.fetchedAtMs < _negativeTtl.inMilliseconds) {
      return null;
    }
    if (!allowNetwork) return null;

    // 1. The user's own server (embedded/sidecar lyrics - best quality).
    final server = _server;
    if (server != null) {
      final result = await server.getLyricsBySongId(trackId);
      if (result case Ok(:final value) when value != null) {
        final lyrics = TrackLyrics(
          lines: [
            for (final l in value.lines)
              LyricLine(
                startMs: value.synced ? l.startMs : null,
                text: l.text,
              ),
          ],
          synced: value.synced,
          source: 'server',
        );
        if (!lyrics.isEmpty) {
          // Plain text on the server is not the last word: LRCLIB may have the
          // synced version, which a person can follow and tap (a friend could
          // not tap a line of "Burden": the file's plain text had won).
          if (!lyrics.synced) {
            final upgraded = await _syncedFromLrclib(
                title: title,
                artist: artist,
                album: album,
                durationSec: durationSec);
            if (upgraded != null) {
              await _store(trackId, upgraded);
              return upgraded;
            }
          }
          await _store(trackId, lyrics);
          return lyrics;
        }
      }
    }

    // 2. LRCLIB.
    final lrclib = _lrclib;
    if (lrclib != null) {
      final result = await lrclib.find(
        title: title,
        artist: artist,
        album: album,
        durationSec: durationSec,
      );
      switch (result) {
        case Ok(:final value):
          if (value != null && !value.isEmpty) {
            await _store(trackId, value);
            return value;
          }
          await _storeNone(trackId);
        case Err(:final failure):
          // Network trouble: do not poison the cache with a "none".
          Log.debug('lyrics', 'LRCLIB failed: ${failure.message}');
      }
    }
    return null;
  }

  /// The synced lyrics of the same song from LRCLIB, or `null` (none, or the
  /// service cannot be reached: the plain text is still there).
  Future<TrackLyrics?> _syncedFromLrclib({
    required String title,
    String? artist,
    String? album,
    int? durationSec,
  }) async {
    final lrclib = _lrclib;
    if (lrclib == null) return null;
    final result = await lrclib.find(
      title: title,
      artist: artist,
      album: album,
      durationSec: durationSec,
      syncedOnly: true,
    );
    final found = result.valueOrNull;
    return found != null && found.synced && !found.isEmpty ? found : null;
  }

  TrackLyrics _decode(LyricsRow row) {
    if (row.kind == 'synced') {
      final lines = <LyricLine>[];
      final decoded = jsonDecode(row.body) as List;
      for (final item in decoded) {
        final m = (item as Map).cast<String, dynamic>();
        lines.add(LyricLine(
          startMs: m['t'] as int?,
          text: (m['x'] as String?) ?? '',
        ));
      }
      return TrackLyrics(lines: lines, synced: true, source: row.source);
    }
    return TrackLyrics(
      lines: [
        for (final t in row.body.split('\n')) LyricLine(startMs: null, text: t),
      ],
      synced: false,
      source: row.source,
    );
  }

  Future<void> _store(String trackId, TrackLyrics lyrics) async {
    final body = lyrics.synced
        ? jsonEncode([
            for (final l in lyrics.lines) {'t': l.startMs, 'x': l.text},
          ])
        : lyrics.lines.map((l) => l.text).join('\n');
    await _db.into(_db.lyrics).insertOnConflictUpdate(LyricsCompanion.insert(
          serverId: _serverId,
          trackId: trackId,
          kind: lyrics.synced ? 'synced' : 'plain',
          body: body,
          source: Value(lyrics.source),
          fetchedAtMs: _clock.now().millisecondsSinceEpoch,
        ));
  }

  Future<void> _storeNone(String trackId) async {
    await _db.into(_db.lyrics).insertOnConflictUpdate(LyricsCompanion.insert(
          serverId: _serverId,
          trackId: trackId,
          kind: 'none',
          body: '',
          fetchedAtMs: _clock.now().millisecondsSinceEpoch,
        ));
  }
}
