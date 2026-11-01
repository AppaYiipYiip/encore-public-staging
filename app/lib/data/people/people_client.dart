import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

import '../../core/logger.dart';
import '../../core/network_policy.dart';
import '../../core/result.dart';

/// What a person is on a server (ADR-092): an owner runs it, someone who can
/// invite brings friends in as guests, a guest listens.
enum PersonRole {
  owner('owner', 'Owner'),
  inviter('inviter', 'Can invite'),
  guest('guest', 'Guest');

  const PersonRole(this.wire, this.label);

  /// What the service calls it.
  final String wire;

  /// What the app calls it: the one place these words are written.
  final String label;

  static PersonRole? tryParse(Object? wire) {
    for (final role in values) {
      if (role.wire == wire) return role;
    }
    return null;
  }
}

/// Who the people service thinks I am (`GET /people/api/me`).
@immutable
class PeopleMe {
  const PeopleMe({
    required this.user,
    required this.isAdmin,
    required this.sharing,
    bool? canInvite,
    PersonRole? role,
    bool? canManage,
  })  : _canInvite = canInvite,
        _role = role,
        _canManage = canManage;

  final String user;

  /// The music server says this person administers it.
  final bool isAdmin;

  final bool? _canInvite;
  final PersonRole? _role;
  final bool? _canManage;

  /// What this person is on the server. An older service sends none: then
  /// somebody who may invite is an owner and everybody else a guest.
  PersonRole get role =>
      _role ?? ((_canInvite ?? isAdmin) ? PersonRole.owner : PersonRole.guest);

  /// This person may make invitations (an owner, or somebody who can invite).
  bool get canInvite =>
      _canInvite ?? (_role != null ? _role != PersonRole.guest : isAdmin);

  /// This person may see everybody and change who is what (an owner).
  bool get canManage => _canManage ?? role == PersonRole.owner;

  PeopleMe copyWith({bool? sharing}) => PeopleMe(
        user: user,
        isAdmin: isAdmin,
        sharing: sharing ?? this.sharing,
        canInvite: _canInvite,
        role: _role,
        canManage: _canManage,
      );

  /// Whether this person chose to let friends see what they are listening to.
  final bool sharing;
}

/// What a friend who shares is listening to right now.
@immutable
class FriendActivity {
  const FriendActivity({
    required this.user,
    required this.title,
    required this.artist,
    required this.album,
    required this.coverUrl,
    required this.isPlaying,
    required this.startedAt,
  });

  final String user;
  final String title;
  final String artist;
  final String album;

  /// A public picture address, or `null` (never one that carries a login).
  final String? coverUrl;
  final bool isPlaying;
  final DateTime startedAt;

  static FriendActivity? tryParse(Object? json) {
    if (json is! Map) return null;
    final user = json['user'];
    final title = json['title'];
    if (user is! String || user.isEmpty || title is! String || title.isEmpty) {
      return null;
    }
    final cover = json['coverUrl'];
    final since = json['since'];
    return FriendActivity(
      user: user,
      title: title,
      artist: json['artist'] is String ? json['artist'] as String : '',
      album: json['album'] is String ? json['album'] as String : '',
      coverUrl: cover is String && cover.isNotEmpty ? cover : null,
      isPlaying: json['state'] == 'playing',
      startedAt: _time(since) ?? DateTime.fromMillisecondsSinceEpoch(0),
    );
  }
}

/// The only thing about my listening that ever leaves the phone: no song id,
/// no path, nothing that points into a library (docs/35, section 3).
@immutable
class NowPlayingReport {
  const NowPlayingReport({
    required this.title,
    required this.artist,
    required this.playing,
    this.album = '',
    this.coverUrl,
  });

  final String title;
  final String artist;
  final String album;
  final String? coverUrl;
  final bool playing;
}

/// A freshly made invitation: [url] is what the owner sends to a friend.
@immutable
class CreatedInvite {
  const CreatedInvite({
    required this.id,
    required this.url,
    required this.expiresAt,
    this.role = PersonRole.guest,
  });

  final String id;
  final String url;
  final DateTime expiresAt;

