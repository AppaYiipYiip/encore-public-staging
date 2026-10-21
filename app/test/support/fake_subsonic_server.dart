import 'fake_http.dart';

/// A tiny in-memory Subsonic/Navidrome server for contract and sync tests.
///
/// Mutate the public lists between sync runs to simulate server-side changes.
class FakeSubsonicServer {
  FakeSubsonicServer() {
    adapter = FakeHttpAdapter(routes: {
      'ping': (_) => FakeResponse.json(subsonicOk({})),
      'getOpenSubsonicExtensions': (_) =>
          FakeResponse.json(subsonicOk({'openSubsonicExtensions': <Object>[]})),
      'getScanStatus': (_) => FakeResponse.json(subsonicOk({
            'scanStatus': {
              'scanning': scanning,
              'count': songs.length,
              'folderCount': 1,
              'lastScan': lastScan,
            },
          })),
      'getArtists': (_) => FakeResponse.json(subsonicOk({
            'artists': {
              'index': [
                {'name': 'A', 'artist': artists},
              ],
            },
          })),
      'getAlbumList2': (r) {
        final size = int.parse(r.param('size') ?? '500');
        final offset = int.parse(r.param('offset') ?? '0');
        return FakeResponse.json(subsonicOk({
          'albumList2': {'album': _page(albums, offset, size)},
        }));
      },
      'search3': (r) {
        final size = int.parse(r.param('songCount') ?? '0');
        final offset = int.parse(r.param('songOffset') ?? '0');
        return FakeResponse.json(subsonicOk({
          'searchResult3': {'song': _page(songs, offset, size)},
        }));
      },
      'getPlaylists': (_) => FakeResponse.json(subsonicOk({
            'playlists': {
              'playlist': [
                for (final p in playlists)
                  {
                    for (final e in p.entries.where((e) => e.key != 'entry'))
                      e.key: e.value
                  },
              ],
            },
          })),
      'getPlaylist': (r) {
        final id = r.param('id');
        final p = playlists.where((p) => p['id'] == id);
        if (p.isEmpty) {
          return FakeResponse.json(subsonicError(70, 'playlist not found'));
        }
        return FakeResponse.json(subsonicOk({'playlist': p.first}));
      },
      'getStarred2': (_) => FakeResponse.json(subsonicOk({
            'starred2': {
              'song': [
                for (final s in songs)
                  if (starredSongIds.contains(s['id']))
                    {...s, 'starred': '2026-10-01T00:00:00Z'},
              ],
            },
          })),
    });
  }

  late final FakeHttpAdapter adapter;

  List<Map<String, Object?>> artists = [];
  List<Map<String, Object?>> albums = [];
  List<Map<String, Object?>> songs = [];
  List<Map<String, Object?>> playlists = [];
  Set<String> starredSongIds = {};
  bool scanning = false;
  String lastScan = '2026-10-14T10:00:00.000000000Z';

  /// Convenience: replace the library with [songCount] generated songs spread
  /// over [albumCount] albums by one artist.
  void seed({int songCount = 30, int albumCount = 3}) {
    artists = [
      {'id': 'ar1', 'name': 'Alcest', 'albumCount': albumCount},
    ];
    albums = [
      for (var a = 0; a < albumCount; a++)
        {
          'id': 'al$a',
          'name': 'Album $a',
          'artist': 'Alcest',
          'artistId': 'ar1',
          'songCount': songCount ~/ albumCount,
          'duration': 100 * (songCount ~/ albumCount),
          'created': '2026-10-09T21:27:34.835687354Z',
          'coverArt': 'al-al$a',
        },
    ];
    songs = [
      for (var i = 0; i < songCount; i++) song(i, album: i % albumCount),
    ];
  }

  static Map<String, Object?> song(
    int i, {
    int album = 0,
    String? title,
    int size = 5000000,
    String suffix = 'mp3',
  }) =>
      {
        'id': 's$i',
        'title': title ?? 'Song $i',
        'album': 'Album $album',
        'albumId': 'al$album',
        'artist': 'Alcest',
        'artistId': 'ar1',
        'track': i,
        'duration': 200,
        'size': size,
        'suffix': suffix,
        'bitRate': 320,
        'created': '2026-10-09T21:27:34.835687354Z',
      };

  static Map<String, Object?> playlist(
    String id,
    String name, {
    List<String> songIds = const [],
    bool readonly = false,
    String changed = '2026-10-10T00:00:00Z',
    List<Map<String, Object?>>? library,
  }) =>
      {
        'id': id,
        'name': name,
        'songCount': songIds.length,
        'duration': songIds.length * 200,
        'readonly': readonly,
        'changed': changed,
        'created': '2026-10-01T00:00:00Z',
        'entry': [
          for (final sid in songIds)
            library?.firstWhere((s) => s['id'] == sid,
                    orElse: () => {'id': sid, 'title': 'Song $sid'}) ??
                {'id': sid, 'title': 'Song $sid'},
        ],
      };

  static List<Map<String, Object?>> _page(
    List<Map<String, Object?>> source,
    int offset,
    int size,
  ) {
    if (offset >= source.length) return const [];
    final end = (offset + size).clamp(0, source.length);
    return source.sublist(offset, end);
  }
}
