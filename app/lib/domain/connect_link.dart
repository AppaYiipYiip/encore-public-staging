import 'package:meta/meta.dart';

/// A setup link: what someone sends a person who is about to sign in, so
/// they type a password instead of an address (ADR-068).
///
/// `encore://connect?server=<address>&away=<address>&name=<name>&user=<name>`
///
/// It carries no secret: no password, no token. Whoever has the link learns
/// the server's address, which is not a secret either.
@immutable
class ConnectLink {
  const ConnectLink({required this.server, this.away, this.name, this.user});

  /// The address of the music server at home.
  final String server;

  /// A second address, for away from home (a Tailscale name, an HTTPS address).
  final String? away;

  /// What to call the server in the app.
  final String? name;

  /// The account the person should sign in with, when the sender chose it.
  final String? user;

  /// The link as text.
  String toLink() => Uri(
        scheme: 'encore',
        host: 'connect',
        queryParameters: {
          'server': server,
          if (away != null && away!.isNotEmpty) 'away': away!,
          if (name != null && name!.isNotEmpty) 'name': name!,
          if (user != null && user!.isNotEmpty) 'user': user!,
        },
      ).toString();

  /// The message a person sends to someone they are inviting.
  String toInvite({String appName = 'Encore'}) =>
      'Come and listen to my music on $appName.\n'
      '1. Install $appName.\n'
      '2. Copy the line below, open $appName and tap "Got a setup link?".\n'
      '3. Sign in with the username and password I gave you.\n\n'
      '${toLink()}';

  @override
  bool operator ==(Object other) =>
      other is ConnectLink &&
      other.server == server &&
      other.away == away &&
      other.name == name &&
      other.user == user;

  @override
  int get hashCode => Object.hash(server, away, name, user);
}

final RegExp _link = RegExp(r'encore://connect\?[^\s]+', caseSensitive: false);

/// A bare address on its own: `192.168.1.10:4533`, `http://nas.local/music`.
final RegExp _bareAddress = RegExp(
  r'^(?:https?://)?[A-Za-z0-9._-]+(?::\d{1,5})?(?:/[^\s]*)?$',
);

/// The setup link inside [text] (a whole message may have been pasted), or a
/// lone address; `null` when there is neither.
ConnectLink? findConnectLink(String text) {
  final match = _link.firstMatch(text);
  if (match != null) {
    final Uri uri;
    try {
      uri = Uri.parse(match.group(0)!.replaceAll(RegExp(r'[.,;)\]]+$'), ''));
    } on FormatException {
      return null;
    }
    final server = uri.queryParameters['server']?.trim();
    if (server == null || server.isEmpty) return null;
    String? clean(String key) {
      final v = uri.queryParameters[key]?.trim();
      return v == null || v.isEmpty ? null : v;
    }

    return ConnectLink(
      server: server,
      away: clean('away'),
      name: clean('name'),
      user: clean('user'),
    );
  }
  final bare = text.trim();
  if (bare.isNotEmpty && bare.length < 200 && _bareAddress.hasMatch(bare)) {
    return ConnectLink(server: bare);
  }
  return null;
}
