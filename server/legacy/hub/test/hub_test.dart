import 'package:encore_hub/encore_hub.dart';
import 'package:encore_session/encore_session.dart';
import 'package:test/test.dart';

/// What a session is, as three friends in a living room would say it
/// (docs/30): somebody starts it and is the host, the others join with a code,
/// everybody adds songs and presses play, the host can send somebody away, and
/// when the host leaves the evening is over. The hub keeps the one true state
/// and tells everybody the new one after every change.
void main() {
  late int now;
  late Hub hub;

  setUp(() {
    now = 1000;
    hub = Hub(clock: () => now);
  });

  List<SessionState> hear(String code, String user) {
    final heard = <SessionState>[];
    hub.subscribe(code, user, (event) {
      if (event is StateEvent) heard.add(event.state);
    });
    return heard;
  }

  test('somebody starts a session, is its host, and gets a code to share', () {
    final session = hub.create('owner')!;

    expect(session.code, matches(RegExp(r'^[A-HJ-NP-Z2-9]{6}$')),
        reason: 'six letters and digits without the ones that look alike');
    expect(session.state.members,
        [const Member(id: 'owner', name: 'owner', role: Role.host)]);
    expect(hub.find(session.code), same(session));
  });

  test('starting another session ends the first one', () {
    final first = hub.create('owner')!;
    final second = hub.create('owner')!;

    expect(first.state.ended, isTrue);
    expect(second.state.ended, isFalse);
    expect(hub.find(first.code), isNull, reason: 'its code stops working');
  });

  test('a friend joins with the code, whatever the letter case', () {
    final session = hub.create('owner')!;

    final joined = hub.join(session.code.toLowerCase(), 'mia');

    expect(joined.ok, isTrue, reason: joined.rejected ?? '');
    expect(hub.find(session.code)!.state.members.map((m) => m.id),
        ['owner', 'mia']);
    expect(hub.find(session.code)!.state.member('mia')!.role, Role.member);
  });

  test('a code that does not exist says so in plain words', () {
    final joined = hub.join('ZZZZZZ', 'mia');

    expect(joined.ok, isFalse);
    expect(joined.rejected, 'there is no session with that code');
  });

  test('everybody listening hears the state at once and after every change',
      () {
    final session = hub.create('owner')!;
    hub.join(session.code, 'mia');
    final heard = hear(session.code, 'mia');

    expect(heard, hasLength(1), reason: 'the current state, straight away');

    hub.command(session.code, 'owner', const Add('song-a'));
    hub.command(session.code, 'mia', const Add('song-b'));
    hub.command(session.code, 'mia', const Play());

    expect(heard, hasLength(4));
    expect([for (final e in heard.last.queue) '${e.trackId} by ${e.addedBy}'],
        ['song-a by owner', 'song-b by mia']);
    expect(
        heard.map((s) => s.rev).toList(), [...heard.map((s) => s.rev)]..sort(),
        reason: 'in order: a phone keeps the highest revision');
    expect(heard.last.playing, isTrue);
  });

  test('the hub clock is what positions are measured from', () {
    final session = hub.create('owner')!;
    hub.command(session.code, 'owner', const Add('song-a'));

    now = 5000;
    hub.command(session.code, 'owner', const Play());

    expect(hub.find(session.code)!.state.anchor, const Anchor(5000, 0));
  });

  test('a command from somebody who is not in the session is refused', () {
    final session = hub.create('owner')!;

    final result = hub.command(session.code, 'stranger', const Play());

    expect(result.ok, isFalse);
    expect(result.rejected, 'you are not in this session');
  });

  test('only the host sends somebody away, and they are told', () {
    final session = hub.create('owner')!;
    hub.join(session.code, 'mia');
    hub.join(session.code, 'ben');
    final events = <HubEvent>[];
    hub.subscribe(session.code, 'ben', events.add);

    final refused = hub.command(session.code, 'mia', const Kick('ben'));
    expect(refused.rejected, 'only the host can do that');

    final done = hub.command(session.code, 'owner', const Kick('ben'));
    expect(done.ok, isTrue);
    expect(events.whereType<KickedEvent>(), hasLength(1),
        reason: 'ben is told, so his phone can leave');
    expect(hub.find(session.code)!.state.members.map((m) => m.id),
        ['owner', 'mia']);
  });

  test('a friend leaving does not end it; the host leaving does, for everybody',
      () {
    final session = hub.create('owner')!;
    hub.join(session.code, 'mia');
    final heard = hear(session.code, 'mia');

    hub.leaveSession(session.code, 'mia');
    expect(hub.find(session.code)!.state.ended, isFalse);

    hub.join(session.code, 'ben');
    final benHeard = hear(session.code, 'ben');
    hub.leaveSession(session.code, 'owner');

    expect(benHeard.last.ended, isTrue, reason: 'ben hears that it is over');
    expect(heard.last.ended, isFalse,
        reason: 'mia had left: she hears nothing more');
    expect(hub.find(session.code), isNull);
  });

  test('somebody who stops listening is not sent anything any more', () {
    final session = hub.create('owner')!;
    hub.join(session.code, 'mia');
    final heard = <SessionState>[];
    final listening = hub.subscribe(session.code, 'mia', (event) {
      if (event is StateEvent) heard.add(event.state);
    })!;

    listening.cancel();
    hub.command(session.code, 'owner', const Add('song-a'));

    expect(heard, hasLength(1), reason: 'only the first, before they stopped');
  });

  test('a session nobody touches for hours is ended and forgotten', () {
    final session = hub.create('owner')!;
    final heard = hear(session.code, 'owner');

    now += const Duration(hours: 7).inMilliseconds;
    final ended = hub.sweep();

    expect(ended, 1);
    expect(hub.find(session.code), isNull);
    expect(heard.last.ended, isTrue);
  });

  test('a session in use is kept however long it runs', () {
    final session = hub.create('owner')!;
    for (var hour = 0; hour < 10; hour++) {
      now += const Duration(hours: 1).inMilliseconds;
      hub.command(session.code, 'owner', const Add('song'));
      hub.sweep();
    }
    expect(hub.find(session.code), isNotNull);
  });

  test('the hub refuses a new session when it is full', () {
    final small = Hub(clock: () => now, maxSessions: 2);
    expect(small.create('a'), isNotNull);
    expect(small.create('b'), isNotNull);
    expect(small.create('c'), isNull);
  });

  test('two sessions at once do not share anything', () {
    final one = hub.create('owner')!;
    final two = hub.create('mia')!;
    hub.command(one.code, 'owner', const Add('only-in-one'));

    expect(hub.find(two.code)!.state.queue, isEmpty);
  });
}