  /// What the person who opens it becomes.
  final PersonRole role;
}

/// One invitation in the owner's list. The secret code is never shown again;
/// the server keeps only a hash of it.
@immutable
class InviteRow {
  const InviteRow({
    required this.id,
    required this.state,
    required this.createdAt,
    required this.expiresAt,
    this.inviter = '',
    this.role = PersonRole.guest,
    this.redeemedBy,
    this.redeemedAt,
  });

  final String id;

  /// Who made it.
  final String inviter;

  /// What the invited person becomes.
  final PersonRole role;

  /// `open`, `used`, `expired` or `revoked`.
  final String state;
  final DateTime createdAt;
  final DateTime expiresAt;
  final String? redeemedBy;
  final DateTime? redeemedAt;

  bool get isOpen => state == 'open';
}

/// One person on the server, as an owner sees them (`GET /people/api/people`).
@immutable
class PersonOnServer {
  const PersonOnServer({
    required this.user,
    required this.role,
    required this.isFounding,
    this.invitedBy,
    this.joinedAt,
  });

  final String user;
  final PersonRole role;

  /// An administrator of the music server or a name in the server's settings:
  /// always an owner, cannot be changed or removed from the app.
  final bool isFounding;
  final String? invitedBy;
  final DateTime? joinedAt;

  static PersonOnServer? tryParse(Object? json) {
    if (json is! Map) return null;
    final user = json['user'];
    final role = PersonRole.tryParse(json['role']);
    if (user is! String || user.isEmpty || role == null) return null;
    final by = json['invitedBy'];
    return PersonOnServer(
      user: user,
      role: role,
      isFounding: json['fixed'] == true,
      invitedBy: by is String && by.isNotEmpty ? by : null,
      joinedAt: _time(json['joinedAt']),
    );
  }
}

/// What [ActivityPublisher] needs from the service (so it is tested without
/// one).
abstract interface class ActivitySink {
  Future<Result<void>> report(NowPlayingReport report);
  Future<Result<void>> clear();
}

/// Everything the app asks of the people service; [PeopleClient] is the real
/// one and tests use a fake.
abstract interface class PeopleApi implements ActivitySink {
  Future<Result<PeopleMe>> me();
  Future<Result<List<FriendActivity>>> friends();
  Future<Result<void>> setSharing(bool on);

  /// Whether this server can show what a person listens to to their friends. Where it cannot (an Encore server today: friend activity is a
  /// later phase), "Share what I'm listening to" is not offered: a switch that does nothing, and goes back at the next start, would lie
  /// (AUDIT F57, D-37).
  bool get sharesListening;
  Future<Result<CreatedInvite>> createInvite({PersonRole role});
  Future<Result<List<InviteRow>>> invites();
  Future<Result<void>> revokeInvite(String id);
  Future<Result<List<PersonOnServer>>> people();
  Future<Result<void>> setRole(String user, PersonRole role);
  Future<Result<void>> removePerson(String user);
}

DateTime? _time(Object? seconds) => seconds is num
    ? DateTime.fromMillisecondsSinceEpoch((seconds * 1000).round())
    : null;

/// Client of the `encore-people` companion service (docs/35): invitations and
/// friend activity. Stateless: every request carries the music server's own
/// Subsonic token (`u`, `t`, `s`), so there is no second login and no password
/// stored on the service.
///
/// An [AuthFailure] here means the *people service* did not accept the login.
/// The service is optional, so callers must not treat it as the end of the
/// music session.
class PeopleClient implements PeopleApi {
  @override
  bool get sharesListening => true;

  PeopleClient({
    required Uri baseUrl,
    required Map<String, String> Function() auth,
    Dio? dio,
  })  : _base = baseUrl,
        _auth = auth,
        _dio = dio ??
            Dio(BaseOptions(
              connectTimeout: const Duration(seconds: 5),
              receiveTimeout: const Duration(seconds: 10),
            ));

  final Uri _base;
  final Map<String, String> Function() _auth;
  final Dio _dio;

  static String _basePath(Uri base) => base.path.replaceAll(RegExp(r'/+$'), '');

