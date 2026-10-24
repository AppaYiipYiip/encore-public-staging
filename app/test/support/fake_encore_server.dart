import 'dart:convert';

import 'fake_http.dart';

/// An in-memory Encore server (docs/17) behind [FakeHttpAdapter]: the same rules as the real one for the parts the app uses - refs found by
/// what describes them, likes as a set, playlists with fractional positions and client-made ids, state-based change feeds with cursors, the
/// feed of the server's files. Every write is idempotent, as on the real server.
///
/// The shapes are the ones the Python server's tests pin down (`server/encore_server/tests`), so a change on either side shows up here.
class FakeEncoreServer {
  FakeEncoreServer({this.user = 'tester'}) {
    adapter = FakeHttpAdapter()..fallback = _dispatch;
    _handlers['/encore/api/v1/info'] = (r) => _info();
    _handlers['/encore/api/v1/server'] = (r) => _ok({
          'serverId': serverId,
          'name': 'Fake Encore',
          'addresses': [
            for (final a in addresses) {'kind': a.$1, 'url': a.$2}
          ],
        });
    _handlers['/encore/api/v1/refs/resolve'] = _resolve;
    _handlers['/encore/api/v1/library/changes'] = _changes;
    _handlers['/encore/api/v1/library/files'] = _files;
    _handlers['/encore/api/v1/plays'] = _plays;
    _handlers['/encore/api/v1/migrate/navidrome'] = (r) {
      migrations++;
      return failMigration
          ? _error(500, 'internal')
          : _ok({'report': migrationReport});
    };
    _handlers['/encore/api/v1/playlists'] = _playlistsRoot;
    _handlers['/encore/api/v1/me'] = (r) => _ok({
          'id': 'pn_me',
          'name': user,
          'username': user,
          'role': myRole,
          'explicitOk': true,
          'federationOk': true,
        });
    _handlers['/encore/api/v1/invites'] = _invitesRoot;
    _handlers['/encore/api/v1/imports'] = _importsRoot;
    _handlers['/encore/api/v1/people'] = (r) => _ok({'items': people});
    _handlers['/encore/api/v1/auth/logout'] = (r) {
      logouts.add(r.headers['x-encore-device']);
      return _ok(<String, Object?>{});
    };
    _handlers['/encore/api/v1/auth/login'] = (r) {
      logins++;
      if (failLogin) return _error(401, 'unauthorized');
      return _ok({
        'deviceToken': 'ed_fake$logins',
        'device': {'id': 'dv_$logins', 'name': 'Android phone'},
        'person': {'id': 'pn_me', 'name': user, 'role': myRole},
      });
    };
  }

  /// The device ids the phone asked to end (`POST /auth/logout`, named by `X-Encore-Device`).
  final List<String?> logouts = [];

  /// How many times a phone signed in as a device, and whether the server refuses that.
  int logins = 0;
  bool failLogin = false;

  /// What the server's reader finds behind any link it is given (title, artist), and the picture it gives the playlist.
  List<(String, String)> linkSongs = [
    ('Song A', 'Artist'),
    ('Song B', 'Artist'),
    ('Song C', 'Artist'),
  ];
  String? linkPicture;
  final List<Map<String, Object?>> importRows = [];

  /// This person's role on the server (`owner` or `member`).
  String myRole = 'owner';

  /// The people the owner sees, and the invitations (what a test arranges or reads back).
  final List<Map<String, Object?>> people = [];
  final List<Map<String, Object?>> inviteRows = [];
  int _inviteCount = 0;

  final String user;
  late final FakeHttpAdapter adapter;

  /// What `/info` says about YouTube: `ok`, `resting` or `off`.
  String youtubeState = 'ok';

  /// What a test can arrange or look at.
  final Map<String, Map<String, Object?>> refs = {};
  final Map<String, int> likes = {}; // ref -> at
  final Map<String, Map<String, Object?>> playlists = {};
  final Map<String, List<Map<String, Object?>>> entries =
      {}; // playlist -> entries (all, with deleted)
  final List<Map<String, Object?>> plays = [];
  final List<({int seq, String kind, String target})> _log = [];
  final List<({int seq, String ref})> _fileLog = [];
  int _seq = 0;
  int _fileSeq = 0;
  int clockMs = 1790000000000;
  bool online = true;

  /// How many requests of each route were made (`PUT /likes/...` is counted under `PUT likes`).
  final Map<String, int> calls = {};

  /// How many times the phone asked the server to bring the person's library over from the music server, and what the server says it did.
  int migrations = 0;

