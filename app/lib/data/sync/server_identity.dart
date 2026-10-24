import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

import 'package:crypto/crypto.dart' as crypto;
import 'package:cryptography/cryptography.dart';
import 'package:dio/dio.dart';

import '../../core/logger.dart';

/// Who answers at an address (docs/11 ADR-R40, docs/31 CN-9 to CN-11).
///
/// An Encore server is its **key**: its id is the hash of its public key, and it proves the key by signing a fresh challenge. The phone sends
/// no login and no token to an address until that address has proved it is the server the phone knows; a recycled address on somebody
/// else's network, or an advertisement that copied an id, cannot sign.
enum EndpointVerdict {
  /// The key hashes to the id and the signature over this phone's own challenge verifies (and the id is the one the phone has).
  verified,

  /// A server that has no key yet (an older Encore server, or a plain music server): it answered an unauthenticated question like one,
  /// and it is used as before. Never accepted for a server whose key the phone has pinned.
  legacy,

  /// It answered, but it is not the server the phone knows: another id, a signature that does not verify, or no key where one was pinned.
  wrongKey,

  /// No answer, or an answer that is no server at all.
  unreachable,
}

class EndpointProof {
  const EndpointProof(this.verdict, {this.serverId});

  final EndpointVerdict verdict;

  /// The id the server proved (only with [EndpointVerdict.verified]).
  final String? serverId;

  bool get usable =>
      verdict == EndpointVerdict.verified || verdict == EndpointVerdict.legacy;

  @override
  String toString() =>
      'EndpointProof($verdict${serverId == null ? '' : ', $serverId'})';
}

const _domain = 'encore.info.v1\n';
const _base32 = 'abcdefghijklmnopqrstuvwxyz234567';

/// 26 characters: the first 128 bits of the SHA-256 of [publicKey], as lower-case base32 without padding (the server's `server_id_for`).
String serverIdForKey(List<int> publicKey) {
  final digest = crypto.sha256.convert(publicKey).bytes.sublist(0, 16);
  final out = StringBuffer();
  var buffer = 0;
  var bits = 0;
  for (final byte in digest) {
    buffer = (buffer << 8) | byte;
    bits += 8;
    while (bits >= 5) {
      out.write(_base32[(buffer >> (bits - 5)) & 31]);
      bits -= 5;
    }
    buffer &= (1 << bits) - 1;
  }
  if (bits > 0) out.write(_base32[(buffer << (5 - bits)) & 31]);
  return out.toString();
}

List<int>? _fromBase64Url(String? text) {
  if (text == null || text.isEmpty) return null;
  try {
    return base64Url.decode(base64Url.normalize(text));
  } on FormatException {
    return null;
  }
}

/// What a phone does with an answer: the key must hash to [serverId] and the signature over **its own** nonce must verify. Anything
/// malformed is simply "no" (the server's `identity.verify`).
Future<bool> verifyServerAnswer({
  required String serverId,
  required String publicKey,
  required String nonce,
  required String signature,
}) async {
  final key = _fromBase64Url(publicKey);
  final sig = _fromBase64Url(signature);
  if (key == null || sig == null || key.length != 32 || sig.length != 64) {
    return false;
  }
  if (serverIdForKey(key) != serverId) return false;
  final message = utf8.encode('$_domain$serverId\n$nonce');
  return Ed25519().verify(
    message,
    signature: Signature(sig,
        publicKey: SimplePublicKey(key, type: KeyPairType.ed25519)),
  );
}

/// Asks an address who it is, with nothing a stranger could use: a public `GET /encore/api/v1/info?challenge=<fresh nonce>`.
class ServerIdentityProbe {
  ServerIdentityProbe({Dio Function()? dioFactory, Random? random})
      : _dioFactory = dioFactory ?? _plainDio,
        _random = random ?? Random.secure();

  final Dio Function() _dioFactory;
  final Random _random;

  static Dio _plainDio() => Dio(BaseOptions(
        connectTimeout: const Duration(seconds: 3),
        receiveTimeout: const Duration(seconds: 4),
        sendTimeout: const Duration(seconds: 4),
        followRedirects: false,
        // Every status is an answer to read: a 404 is "not an Encore server", not an exception.
        validateStatus: (_) => true,
      ));

  /// A client with the rules of this question, whatever [_dioFactory] made: every status is an answer to read (a 404 is "not an Encore
  /// server", not an exception) and a redirect is never followed to somewhere else.
  Dio _newDio() {
    final dio = _dioFactory();
    dio.options.validateStatus = (_) => true;
    dio.options.followRedirects = false;
    return dio;
  }

  String _nonce() => base64Url
      .encode(
          Uint8List.fromList(List.generate(24, (_) => _random.nextInt(256))))
      .replaceAll('=', '');

  /// [expectedId]: the id this phone has pinned for the server, if any.
  Future<EndpointProof> check(Uri base, {String? expectedId}) async {
    final nonce = _nonce();
    final dio = _newDio();
    final front = base.path.replaceAll(RegExp(r'/+$'), '');
    Response<dynamic> response;
    try {
      response = await dio.getUri<dynamic>(base.replace(
        path: '$front/encore/api/v1/info',
        queryParameters: {'challenge': nonce},
      ));
    } on DioException catch (error) {
      Log.debug('identity', '$base did not answer: ${error.type.name}');
      return const EndpointProof(EndpointVerdict.unreachable);
    } finally {
      dio.close();
    }
    final body = response.data;
    final map = body is Map ? body.cast<String, dynamic>() : null;
    final claimed = map?['serverId'];
    if (response.statusCode == 200 && claimed is String) {
      final ok = await verifyServerAnswer(
        serverId: claimed,
        publicKey: '${map?['publicKey'] ?? ''}',
        nonce: nonce,
        signature: '${map?['signature'] ?? ''}',
      );
      if (!ok || (expectedId != null && expectedId != claimed)) {
        Log.info('identity',
            '$base answered with a key that is not the one we know');
        return const EndpointProof(EndpointVerdict.wrongKey);
      }
      return EndpointProof(EndpointVerdict.verified, serverId: claimed);
    }
    // It answered, but with no key. A server whose key is pinned cannot "downgrade" to having none.
    if (expectedId != null) {
      return const EndpointProof(EndpointVerdict.wrongKey);
    }
    if (response.statusCode == 200 &&
        map != null &&
        map['apiVersion'] != null) {
      return const EndpointProof(EndpointVerdict
          .legacy); // an Encore server that is too old to have a key
    }
    return _legacyMusicServer(base);
  }

  /// A plain music server: an unauthenticated Subsonic `ping` is answered with a Subsonic envelope (an error that asks for a login),
  /// which says "a Subsonic server is here" without sending it anything.
  Future<EndpointProof> _legacyMusicServer(Uri base) async {
    final dio = _newDio();
    final front = base.path.replaceAll(RegExp(r'/+$'), '');
    try {
      final response = await dio.getUri<dynamic>(base.replace(
        path: '$front/rest/ping.view',
        queryParameters: {'v': '1.16.1', 'c': 'encore', 'f': 'json'},
      ));
      final data = response.data;
      final envelope = data is Map ? data['subsonic-response'] : null;
      if (envelope is Map && envelope['status'] is String) {
        return const EndpointProof(EndpointVerdict.legacy);
      }
    } on DioException catch (error) {
      Log.debug('identity', '$base is not a music server: ${error.type.name}');
    } finally {
      dio.close();
    }
    return const EndpointProof(EndpointVerdict.unreachable);
  }
}
