import 'dart:async';

import 'package:encore/app/connection.dart';
import 'package:encore/app/providers.dart';
import 'package:encore/core/result.dart';
import 'package:encore/data/people/people_client.dart';
import 'package:encore/features/people/people_providers.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_people_api.dart';

/// Finding the people service, knowing what the person chose, and keeping the
/// friends' list fresh (docs/35). Every seam is replaced by a fake: no
/// network, no timers that matter.
void main() {
  group('finding the service', () {
    ProviderContainer container({
      List<Uri> candidates = const [],
      Set<String> answering = const {},
      Map<String, String> Function()? auth,
      List<String>? asked,
    }) {
      final c = ProviderContainer(overrides: [
        networkKindProvider
            .overrideWith((ref) => Stream.value(NetworkKind.wifi)),
        encorePeopleApiProvider.overrideWith((ref) async => null),
        peopleCandidatesProvider.overrideWith((ref) async => candidates),
        peopleAuthProvider.overrideWith((ref) async => auth),
        peopleProbeProvider.overrideWithValue((uri) async {
          asked?.add(uri.toString());
          return answering.contains(uri.toString());
        }),
      ]);
      addTearDown(c.dispose);
      return c;
    }

    Map<String, String> login() => {'u': 'sara', 't': 'tok', 's': 'salt'};

    test('is the first known address that answers', () async {
      final c = container(
        candidates: [
          Uri.parse('http://192.168.50.132:4533'),
          Uri.parse('https://music.example.ts.net'),
        ],
        answering: {'https://music.example.ts.net'},
        auth: login,
      );

      expect(await c.read(peopleServiceProvider.future),
          Uri.parse('https://music.example.ts.net'));
    });

    test('is nothing when no address answers', () async {
      final c = container(
        candidates: [Uri.parse('http://192.168.50.132:4533')],
        auth: login,
      );

      expect(await c.read(peopleServiceProvider.future), isNull);
      expect(await c.read(peopleApiProvider.future), isNull);
    });

    test('is not even looked for before the person is signed in', () async {
      final asked = <String>[];
      final c = container(
        candidates: [Uri.parse('https://music.example.ts.net')],
        answering: {'https://music.example.ts.net'},
        auth: null,
        asked: asked,
      );

      expect(await c.read(peopleServiceProvider.future), isNull);
      expect(asked, isEmpty, reason: 'no address is asked without a login');
    });

    test('becomes a client once found', () async {
      final c = container(
        candidates: [Uri.parse('https://music.example.ts.net')],
        answering: {'https://music.example.ts.net'},
        auth: login,
      );

      expect(await c.read(peopleApiProvider.future), isA<PeopleClient>());
    });
  });

  group('what I chose', () {
    ProviderContainer containerWith(FakePeopleApi? api) {
      final c = ProviderContainer(overrides: [
        peopleApiProvider.overrideWith((ref) async => api),
      ]);
      addTearDown(c.dispose);
      return c;
    }

    test('is read from the service', () async {
      final c = containerWith(FakePeopleApi(
          me_: const PeopleMe(user: 'owner', isAdmin: true, sharing: true)));

      final me = (await c.read(peopleProvider.future))!;

      expect(me.user, 'owner');
      expect(me.isAdmin, isTrue);
      expect(me.sharing, isTrue);
    });

    test('is nothing without a service', () async {
      final c = containerWith(null);

      expect(await c.read(peopleProvider.future), isNull);
    });

    test(
        'an ask that went out before the server could be reached is made again when it can (QA round 1, R1-1: an owner without Invite and People)',
        () async {
      final api = FakePeopleApi(
          me_: const PeopleMe(
              user: 'owner', isAdmin: true, sharing: false, canInvite: true))
        ..meAnswers.add(const Result.err(NetworkFailure('Cannot reach')));
      final reachable = StreamController<ServerFinding>();
      addTearDown(reachable.close);
      final c = ProviderContainer(overrides: [
        peopleApiProvider.overrideWith((ref) async => api),
        serverFindingProvider.overrideWith((ref) => reachable.stream),
      ]);
      addTearDown(c.dispose);
      // The screens that show the tiles are listening, and a provider nobody listens to is paused.
      addTearDown(c.listen(peopleProvider, (_, __) {}).close);

      expect(await c.read(peopleProvider.future), isNull,
          reason: 'the first ask found nobody to answer');
      reachable.add(ServerFinding.answering);
      await pumpEventQueue();

      expect((await c.read(peopleProvider.future))?.canInvite, isTrue,
          reason:
              'the owner gets Invite and People as soon as the server answers');
    });

    test('a person already known is not forgotten when the line blinks',
        () async {
      final api = FakePeopleApi(
          me_: const PeopleMe(user: 'owner', isAdmin: true, sharing: false));
      final reachable = StreamController<ServerFinding>();
      addTearDown(reachable.close);
      final c = ProviderContainer(overrides: [
        peopleApiProvider.overrideWith((ref) async => api),
        serverFindingProvider.overrideWith((ref) => reachable.stream),
      ]);
      addTearDown(c.dispose);
      addTearDown(c.listen(peopleProvider, (_, __) {}).close);
      await c.read(peopleProvider.future);
      api.meAnswers.add(const Result.err(NetworkFailure('Cannot reach')));

      reachable
        ..add(ServerFinding.silent)
        ..add(ServerFinding.answering);
      await pumpEventQueue();

      expect(c.read(peopleProvider).value?.user, 'owner');
    });

    test('switching sharing on shows at once and is sent', () async {
      final api = FakePeopleApi();
      final c = containerWith(api);
      await c.read(peopleProvider.future);

      final failure = await c.read(peopleProvider.notifier).setSharing(true);

      expect(failure, isNull);
      expect(c.read(peopleProvider).value!.sharing, isTrue);
      expect(api.sharingCalls, [true]);
    });

    test('a switch the service did not accept goes back, with the reason',
        () async {
      final api = FakePeopleApi()
        ..sharingAnswer =
            const Result<void>.err(NetworkFailure('Cannot reach'));
      final c = containerWith(api);
      await c.read(peopleProvider.future);

      final failure = await c.read(peopleProvider.notifier).setSharing(true);

      expect(failure, isA<NetworkFailure>());
      expect(c.read(peopleProvider).value!.sharing, isFalse,
          reason: 'what is shown is what the server holds');
    });
  });

  group('friends', () {
    test('are listed as the service says', () async {
      final api = FakePeopleApi()
        ..friendAnswers.add(Result.ok([friendActivity('ben', 'Dogs')]));
      final c = ProviderContainer(overrides: [
        peopleApiProvider.overrideWith((ref) async => api),
        friendsPollEveryProvider.overrideWithValue(Duration.zero),
      ]);
      addTearDown(c.dispose);
      final sub = c.listen(friendsProvider, (_, __) {});
      addTearDown(sub.close);

      await pumpEventQueue();

      expect(c.read(friendsProvider).value!.map((f) => f.user), ['ben']);
    });

    test('keep their last list when one look fails, and keep looking',
        () async {
      final api = FakePeopleApi()
        ..friendAnswers.addAll([
          Result.ok([friendActivity('ben', 'Dogs')]),
          const Result.err(NetworkFailure('down')),
        ]);
      final c = ProviderContainer(overrides: [
        peopleApiProvider.overrideWith((ref) async => api),
        friendsPollEveryProvider.overrideWithValue(Duration.zero),
      ]);
      addTearDown(c.dispose);
      final sub = c.listen(friendsProvider, (_, __) {});
      addTearDown(sub.close);

      await pumpEventQueue(times: 50);

      expect(c.read(friendsProvider).value!.map((f) => f.user), ['ben']);
      expect(api.friendCalls, greaterThan(2),
          reason: 'one failed look is not the end of looking');
    });

    test('stop being asked once nobody is watching', () async {
      final api = FakePeopleApi();
      final c = ProviderContainer(overrides: [
        peopleApiProvider.overrideWith((ref) async => api),
        friendsPollEveryProvider.overrideWithValue(Duration.zero),
      ]);
      addTearDown(c.dispose);
      final sub = c.listen(friendsProvider, (_, __) {});
      await pumpEventQueue(times: 20);

      sub.close();
      await pumpEventQueue(
          times: 5); // lets the provider notice it is unwatched
      final calls = api.friendCalls;
      await pumpEventQueue(times: 50);

      expect(api.friendCalls, calls,
          reason: 'no more requests after the page closes');
    });

    test('are an empty list when there is no service', () async {
      final c = ProviderContainer(overrides: [
        peopleApiProvider.overrideWith((ref) async => null),
      ]);
      addTearDown(c.dispose);
      final sub = c.listen(friendsProvider, (_, __) {});
      addTearDown(sub.close);

      await pumpEventQueue();

      expect(c.read(friendsProvider).value, isEmpty);
    });
  });
}