  /// The server answers the move with an error (a test of what the phone does then).
  bool failMigration = false;
  Map<String, Object?> migrationReport = {
    'likes': 0,
    'albums': 0,
    'artists': 0,
    'playlists': 0,
    'entries': 0,
    'unmatched': 0
  };

  int _refCount = 0;

  String _newRef() => 'sr_${(++_refCount).toString().padLeft(26, '0')}';

  final Map<String, FakeHandler> _handlers = {};

  // -------------------------------------------------------------- what a test arranges

  /// A song the server knows, optionally with a kept file.
  String addRef(String title, String artist,
      {String? album,
      int durationMs = 200000,
      String? fileId,
      Map<String, Object?> meta = const {},
      String? videoId}) {
    final id = _newRef();
    refs[id] = {
      'id': id,
      'title': title,
      'artists': [artist],
      'album': album,
      'albumArtist': null,
      'trackNo': null,
      'discNo': null,
      'year': null,
      'durationMs': durationMs,
      'isrc': null,
      'mbid': null,
      'deezerId': null,
      'videoId': videoId,
      'coverUrl': null,
      'explicit': false,
      'file': null,
    };
    if (fileId != null) attachFile(id, fileId, meta: meta);
    return id;
  }

  /// A playlist the server already holds for the person (what bringing it over from the music server leaves): its songs, in order.
  void addPlaylist(String id, String name, List<String> refIds,
      {String? sourceId}) {
    playlists[id] = {
      'id': id,
      'name': name,
      'cover': null,
      'collaborative': false,
      'createdAt': clockMs,
      'updatedAt': clockMs,
      'deleted': false,
      'sourceId': sourceId,
    };
    entries[id] = [
      for (var i = 0; i < refIds.length; i++)
        {
          'id': 'pe_${id.substring(3, 8)}${i.toString().padLeft(21, '0')}',
          'playlist': id,
          'ref': refIds[i],
          'position': i + 1.0,
          'addedAt': clockMs,
          'deleted': false,
        },
    ];
    _touch('playlist', id);
    for (final e in entries[id]!) {
      _touch('entry', e['id']! as String);
    }
  }

  void attachFile(String refId, String fileId,
      {Map<String, Object?> meta = const {}}) {
    refs[refId]!['file'] = {
      'id': 'sf_$fileId',
      'navidromeSongId': fileId,
      'codec': 'opus',
      'bitrateKbps': 128,
      'meta': meta,
    };
    _fileLog.add((seq: ++_fileSeq, ref: refId));
    for (final like in likes.keys.where((r) => r == refId)) {
      _touch('like', like);
    }
  }

  void removeFile(String refId) {
    refs[refId]!['file'] = null;
    _fileLog.add((seq: ++_fileSeq, ref: refId));
  }

  void _touch(String kind, String target) =>
      _log.add((seq: ++_seq, kind: kind, target: target));

  /// Another device likes a song, creates a playlist, ... (what the app should see arrive).
  void otherDeviceLikes(String refId) => _like(refId);

  /// What another device of the same person does, as a request to the server (for tests: `call('PUT', '/encore/api/v1/likes/sr_...')`).
  Future<FakeResponse> call(String method, String path, [Object? body]) =>
      _dispatch(RecordedRequest(
        method: method,
        uri: Uri.parse('http://fake.test$path'),
        body: body == null ? '' : jsonEncode(body),
        contentType: 'application/json',
      ));

  // -------------------------------------------------------------- the routes