  /// Asks whether [base] is an `encore-people` service. No login is sent: the
  /// token goes only to an address that has just proved what it is.
  static Future<bool> probe(Uri base, {Dio? dio}) async {
    final http = dio ??
        Dio(BaseOptions(
          connectTimeout: const Duration(milliseconds: 1500),
          receiveTimeout: const Duration(milliseconds: 2500),
        ));
    try {
      final response = await http.getUri<String>(
        base.replace(
          path: '${_basePath(base)}/people/api/info',
          query: '',
          fragment: '',
        ),
        options: Options(
          responseType: ResponseType.plain,
          validateStatus: (_) => true,
        ),
      );
      if (response.statusCode != 200) return false;
      final data = jsonDecode(response.data ?? '');
      return data is Map && data['service'] == 'encore-people';
    } on DioException catch (error) {
      Log.debug('people', 'no people service there: ${error.type.name}');
      return false;
    } on FormatException {
      return false; // something answered, and it is not this service
    }
  }

  // -------------------------------------------------------------- who am I

  @override
  Future<Result<PeopleMe>> me() => guard(() async {
        final data = _map(await _send('GET', '/me'));
        final user = data['user'];
        if (user is! String) throw _unreadable();
        return PeopleMe(
          user: user,
          isAdmin: data['admin'] == true,
          canInvite:
              data['canInvite'] is bool ? data['canInvite'] as bool : null,
          role: PersonRole.tryParse(data['role']),
          canManage:
              data['canManage'] is bool ? data['canManage'] as bool : null,
          sharing: data['sharing'] == true,
        );
      });

  // ------------------------------------------------------- friend activity

  @override
  Future<Result<List<FriendActivity>>> friends() => guard(() async {
        final data = _map(await _send('GET', '/activity'));
        final list = data['friends'];
        if (list is! List) throw _unreadable();
        return [
          for (final entry in list)
            if (FriendActivity.tryParse(entry) case final friend?) friend,
        ];
      });

  /// Tells the service what is playing. It ignores the report unless this
  /// person switched sharing on, so calling it is always safe.
  @override
  Future<Result<void>> report(NowPlayingReport report) => guard<void>(() async {
        final cover = _publicCover(report.coverUrl);
        await _send('PUT', '/activity', body: {
          'title': report.title,
          'artist': report.artist,
          'album': report.album,
          if (cover != null) 'coverUrl': cover,
          'state': report.playing ? 'playing' : 'paused',
        });
      });

  /// Forgets what this person was listening to.
  @override
  Future<Result<void>> clear() =>
      guard<void>(() async => _send('DELETE', '/activity'));

  @override
  Future<Result<void>> setSharing(bool on) => guard<void>(
      () async => _send('PUT', '/activity/sharing', body: {'on': on}));

  // ------------------------------------------------- invitations (admin)

  @override
  Future<Result<CreatedInvite>> createInvite(
          {PersonRole role = PersonRole.guest}) =>
      guard(() async {
        final data =
            _map(await _send('POST', '/invites', body: {'role': role.wire}));
        final id = data['id'];
        final url = data['url'];
        final expires = _time(data['expiresAt']);
        if (id == null || url is! String || expires == null) {
          throw _unreadable();
        }
        return CreatedInvite(
          id: '$id',
          url: url,
          expiresAt: expires,
          role: PersonRole.tryParse(data['role']) ?? PersonRole.guest,
        );
      });

  @override
  Future<Result<List<InviteRow>>> invites() => guard(() async {
        final data = _map(await _send('GET', '/invites'));
        final list = data['invites'];
        if (list is! List) throw _unreadable();
        final rows = <InviteRow>[];
        for (final e in list) {
          if (e is! Map) continue;
          final id = e['id'];
          final state = e['state'];
          final created = _time(e['createdAt']);
          final expires = _time(e['expiresAt']);
          if (id == null ||
              state is! String ||
              created == null ||
              expires == null) {
            continue;
          }
          rows.add(InviteRow(
            id: '$id',
            state: state,
            createdAt: created,
            expiresAt: expires,
            inviter: e['inviter'] is String ? e['inviter'] as String : '',
            role: PersonRole.tryParse(e['role']) ?? PersonRole.guest,
            redeemedBy:
                e['redeemedBy'] is String ? e['redeemedBy'] as String : null,
            redeemedAt: _time(e['redeemedAt']),
          ));
        }
        return rows;
      });

