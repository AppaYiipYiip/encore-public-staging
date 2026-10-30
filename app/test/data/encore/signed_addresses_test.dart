import 'package:encore/core/result.dart';
import 'package:encore/data/encore/signed_addresses.dart';
import 'package:flutter_test/flutter_test.dart';

/// The Encore server signs the address of every song and one ticket for every picture (docs/tasks P2-20 slice 2): the phone holds no music-server
/// login, and must not ask the server again for what it already has.
void main() {
  var now = DateTime.utc(2026, 10, 25, 12);
  DateTime clock() => now;

  group('the address of a song', () {
    late List<String> asked;
    late Duration lives;
    late StreamAddresses addresses;

    setUp(() {
      now = DateTime.utc(2026, 10, 25, 12);
      asked = [];
      lives = const Duration(hours: 6);
      addresses = StreamAddresses(
        clock: clock,
        fetch: (ref) async {
          asked.add(ref);
          return Result.ok(SignedAddress(
              Uri.parse(
                  'http://home.test/encore/stream/$ref?sig=${asked.length}'),
              now.add(lives)));
        },
      );
    });

    test('is asked once, and the same song again costs no round trip',
        () async {
      final first = await addresses.forRef('sr_1');
      final second = await addresses.forRef('sr_1');

      expect(second, first);
      expect(asked, ['sr_1']);
    });

    test('two taps at once are one question', () async {
      final both = await Future.wait(
          [addresses.forRef('sr_1'), addresses.forRef('sr_1')]);

      expect(both[0], both[1]);
      expect(asked, ['sr_1']);
    });

    test('another song is another question', () async {
      await addresses.forRef('sr_1');
      await addresses.forRef('sr_2');

      expect(asked, ['sr_1', 'sr_2']);
    });

    test(
        'is asked again before it runs out, not after (a song must not stop '
        'half way)', () async {
      await addresses.forRef('sr_1');

      now = now.add(const Duration(hours: 5, minutes: 49));
      await addresses.forRef('sr_1');
      expect(asked, ['sr_1'], reason: '11 minutes left: still good');

      now = now.add(const Duration(minutes: 2));
      final renewed = await addresses.forRef('sr_1');
      expect(asked, ['sr_1', 'sr_1'], reason: '9 minutes left: ask again');
      expect(renewed.queryParameters['sig'], '2');
    });

    test('a failure is told to the caller and not remembered', () async {
      var fail = true;
      final flaky = StreamAddresses(
        clock: clock,
        fetch: (ref) async => fail
            ? const Result.err(NetworkFailure('No connection.'))
            : Result.ok(SignedAddress(
                Uri.parse('http://home.test/encore/stream/$ref'),
                now.add(const Duration(hours: 6)))),
      );

      await expectLater(flaky.forRef('sr_1'), throwsA(isA<NetworkFailure>()));
      fail = false;
      expect(await flaky.forRef('sr_1'), isA<Uri>());
    });

    test('forgets the oldest when it holds too many, and everything on clear',
        () async {
      final small = StreamAddresses(
        clock: clock,
        capacity: 2,
        fetch: (ref) async {
          asked.add(ref);
          return Result.ok(SignedAddress(
              Uri.parse('http://home.test/s/$ref'), now.add(lives)));
        },
      );
      await small.forRef('a');
      await small.forRef('b');
      await small.forRef('c');
      asked.clear();

      await small.forRef('c');
      await small.forRef('a');
      expect(asked, ['a'], reason: 'c is still known, a was forgotten');

      small.clear();
      asked.clear();
      await small.forRef('c');
      expect(asked, ['c']);
    });
  });

  group('the ticket for pictures', () {
    late int fetches;
    late Duration lives;
    late Uri base;
    late CoverPassHolder pass;

    setUp(() {
      now = DateTime.utc(2026, 10, 25, 12);
      fetches = 0;
      lives = const Duration(days: 7);
      base = Uri.parse('http://home.test:4540');
      pass = CoverPassHolder(
        clock: clock,
        baseUrl: () => base,
        fetch: () async {
          fetches++;
          return Result.ok(CoverPass(
              person: 'pn_marwa',
              expiresAt: now.add(lives),
              signature: 'sig$fetches'));
        },
      );
    });

    test('gives no address until it has the ticket, then every picture one',
        () async {
      expect(pass.urlFor('al-1', 300), isNull);

      await pass.ensure();
      final url = pass.urlFor('al-1', 300)!;

      expect(url.host, 'home.test');
      expect(url.port, 4540);
      expect(url.path, '/encore/cover/al-1');
      expect(url.queryParameters['size'], '300');
      expect(url.queryParameters['p'], 'pn_marwa');
      expect(url.queryParameters['sig'], 'sig1');
      expect(url.queryParameters['e'],
          '${now.add(lives).millisecondsSinceEpoch ~/ 1000}');
      expect(pass.urlFor('al-2', 64)!.path, '/encore/cover/al-2');
      expect(fetches, 1, reason: 'one ticket for all of them');
    });

    test('carries no login of the music server', () async {
      await pass.ensure();

      final url = pass.urlFor('al-1', 300)!.toString();

      for (final secret in ['u=', 't=', 's=salt', 'password']) {
        expect(url, isNot(contains(secret)));
      }
    });

    test('a picture id is written safely into the address', () async {
      await pass.ensure();

      expect(pass.urlFor('a b/../c', 64)!.path, '/encore/cover/a%20b%2F..%2Fc');
    });

    test('follows the server when its address changes (home, then away)',
        () async {
      await pass.ensure();
      base = Uri.parse('https://our-music.tail1234.ts.net');

      final url = pass.urlFor('al-1', 64)!;

      expect(url.host, 'our-music.tail1234.ts.net');
      expect(url.scheme, 'https');
    });

    test('is renewed a day before it ends, and not before', () async {
      await pass.ensure();

      now = now.add(const Duration(days: 5, hours: 23));
      await pass.ensure();
      expect(fetches, 1, reason: 'more than a day left');

      now = now.add(const Duration(hours: 2));
      await pass.ensure();
      expect(fetches, 2);
      expect(pass.urlFor('al-1', 64)!.queryParameters['sig'], 'sig2');
    });

    test('an old ticket is not used while a new one is on its way', () async {
      await pass.ensure();
      now = now.add(const Duration(days: 8));

      expect(pass.urlFor('al-1', 64), isNull);
    });

    test('two asks at once are one question', () async {
      await Future.wait([pass.ensure(), pass.ensure(), pass.ensure()]);

      expect(fetches, 1);
    });

    test('a refused ticket is asked for again by the next ensure', () async {
      await pass.ensure();
      pass.expire();

      expect(pass.urlFor('al-1', 64), isNull);
      await pass.ensure();
      expect(fetches, 2);
      expect(pass.urlFor('al-1', 64), isNotNull);
    });

    test('tells those who show pictures when a ticket arrives', () async {
      final seen = <int>[];
      final sub = pass.changes.listen(seen.add);

      await pass.ensure();
      await Future<void>.delayed(Duration.zero);
      pass.expire();
      await pass.ensure();
      await Future<void>.delayed(Duration.zero);

      expect(seen, [1, 2]);
      expect(pass.generation, 2);
      await sub.cancel();
    });

    test('a failed ask leaves the pictures as they were, and says nothing',
        () async {
      final failing = CoverPassHolder(
        clock: clock,
        baseUrl: () => base,
        fetch: () async => const Result.err(NetworkFailure('No connection.')),
      );

      await failing.ensure();

      expect(failing.urlFor('al-1', 64), isNull);
      expect(failing.generation, 0);
    });
  });
}