  Future<FakeResponse> _dispatch(RecordedRequest r) async {
    if (!online) return const FakeResponse.connectionError();
    final path = r.uri.path;
    final key = '${r.method} ${_shape(path)}';
    calls[key] = (calls[key] ?? 0) + 1;
    final exact = _handlers[path];
    if (exact != null) return exact(r);
    final likeMatch =
        RegExp(r'^/encore/api/v1/likes/(sr_\w+)$').firstMatch(path);
    if (likeMatch != null) {
      final ref = likeMatch.group(1)!;
      if (!refs.containsKey(ref)) return _error(404, 'not_found');
      if (r.method == 'PUT') {
        _like(ref, atMs: _atOf(r));
      } else if (r.method == 'DELETE' && likes.remove(ref) != null) {
        _touch('like', ref);
      }
      return _ok({'changed': true, 'cursor': '$_seq'});
    }
    final inviteMatch =
        RegExp(r'^/encore/api/v1/invites/(iv_\w+)$').firstMatch(path);
    if (inviteMatch != null && r.method == 'DELETE') {
      final row =
          inviteRows.where((i) => i['id'] == inviteMatch.group(1)).firstOrNull;
      if (row == null) return _error(404, 'not_found');
      row['state'] = 'revoked';
      return _ok({'changed': true});
    }
    final personMatch =
        RegExp(r'^/encore/api/v1/people/(pn_\w+)$').firstMatch(path);
    if (personMatch != null) {
      final row =
          people.where((p) => p['id'] == personMatch.group(1)).firstOrNull;
      if (row == null) return _error(404, 'not_found');
      if (r.method == 'DELETE') {
        people.remove(row);
        return _ok({'removed': true});
      }
      final body = jsonDecode(r.body) as Map;
      if (body['role'] != null) row['role'] = body['role'];
      if (body['locked'] != null) row['locked'] = body['locked'];
      return _ok(row);
    }
    final streamMatch =
        RegExp(r'^/encore/api/v1/refs/(sr_\w+)/stream-url$').firstMatch(path);
    if (streamMatch != null) {
      return _ok({
        'url':
            '/encore/stream/${streamMatch.group(1)}?p=pn_x&e=9999999999&sig=abc',
        'expiresAt': 9999999999000
      });
    }
    final refMatch = RegExp(r'^/encore/api/v1/refs/(sr_\w+)$').firstMatch(path);
    if (refMatch != null) {
      final ref = refs[refMatch.group(1)];
      return ref == null ? _error(404, 'not_found') : _ok(ref);
    }
    final entriesMatch =
        RegExp(r'^/encore/api/v1/playlists/(pl_\w+)/entries$').firstMatch(path);
    if (entriesMatch != null) return _entriesRoute(entriesMatch.group(1)!, r);
    final orderMatch =
        RegExp(r'^/encore/api/v1/playlists/(pl_\w+)/order$').firstMatch(path);
    if (orderMatch != null) return _orderRoute(orderMatch.group(1)!, r);
    final playlistMatch =
        RegExp(r'^/encore/api/v1/playlists/(pl_\w+)$').firstMatch(path);
    if (playlistMatch != null) {
      return _playlistRoute(playlistMatch.group(1)!, r);
    }
    return _error(404, 'not_found');
  }

  static String _shape(String path) => path
      .replaceAll(RegExp(r'(sr|pl|pe)_\w+'), '{id}')
      .replaceFirst('/encore/api/v1/', '');

  int? _atOf(RecordedRequest r) {
    if (r.body.isEmpty) return null;
    final body = jsonDecode(r.body);
    return body is Map ? body['at'] as int? : null;
  }

  void _like(String ref, {int? atMs}) {
    if (likes.containsKey(ref)) return;
    likes[ref] = atMs ?? clockMs++;
    _touch('like', ref);
  }

  FakeResponse _importsRoot(RecordedRequest r) {
    if (r.method != 'POST') return _ok({'imports': importRows});
    final body = jsonDecode(r.body) as Map;
    final id = '${body['id']}';
    final again = importRows.where((i) => i['id'] == id).firstOrNull;
    if (again != null) {
      return _ok({'import': again, 'playlistId': again['playlistId']},
          status: 201);
    }
    final songs = body['songs'] is List
        ? [
            for (final s
                in (body['songs'] as List).cast<Map<String, Object?>>())
              ('${s['title']}', '${(s['artists'] as List).first}')
          ]
        : linkSongs;
    final made = [
      for (final (title, artist) in songs) refs[_resolveOne(title, artist)]!
    ];
    final liked = body['liked'] == true;
    String? playlistId;
    if (liked) {
      for (final ref in made) {
        _like(ref['id']! as String);
      }
    } else {
      playlistId = 'pl_${(++_importPlaylists).toString().padLeft(26, '0')}';
      addPlaylist(playlistId, '${body['name'] ?? 'Imported playlist'}',
          [for (final ref in made) ref['id']! as String]);
      playlists[playlistId]!['cover'] = linkPicture;
    }
    final row = <String, Object?>{
      'id': id,
      'source': body['source'] ?? 'youtube',
      'name': '${body['name'] ?? 'Imported playlist'}',
      'state': 'running',
      'playlistId': playlistId,
      'total': made.length,
      'matched': 0,
      'unmatched': 0,
      'pending': made.length,
      'kept': 0,
      'truncated': false,
      'createdAt': clockMs,
    };
    importRows.add(row);
    return _ok({'import': row, 'playlistId': playlistId}, status: 201);
  }

  int _importPlaylists = 0;

  String _resolveOne(String title, String artist) {
    final found = refs.values
        .where((r) =>
            '${r['title']}' == title &&
            ((r['artists'] as List).first as String) == artist)
        .firstOrNull;
    return found == null ? addRef(title, artist) : found['id']! as String;
  }

