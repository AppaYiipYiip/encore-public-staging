import 'package:encore/data/db/app_database.dart';
import 'package:encore/playback/queue_model.dart';

/// A track row with sensible defaults for tests that do not need a database.
TrackRow trackRow(
  String id, {
  String? title,
  String? artist = 'Artist',
  String? album = 'Album',
  String? albumId = 'al1',
  int? durationSec = 200,
  int? starredAtMs,
  double? rgTrackGain,
  double? rgTrackPeak,
}) =>
    TrackRow(
      serverId: 1,
      id: id,
      albumId: albumId,
      artistId: 'ar1',
      title: title ?? 'Song $id',
      album: album,
      artist: artist,
      durationSec: durationSec,
      suffix: 'flac',
      bitRate: 900,
      rgTrackGain: rgTrackGain,
      rgTrackPeak: rgTrackPeak,
      starredAtMs: starredAtMs,
      missing: false,
      fingerprint: '',
      audioKey: 'k-$id',
      syncRun: 0,
      isRef: false,
      explicit: false,
    );

/// `n` queue items `t1..tn`.
List<QueueItem> queueItems(int n, {int uidStart = 1}) => [
      for (var i = 1; i <= n; i++)
        QueueItem(uid: uidStart + i - 1, id: 't$i', title: 'Song $i'),
    ];
