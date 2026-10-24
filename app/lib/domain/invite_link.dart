import 'package:meta/meta.dart';

import '../core/network_policy.dart';

/// The link a person is sent to join somebody's server (docs/39 F3):
/// `https://<server>/people/join/<code>`. The code works once and for a few
/// days; the page behind the link makes the account for a person without the
/// app, and the app makes it itself with the same two calls (`info`, `redeem`).
///
/// It carries no password and nothing that outlives the invitation.
@immutable
class InviteLink {
  const InviteLink({
    required this.server,
    required this.code,
    this.behindPeoplePrefix = true,
    this.encore = false,
    this.serverId,
  });

  /// The front door of the server: scheme, host, port and any path in front of
  /// `/people`.
  final Uri server;

  /// The one-time code.
  final String code;

  /// Behind the public address the people service sits under `/people`; on its
  /// own port at home (`http://192.168.1.10:8702/join/<code>`) it does not.
  /// The calls go to the same place the link came from.
  final bool behindPeoplePrefix;

  /// The link of an Encore server (`https://<server>/encore/join/<code>`): the invitation is checked and used on the server's own API, on
  /// the same address as everything else.
  final bool encore;

  /// The key of the server that made the invitation (`?id=` on the link, docs/11 ADR-R40): the phone checks that the address answers with
  /// this key before it sends the new person's name and password there. `null` for a link from before keys.
  final String? serverId;

  /// Who invited, what the server is called, until when: asked before the
  /// person chooses a name.
  Uri get infoUrl => encore
      ? _api('/invites/check').replace(queryParameters: {'code': code})
      : _join('$code/info');

  /// Makes the account.
  Uri get redeemUrl => encore ? _api('/auth/join') : _join('$code/redeem');

  /// What this server is called (an Encore server only).
  Uri get nameUrl => _api('/info');

  /// Whether this invitation is to a server one of [addresses] already is (same host and port): somebody who has an account there does
  /// not need it, but somebody who uses Encore on another server does, and may be signed in on this very phone.
  bool pointsAt(Iterable<Uri> addresses) {
    int port(Uri u) => u.hasPort ? u.port : (u.scheme == 'https' ? 443 : 80);
    return addresses.any((a) =>
        a.host.toLowerCase() == server.host.toLowerCase() &&
        port(a) == port(server));
  }

  Uri _api(String tail) {
    final front = server.path.replaceAll(RegExp(r'/+$'), '');
    return server.replace(path: '$front/encore/api/v1$tail');
  }

  Uri _join(String tail) {
    final front = server.path.replaceAll(RegExp(r'/+$'), '');
    final people = behindPeoplePrefix ? '/people' : '';
    return server.replace(path: '$front$people/join/$tail');
  }

  @override
  bool operator ==(Object other) =>
      other is InviteLink &&
      other.server == server &&
      other.code == code &&
      other.behindPeoplePrefix == behindPeoplePrefix &&
      other.encore == encore &&
      other.serverId == serverId;

  @override
  int get hashCode =>
      Object.hash(server, code, behindPeoplePrefix, encore, serverId);

  @override
  String toString() => 'InviteLink($server, $code)';
}

// `scheme://host[:port][/some/path]` then the join path, then the code.
const _front = r'(https?)://([^\s/?#]+)((?:/[^\s/?#]+)*?)';
const _code = r'([A-Za-z0-9_-]+)';
final RegExp _encoreForm =
    RegExp('$_front/encore/join/$_code${r'(?:\?id=([^\s&#]*))?'}');
final RegExp _serverKey = RegExp(r'^[a-z2-7]{26}$');
final RegExp _publicForm = RegExp('$_front/people/join/$_code');
final RegExp _homeForm = RegExp('$_front/join/$_code');

/// The invitation link inside [text] (a pasted message, a shared link, a link
/// that was tapped), or `null`. A link over plain http to an address on the
/// internet is refused: the page takes a password.
InviteLink? findInviteLink(String text) {
  for (final (pattern, prefixed, encore) in [
    (_encoreForm, false, true),
    (_publicForm, true, false),
    (_homeForm, false, false),
  ]) {
    final m = pattern.firstMatch(text);
    if (m == null) continue;
    final server = Uri.tryParse('${m.group(1)}://${m.group(2)}${m.group(3)}');
    if (server == null || server.host.isEmpty) continue;
    if (cleartextProblem(server) != null) return null;
    // A link that names a key badly is not a link without a key: it is refused, never relaxed into one.
    final named = encore ? m.group(5) : null;
    if (named != null && !_serverKey.hasMatch(named)) return null;
    return InviteLink(
        server: server,
        code: m.group(4)!,
        behindPeoplePrefix: prefixed,
        encore: encore,
        serverId: named);
  }
  return null;
}