  FakeResponse _invitesRoot(RecordedRequest r) {
    if (r.method == 'POST') {
      final body = r.body.isEmpty
          ? const <String, Object?>{}
          : jsonDecode(r.body) as Map;
      final id = 'iv_${(++_inviteCount).toString().padLeft(26, '0')}';
      final row = <String, Object?>{
        'id': id,
        'role': body['role'] ?? 'member',
        'note': body['note'],
        'createdAt': clockMs,
        'expiresAt': clockMs + 7 * 24 * 3600 * 1000,
        'state': 'open',
        'usedBy': null,
        'usedAt': null,
      };
      inviteRows.add(row);
      return _ok({
        'invite': {...row, 'code': 'ABCD-EFGH-JK$_inviteCount'}
      }, status: 201);
    }
    return _ok({'items': inviteRows});
  }

  /// What `GET /server` says about this server: its key and the addresses it has (`('home', 'http://...')`).
  String? serverId;
  final List<(String, String)> addresses = [];

  FakeResponse _info() => _ok({
        'apiVersion': '1.0',
        'minAppVersion': '0.1.0',
        'serverVersion': '0.1.0',
        'name': 'Fake Encore',
        'features': ['library', 'playback', 'live', 'refs', 'keep'],
        'youtube': {'state': youtubeState, 'resumesInSec': 0},
      });

  FakeResponse _resolve(RecordedRequest r) {
    final songs = (jsonDecode(r.body) as Map)['songs'] as List;
    final items = <Map<String, Object?>>[];
    for (final s in songs.cast<Map<String, Object?>>()) {
      final title = '${s['title']}';
      final artists = [
        for (final a in (s['artists'] as List? ?? const [])) '$a'
      ];
      final artist = artists.isEmpty ? '' : artists.first;
      final duration = s['durationMs'] as int?;
      final found = refs.values.where((ref) {
        final same = ('${ref['title']}'.toLowerCase() == title.toLowerCase()) &&
            (((ref['artists'] as List).first as String).toLowerCase() ==
                artist.toLowerCase());
        final d = ref['durationMs'] as int?;
        return same &&
            (duration == null || d == null || (duration - d).abs() <= 3000);
      }).firstOrNull;
      if (found != null) {
        items.add(found);
      } else {
        final id = addRef(title, artist,
            album: s['album'] as String?,
            durationMs: duration ?? 200000,
            videoId: s['videoId'] as String?);
        refs[id]!['coverUrl'] = s['coverUrl'];
        refs[id]!['isrc'] = s['isrc'];
        items.add(refs[id]!);
      }
    }
    return _ok({'items': items});
  }

  FakeResponse _changes(RecordedRequest r) {
    final since = int.parse(r.param('since') ?? '0');
    final touched = _log.where((e) => e.seq > since).toList();
    final cursor = touched.isEmpty ? since : touched.last.seq;
    final targets = <String, Set<String>>{};
    for (final e in touched) {
      targets.putIfAbsent(e.kind, () => {}).add(e.target);
    }
    final likeItems = [
      for (final ref in (targets['like'] ?? const <String>{}).toList()..sort())
        {'ref': ref, 'at': likes[ref], 'removed': !likes.containsKey(ref)},
    ];
    final playlistItems = [
      for (final id
          in (targets['playlist'] ?? const <String>{}).toList()..sort())
        if (playlists.containsKey(id)) _playlistJson(id),
    ];
    final entryItems = <Map<String, Object?>>[];
    for (final id in (targets['entry'] ?? const <String>{}).toList()..sort()) {
      for (final list in entries.values) {
        for (final e in list) {
          if (e['id'] == id) entryItems.add(e);
        }
      }
    }
    final wanted = <String>{
      for (final l in likeItems)
        if (l['removed'] == false) l['ref']! as String,
      for (final e in entryItems)
        if (e['deleted'] == false) e['ref']! as String,
    };
    return _ok({
      'refs': [for (final id in wanted.toList()..sort()) refs[id]!],
      'likes': likeItems,
      'savedAlbums': const <Object?>[],
      'follows': const <Object?>[],
      'playlists': playlistItems,
      'entries': entryItems,
      'cursor': '$cursor',
      'more': false,
    });
  }

