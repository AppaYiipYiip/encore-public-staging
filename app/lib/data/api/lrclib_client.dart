import 'package:dio/dio.dart';

import '../../core/result.dart';
import '../../domain/lyrics.dart';

/// Minimal LRCLIB client (<https://lrclib.net>, free, no key) used as the
/// lyrics fallback when the server has none.
class LrcLibClient {
  LrcLibClient({Dio? dio})
      : _dio = dio ??
            Dio(BaseOptions(
              baseUrl: 'https://lrclib.net/api',
              connectTimeout: const Duration(seconds: 5),
              receiveTimeout: const Duration(seconds: 10),
              headers: const {
                'User-Agent':
                    'Encore/0.1 (https://github.com/AppaYiipYiip/encore)',
              },
            ));

  final Dio _dio;

  /// How far off the length of a song may be for a lyrics entry to be the same
  /// version of it (a live cut or a remix is some other length).
  static int toleranceSec(int wanted) => wanted ~/ 50 < 3 ? 3 : wanted ~/ 50;

  /// Looks lyrics up by metadata. `Ok(null)` means "no lyrics exist";
  /// failures are network problems and may be retried later.
  ///
  /// The exact lookup (artist, title, album and length identical) comes first;
  /// when it finds nothing, or only plain text while [syncedOnly], a search by
  /// title and artist takes the synced entry nearest in length. With
  /// [syncedOnly] a plain-only answer is `null`.
  Future<Result<TrackLyrics?>> find({
    required String title,
    String? artist,
    String? album,
    int? durationSec,
    bool syncedOnly = false,
  }) =>
      guard(() async {
        try {
          final exact = await _exact(title, artist, album, durationSec);
          if (exact != null && (!syncedOnly || exact.synced)) return exact;
          final searched =
              await _search(title, artist, durationSec, syncedOnly: syncedOnly);
          return searched ?? (syncedOnly ? null : exact);
        } on DioException catch (e) {
          throw NetworkFailure('Lyrics service unreachable', cause: e);
        }
      });

  Future<TrackLyrics?> _exact(
      String title, String? artist, String? album, int? durationSec) async {
    try {
      final response = await _dio.get<Object?>(
        '/get',
        queryParameters: {
          'track_name': title,
          if (artist != null) 'artist_name': artist,
          if (album != null) 'album_name': album,
          if (durationSec != null) 'duration': durationSec,
        },
      );
      return _parse(response.data);
    } on DioException catch (e) {
      if (e.response?.statusCode == 404) return null;
      rethrow;
    }
  }

  Future<TrackLyrics?> _search(String title, String? artist, int? durationSec,
      {required bool syncedOnly}) async {
    final response = await _dio.get<Object?>(
      '/search',
      queryParameters: {
        'track_name': title,
        if (artist != null) 'artist_name': artist,
      },
    );
    final data = response.data;
    if (data is! List) return null;
    Map<Object?, Object?>? best;
    var bestGap = 1 << 30;
    var bestSynced = false;
    for (final item in data) {
      if (item is! Map) continue;
      final synced =
          (item['syncedLyrics'] as String?)?.trim().isNotEmpty ?? false;
      final plain =
          (item['plainLyrics'] as String?)?.trim().isNotEmpty ?? false;
      if (!synced && (syncedOnly || !plain)) continue;
      final length = (item['duration'] as num?)?.round();
      var gap = 0;
      if (durationSec != null) {
        if (length == null) continue;
        gap = (length - durationSec).abs();
        if (gap > toleranceSec(durationSec)) continue; // another version
      }
      // Synced beats plain; then the nearest length.
      if (best == null ||
          (synced && !bestSynced) ||
          (synced == bestSynced && gap < bestGap)) {
        best = item;
        bestGap = gap;
        bestSynced = synced;
      }
    }
    return best == null ? null : _parse(best);
  }

  static TrackLyrics? _parse(Object? data) {
    if (data is! Map) return null;
    final synced = data['syncedLyrics'];
    if (synced is String && synced.trim().isNotEmpty) {
      return parseLrc(synced, source: 'lrclib');
    }
    final plain = data['plainLyrics'];
    if (plain is String && plain.trim().isNotEmpty) {
      return parseLrc(plain, source: 'lrclib');
    }
    return null;
  }
}
