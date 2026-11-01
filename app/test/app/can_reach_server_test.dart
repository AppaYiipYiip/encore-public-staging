import 'package:encore/app/playback_providers.dart';
import 'package:encore/app/providers.dart' show NetworkKind;
import 'package:encore/data/sync/endpoint_resolver.dart';
import 'package:flutter_test/flutter_test.dart';

/// What the player takes "I can get a song that is not downloaded" to mean. Field test 2026-10-31: with the 4G radio on and no data the
/// player believed it was online, waited for the server on the first song that was not downloaded and never reached the downloaded ones
/// behind it ("if one song is missing I can't play any").
void main() {
  final home =
      ServerEndpoint(label: 'Home', url: Uri.parse('http://192.168.1.2:4533'));

  EndpointResolver resolver({required bool answers}) => EndpointResolver(
        candidates: [home],
        probe: (_) async => answers,
        delay: (_) async {},
      );

  test('no network at all: no', () {
    expect(
        canReachServerNow(NetworkKind.none, resolver(answers: true)), isFalse);
  });

  test('a network and nobody has looked yet: yes (the first second of the app)',
      () {
    expect(canReachServerNow(NetworkKind.mobile, resolver(answers: false)),
        isTrue);
  });

  test('a network and the server does not answer: no', () async {
    final r = resolver(answers: false);
    await r.resolve();

    expect(canReachServerNow(NetworkKind.mobile, r), isFalse);
  });

  test('a network and the server answers: yes', () async {
    final r = resolver(answers: true);
    await r.resolve();

    expect(canReachServerNow(NetworkKind.wifi, r), isTrue);
  });

  test('no session yet: whatever the network says', () {
    expect(canReachServerNow(NetworkKind.wifi, null), isTrue);
    expect(canReachServerNow(null, null), isTrue);
  });
}