  FakeResponse _files(RecordedRequest r) {
    final since = int.parse(r.param('since') ?? '0');
    final limit = int.parse(r.param('limit') ?? '500');
    final latest = <String, int>{};
    for (final e in _fileLog.where((e) => e.seq > since)) {
      latest[e.ref] = e.seq;
    }
    final ordered = latest.entries.toList()
      ..sort((a, b) => a.value.compareTo(b.value));
    final page = ordered.take(limit).toList();
    final cursor = page.isEmpty ? since : page.last.value;
    return _ok({
      'refs': [for (final e in page) refs[e.key]!],
      'cursor': '$cursor',
      'more': ordered.length > page.length,
    });
  }

  FakeResponse _plays(RecordedRequest r) {
    final body = (jsonDecode(r.body) as Map).cast<String, Object?>();
    if (!plays.any((p) => p['id'] == body['id'])) plays.add(body);
    return _ok({'stored': true});
  }

  Map<String, Object?> _playlistJson(String id) => {
        ...playlists[id]!,
        'entries': <Object?>[],
      };

  FakeResponse _playlistsRoot(RecordedRequest r) {
    if (r.method == 'GET') {
      return _ok({
        'items': [for (final id in playlists.keys) _playlistJson(id)]
      });
    }
    final body = (jsonDecode(r.body) as Map).cast<String, Object?>();
    final id = body['id'] as String;
    if (!playlists.containsKey(id)) {
      playlists[id] = {
        'id': id,
        'name': body['name'],
        'cover': null,
        'collaborative': false,
        'createdAt': clockMs,
        'updatedAt': clockMs,
        'deleted': false,
      };
      entries[id] = [];
      _touch('playlist', id);
    }
    return _ok({'changed': true, 'cursor': '$_seq'}, status: 201);
  }

  FakeResponse _playlistRoute(String id, RecordedRequest r) {
    final playlist = playlists[id];
    if (playlist == null) return _error(404, 'not_found');
    if (r.method == 'PATCH') {
      final body = (jsonDecode(r.body) as Map).cast<String, Object?>();
      if (body.containsKey('name')) playlist['name'] = body['name'];
      _touch('playlist', id);
    } else if (r.method == 'DELETE') {
      playlist['deleted'] = true;
      _touch('playlist', id);
    }
    return _ok({'changed': true, 'cursor': '$_seq'});
  }

  FakeResponse _entriesRoute(String playlistId, RecordedRequest r) {
    final list = entries[playlistId];
    if (list == null || playlists[playlistId]!['deleted'] == true) {
      return _error(404, 'not_found');
    }
    final body = (jsonDecode(r.body) as Map).cast<String, Object?>();
    if (r.method == 'POST') {
      final songs = (body['songs'] as List).cast<Map<String, Object?>>();
      final live = list.where((e) => e['deleted'] == false).toList();
      var low = live.isEmpty ? 0.0 : live.last['position']! as double;
      for (final s in songs) {
        if (list.any((e) => e['id'] == s['id'])) continue;
        low += 1;
        final entry = {
          'id': s['id'],
          'playlist': playlistId,
          'ref': s['ref'],
          'position': low,
          'addedAt': clockMs++,
          'deleted': false,
        };
        list.add(entry);
        _touch('entry', '${s['id']}');
      }
      _touch('playlist', playlistId);
      return _ok({'added': const <Object?>[], 'cursor': '$_seq'}, status: 201);
    }
    final ids = (body['entryIds'] as List).cast<String>();
    for (final e in list) {
      if (ids.contains(e['id']) && e['deleted'] == false) {
        e['deleted'] = true;
        _touch('entry', e['id']! as String);
      }
    }
    _touch('playlist', playlistId);
    return _ok({'removed': ids, 'cursor': '$_seq'});
  }

  FakeResponse _orderRoute(String playlistId, RecordedRequest r) {
    final list = entries[playlistId];
    if (list == null) return _error(404, 'not_found');
    final ids =
        ((jsonDecode(r.body) as Map)['entryIds'] as List).cast<String>();
    var position = 0.0;
    for (final id in ids) {
      final entry =
          list.firstWhere((e) => e['id'] == id, orElse: () => const {});
      if (entry.isEmpty) continue;
      entry['position'] = ++position;
      _touch('entry', id);
    }
    _touch('playlist', playlistId);
    return _ok({'cursor': '$_seq'});
  }

  // -------------------------------------------------------------- answers

  FakeResponse _ok(Object body, {int status = 200}) {
    final map = {...(body as Map<String, Object?>), 'serverTime': clockMs};
    return FakeResponse.json(map, status: status);
  }

  FakeResponse _error(int status, String code) => FakeResponse.json({
        'error': {
          'code': code,
          'message': 'A sentence.',
          'retryable': false,
          'retryAfterMs': null,
          'details': <String, Object?>{}
        },
      }, status: status);
}
