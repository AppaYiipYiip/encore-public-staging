import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:encore/data/sync/server_identity.dart';

String b64u(List<int> bytes) => base64Url.encode(bytes).replaceAll('=', '');

/// A server's key for tests: really signs, with the private key made from the 32 bytes [seedStart], [seedStart] + 1, ...
///
/// `SigningIdentity(1)` is the key of the vector made by the real Python server (`server_identity_test.dart`).
class SigningIdentity {
  SigningIdentity(this.seedStart);

  final int seedStart;

  Future<({String id, String key, SimpleKeyPair pair})> identity() async {
    final pair = await Ed25519()
        .newKeyPairFromSeed(List<int>.generate(32, (i) => seedStart + i));
    final key = (await pair.extractPublicKey()).bytes;
    return (id: serverIdForKey(key), key: b64u(key), pair: pair);
  }

  Future<String> id() async => (await identity()).id;

  /// What `GET /info?challenge=<nonce>` answers. [claimId]: an impostor that says it is somebody else's id while signing with its own key.
  Future<Map<String, Object?>> answer(String nonce, {String? claimId}) async {
    final who = await identity();
    final id = claimId ?? who.id;
    final signature = await Ed25519().sign(
      utf8.encode('encore.info.v1\n$id\n$nonce'),
      keyPair: who.pair,
    );
    return {
      'serverId': id,
      'publicKey': who.key,
      'signature': b64u(signature.bytes),
      'apiVersion': '1.0',
      'name': 'Test server',
    };
  }
}
