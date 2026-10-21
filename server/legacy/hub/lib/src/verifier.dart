import 'dart:async';
import 'dart:convert';
import 'dart:io';

/// Says who a request is from, by the music server's own login (the Subsonic
/// token `u`, `t`, `s` every Encore request already carries): the hub has no
/// accounts or passwords of its own.
abstract interface class Verifier {
  /// The name the music server knows the sender by, or `null` when the login
  /// is missing or not accepted.
  Future<String?> verify(Map<String, String> query);
}

/// Asks Navidrome (`ping`) whether the token is good, and remembers a good
/// answer for a few minutes so a phone that sends many requests does not make
/// the music server answer each time.
class NavidromeVerifier implements Verifier {
  NavidromeVerifier(
    this.base, {
    HttpClient? http,
    this.ttl = const Duration(minutes: 5),
    int Function()? nowMs,
  })  : _http = http ?? HttpClient(),
        _now = nowMs ?? (() => DateTime.now().millisecondsSinceEpoch) {
    _http.connectionTimeout = const Duration(seconds: 5);
  }

  /// The music server, as the hub reaches it (`http://navidrome:4533`).
  final Uri base;
  final Duration ttl;
  final HttpClient _http;
  final int Function() _now;
  final Map<String, ({String user, int until})> _good = {};

  @override
  Future<String?> verify(Map<String, String> query) async {
    final user = query['u'];
    final token = query['t'];
    final salt = query['s'];
    if (user == null || token == null || salt == null) return null;
    if (user.isEmpty ||
        user.length > 100 ||
        token.length > 100 ||
        salt.length > 100) {
      return null;
    }
    final key = '$user|$token|$salt';
    final remembered = _good[key];
    final now = _now();
    if (remembered != null && remembered.until > now) return remembered.user;
    _good.removeWhere((_, v) => v.until <= now);

    final url = base.replace(
      path: '${base.path.replaceAll(RegExp(r'/+$'), '')}/rest/ping.view',
      queryParameters: {
        'u': user,
        't': token,
        's': salt,
        'v': '1.16.1',
        'c': 'encore-hub',
        'f': 'json',
      },
    );
    try {
      final request = await _http.getUrl(url);
      final response =
          await request.close().timeout(const Duration(seconds: 6));
      final text = await utf8.decodeStream(response);
      final body = jsonDecode(text);
      final status = body is Map && body['subsonic-response'] is Map
          ? (body['subsonic-response'] as Map)['status']
          : null;
      if (response.statusCode != 200 || status != 'ok') return null;
    } on SocketException {
      return null;
    } on TimeoutException {
      return null;
    } on HttpException {
      return null;
    } on FormatException {
      return null;
    }
    _good[key] = (user: user, until: now + ttl.inMilliseconds);
    return user;
  }
}
