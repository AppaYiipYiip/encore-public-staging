import 'package:encore/data/sync/server_identity.dart';

/// An address that answers "who are you?" the way a test wants, and remembers what it was asked.
///
/// By default it is an older server with no key (legacy): the widget tests that are not about keys behave as they did before keys.
class FakeIdentityProbe extends ServerIdentityProbe {
  FakeIdentityProbe({this.verdict = EndpointVerdict.legacy, this.serverId});

  EndpointVerdict verdict;
  String? serverId;
  final List<({Uri base, String? expectedId})> asked = [];

  @override
  Future<EndpointProof> check(Uri base, {String? expectedId}) async {
    asked.add((base: base, expectedId: expectedId));
    // As the real probe: a server whose key is known cannot be another key, nor get in by saying it has none.
    final other = verdict == EndpointVerdict.verified && serverId != expectedId;
    final noKey = verdict == EndpointVerdict.legacy;
    if (expectedId != null && (other || noKey)) {
      return const EndpointProof(EndpointVerdict.wrongKey);
    }
    return EndpointProof(verdict,
        serverId: verdict == EndpointVerdict.verified ? serverId : null);
  }
}
