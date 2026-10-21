/// Where is plain `http://` acceptable? (ADR-032)
///
/// A self-hosted server on the home network (or reached through a VPN such as
/// Tailscale) is the primary use case and has no TLS certificate; anything
/// that crosses the public internet must use `https://`.
///
/// Pure Dart (no `dart:io`) so it also works on web.
library;

/// `true` when [host] is loopback, link-local, RFC1918, CGNAT/Tailscale
/// (100.64.0.0/10), a single-label name, or a conventional private suffix.
bool isPrivateHost(String host) {
  final h = host.trim().toLowerCase();
  if (h.isEmpty) return false;

  // IPv6 literals (Uri.host strips the brackets).
  if (h.contains(':')) {
    if (h == '::1') return true;
    if (h.startsWith('fe8') ||
        h.startsWith('fe9') ||
        h.startsWith('fea') ||
        h.startsWith('feb')) {
      return true; // link-local fe80::/10
    }
    if (h.startsWith('fc') || h.startsWith('fd')) return true; // ULA fc00::/7
    return false;
  }

  final v4 = _parseIPv4(h);
  if (v4 != null) {
    final a = v4[0];
    final b = v4[1];
    if (a == 10) return true;
    if (a == 127) return true;
    if (a == 169 && b == 254) return true;
    if (a == 172 && b >= 16 && b <= 31) return true;
    if (a == 192 && b == 168) return true;
    if (a == 100 && b >= 64 && b <= 127) return true; // CGNAT / Tailscale
    return false;
  }

  if (h == 'localhost') return true;
  if (!h.contains('.')) return true; // single label: "nas", "navidrome"
  const suffixes = [
    '.local',
    '.lan',
    '.home',
    '.internal',
    '.home.arpa',
    '.localdomain',
    '.ts.net', // Tailscale MagicDNS (WireGuard-encrypted)
  ];
  return suffixes.any(h.endsWith);
}

List<int>? _parseIPv4(String h) {
  final parts = h.split('.');
  if (parts.length != 4) return null;
  final out = <int>[];
  for (final p in parts) {
    final n = int.tryParse(p);
    if (n == null || n < 0 || n > 255 || p.length > 3) return null;
    out.add(n);
  }
  return out;
}

/// Human-readable problem with using [url] as a server address, or `null`.
String? cleartextProblem(Uri url) {
  if (url.scheme == 'http' && !isPrivateHost(url.host)) {
    return 'Servers reached over the internet must use https:// '
        '(${url.host} is not a private address).';
  }
  return null;
}
