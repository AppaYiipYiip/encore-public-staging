import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:meta/meta.dart';

import '../../core/network_policy.dart';

/// Finding the download service without asking a person to know its address
/// (ADR-052).
///
/// The service is the part of the server that finds and downloads music. It
/// is often *not* on the machine that runs the music server, so the first
/// guesses are cheap (same host as the music server, port 8700) and a wider
/// search on the local network is offered only when a person asks for it.

/// What answered when an address was asked "are you the download service?".
enum ProbeVerdict {
  /// It answers the way the request portal does: JSON with `error` (no
  /// session) or `user` (signed in) on `/api/me`.
  service,

  /// Something answers, but it is not a download service.
  other,

  /// Nothing answers: refused, no route, or no reply in time.
  silent,
}

@immutable
class ProbeResult {
  const ProbeResult(this.verdict, {this.statusCode, this.reason});

  final ProbeVerdict verdict;
  final int? statusCode;

  /// `refused` | `timeout` | `unreachable` for [ProbeVerdict.silent];
  /// `page` (an HTML page) | `status` | `json` for [ProbeVerdict.other].
  final String? reason;

  bool get isService => verdict == ProbeVerdict.service;

  @override
  String toString() => 'ProbeResult($verdict, $statusCode, $reason)';
}

/// One side-effect-free question to one address: `GET /api/me` with no
/// cookie.
class PortalProbe {
  PortalProbe({Dio? dio, Duration timeout = const Duration(milliseconds: 1500)})
      : _dio = dio ??
            Dio(BaseOptions(
              connectTimeout: timeout,
              receiveTimeout: timeout * 2,
              sendTimeout: timeout,
              validateStatus: (_) => true,
              responseType: ResponseType.plain,
            ));

  final Dio _dio;

  Future<ProbeResult> probe(Uri base) async {
    final path = '${base.path.replaceAll(RegExp(r'/+$'), '')}/api/me';
    final url = base.replace(path: path, query: '', fragment: '');
    try {
      final response = await _dio.getUri<Object?>(
        Uri(
          scheme: url.scheme,
          host: url.host,
          port: url.hasPort ? url.port : null,
          path: url.path,
        ),
        options: Options(
          responseType: ResponseType.plain,
          validateStatus: (_) => true,
        ),
      );
      return classify(response.statusCode, response.data);
    } on DioException catch (error) {
      return ProbeResult(ProbeVerdict.silent, reason: _silentReason(error));
    } on Object {
      return const ProbeResult(ProbeVerdict.silent, reason: 'unreachable');
    }
  }

  /// Public for tests: what a status code and a body (decoded JSON or text)
  /// say about the sender.
  @visibleForTesting
  static ProbeResult classify(int? status, Object? body) {
    final text = body is String ? body : '';
    Object? json = body is Map ? body : null;
    if (json == null && text.isNotEmpty) {
      try {
        json = jsonDecode(text);
      } on FormatException {
        json = null;
      }
    }
    if (json is Map &&
        (json.containsKey('error') || json.containsKey('user')) &&
        (status == 200 || status == 401 || status == 403)) {
      return ProbeResult(ProbeVerdict.service, statusCode: status);
    }
    final looksLikePage = text.trimLeft().toLowerCase().startsWith('<');
    return ProbeResult(
      ProbeVerdict.other,
      statusCode: status,
      reason: looksLikePage ? 'page' : (json == null ? 'status' : 'json'),
    );
  }

  static String _silentReason(DioException error) {
    final type = error.type.name.toLowerCase();
    if (type.contains('timeout')) return 'timeout';
    final cause = error.error;
    if (cause is SocketException) {
      final text =
          '${cause.message} ${cause.osError?.message ?? ''}'.toLowerCase();
      final code = cause.osError?.errorCode;
      if (text.contains('refused') || code == 111 || code == 10061) {
        return 'refused';
      }
    }
    return 'unreachable';
  }
}

/// `true` when a TCP connection to [host]:[port] opens within [timeout].
typedef TcpOpen = Future<bool> Function(
    String host, int port, Duration timeout);

Future<bool> _socketOpen(String host, int port, Duration timeout) async {
  try {
    final socket = await Socket.connect(host, port, timeout: timeout);
    socket.destroy();
    return true;
  } on Object {
    return false;
  }
}

class PortalDiscovery {
  PortalDiscovery({
    required PortalProbe probe,
    TcpOpen? tcpOpen,
    this.concurrency = 32,
    this.connectTimeout = const Duration(milliseconds: 400),
  })  : _probe = probe,
        _tcpOpen = tcpOpen ?? _socketOpen;