  @override
  Future<Result<void>> revokeInvite(String id) =>
      guard<void>(() async => _send('DELETE', '/invites/$id'));

  // ------------------------------------------------------ people (owners)

  /// A name is one path segment, whatever it holds.
  static String _segment(String name) => Uri.encodeComponent(name);

  @override
  Future<Result<List<PersonOnServer>>> people() => guard(() async {
        final data = _map(await _send('GET', '/people'));
        final list = data['people'];
        if (list is! List) throw _unreadable();
        return [
          for (final entry in list)
            if (PersonOnServer.tryParse(entry) case final person?) person,
        ];
      });

  @override
  Future<Result<void>> setRole(String user, PersonRole role) =>
      guard<void>(() async =>
          _send('PUT', '/people/${_segment(user)}', body: {'role': role.wire}));

  @override
  Future<Result<void>> removePerson(String user) =>
      guard<void>(() async => _send('DELETE', '/people/${_segment(user)}'));

  // ------------------------------------------------------------- plumbing

  /// A cover address is shared with other people, so it must be one anybody
  /// could open: no login in it, ever (docs/35, section 3).
  static String? _publicCover(String? raw) {
    if (raw == null || raw.isEmpty) return null;
    final uri = Uri.tryParse(raw);
    if (uri == null ||
        (uri.scheme != 'http' && uri.scheme != 'https') ||
        uri.host.isEmpty ||
        uri.userInfo.isNotEmpty) {
      return null;
    }
    final keys = uri.queryParameters.keys.map((k) => k.toLowerCase()).toSet();
    const secrets = {
      'p',
      'password',
      'token',
      'access_token',
      'apikey',
      'api_key',
    };
    if (keys.any(secrets.contains)) return null;
    if (keys.contains('t') && keys.contains('s')) return null;
    return raw;
  }

  AppFailure _unreadable() => const ServerFailure(
      'The people service sent an answer the app cannot read');

  Uri _url(String path) => _base.replace(
        path: '${_basePath(_base)}/people/api$path',
        queryParameters: _auth(),
        fragment: null,
      );

  /// Sends one request and returns the body of a successful answer (empty for
  /// "no content"). Everything else becomes a typed failure.
  Future<String> _send(String method, String path, {Object? body}) async {
    final problem = cleartextProblem(_base);
    if (problem != null) {
      throw UnexpectedFailure('Your login was not sent. $problem');
    }
    final Response<String> response;
    try {
      response = await _dio.requestUri<String>(
        _url(path),
        data: body == null ? null : jsonEncode(body),
        options: Options(
          method: method,
          responseType: ResponseType.plain,
          contentType: body == null ? null : Headers.jsonContentType,
          validateStatus: (_) => true,
        ),
      );
    } on DioException catch (error) {
      throw NetworkFailure(
        'Cannot reach the people service at ${_base.host}'
        '${_base.hasPort ? ':${_base.port}' : ''}',
        cause: error,
      );
    }
    final status = response.statusCode ?? 500;
    final text = response.data ?? '';
    if (status >= 200 && status < 300) return text;
    final said = _sentence(text);
    if (status == 401) throw AuthFailure(said ?? 'Sign in again.');
    throw ServerFailure(
      said ?? 'The people service answered $status',
      statusCode: status,
    );
  }

  /// The service's own plain-words explanation, when it sent one.
  static String? _sentence(String text) {
    try {
      final data = jsonDecode(text);
      final error = data is Map ? data['error'] : null;
      return error is String && error.isNotEmpty ? error : null;
    } on FormatException {
      return null;
    }
  }

  Map<String, dynamic> _map(String text) {
    try {
      final data = jsonDecode(text);
      if (data is Map<String, dynamic>) return data;
    } on FormatException {
      // Falls through to the failure below.
    }
    throw _unreadable();
  }
}