  /// The download service's usual port.
  static const int defaultPort = 8700;

  final PortalProbe _probe;
  final TcpOpen _tcpOpen;
  final int concurrency;
  final Duration connectTimeout;

  /// Addresses worth asking first, without duplicates and in this order: the
  /// one saved earlier, then every host the music server is reachable on
  /// (home and away) on each of [ports].
  static List<Uri> nearbyAddresses(
    Iterable<Uri> serverEndpoints, {
    Uri? saved,
    List<int> ports = const [defaultPort],
  }) {
    final out = <Uri>[];
    final seen = <String>{};
    void add(Uri uri) {
      if (uri.host.isEmpty) return;
      final key = '${uri.scheme}://${uri.host}:${uri.port}';
      if (seen.add(key)) out.add(Uri.parse(key));
    }

    if (saved != null) add(saved);
    for (final endpoint in serverEndpoints) {
      for (final port in ports) {
        // Cleartext to a public address is refused everywhere (ADR-032).
        final scheme = isPrivateHost(endpoint.host) ? 'http' : 'https';
        add(Uri(scheme: scheme, host: endpoint.host, port: port));
      }
    }
    return out;
  }

  /// The [candidates] that are the download service, probed in parallel.
  Future<List<Uri>> findNearby(Iterable<Uri> candidates) async {
    final list = candidates.toList();
    final results = await Future.wait([
      for (final uri in list) _probe.probe(uri),
    ]);
    return [
      for (var i = 0; i < list.length; i++)
        if (results[i].isService) list[i],
    ];
  }

  /// The other 253 addresses of the /24 around [ipv4] (host numbers 1..254),
  /// or an empty list unless it is a private IPv4 address of the kind a home
  /// network uses (10/8, 172.16/12, 192.168/16): a public range is never
  /// scanned.
  static List<String> subnetHosts(String ipv4,
      {Set<String> except = const {}}) {
    final parts = ipv4.split('.');
    if (parts.length != 4) return const [];
    final n = [for (final p in parts) int.tryParse(p)];
    if (n.any((v) => v == null || v < 0 || v > 255)) return const [];
    final a = n[0]!;
    final b = n[1]!;
    final homeRange =
        a == 10 || (a == 172 && b >= 16 && b <= 31) || (a == 192 && b == 168);
    if (!homeRange) return const [];
    final prefix = '${n[0]}.${n[1]}.${n[2]}';
    return [
      for (var host = 1; host <= 254; host++)
        if (!except.contains('$prefix.$host') && '$prefix.$host' != ipv4)
          '$prefix.$host',
    ];
  }

  /// Looks for the service on the local network around [around] (the music
  /// server's address): a quick TCP check of [port] on every address of the
  /// /24, then the probe on the ones that answered. Reports progress as
  /// `(done, total)`.
  Future<List<Uri>> searchNetwork(
    Uri around, {
    int port = defaultPort,
    Set<String> alreadyAsked = const {},
    void Function(int done, int total)? onProgress,
    bool Function()? isCancelled,
  }) async {
    final hosts = subnetHosts(around.host, except: alreadyAsked);
    if (hosts.isEmpty) return const [];
    final open = <String>[];
    var done = 0;
    var next = 0;

    Future<void> worker() async {
      while (true) {
        if (isCancelled?.call() ?? false) return;
        final index = next++;
        if (index >= hosts.length) return;
        final host = hosts[index];
        if (await _tcpOpen(host, port, connectTimeout)) open.add(host);
        done++;
        onProgress?.call(done, hosts.length);
      }
    }

    await Future.wait([
      for (var i = 0; i < concurrency.clamp(1, hosts.length); i++) worker(),
    ]);
    if (open.isEmpty || (isCancelled?.call() ?? false)) return const [];
    return findNearby([
      for (final host in open) Uri(scheme: 'http', host: host, port: port),
    ]);
  }
}

/// May the music server's own login be tried on the download service at
/// [service]? Only on the music server's own machine or on a private network;
/// a public host must be given its own password (ADR-052).
bool mayReuseServerLogin(Uri service, Iterable<Uri> serverEndpoints) {
  final host = service.host.toLowerCase();
  if (host.isEmpty) return false;
  if (serverEndpoints.any((e) => e.host.toLowerCase() == host)) return true;
  return isPrivateHost(host);
}
