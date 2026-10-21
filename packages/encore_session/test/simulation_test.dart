import 'dart:collection';
import 'dart:math';

import 'package:encore_session/src/protocol.dart';
import 'package:encore_session/src/reducer.dart';
import 'package:test/test.dart';

/// A hub and four devices on a bad network: messages are delayed, dropped and
/// arrive out of order; people press things at the same time. Whatever
/// happens, once the network settles every device shows what the hub holds
/// (docs/22 section 3.1: "a lost or repeated message cannot corrupt anything").
class Net {
  Net(this.random);

  final Random random;
  int now = 0;
  final _pending = SplayTreeMap<int, List<void Function()>>();
  int _tick = 0;

  /// Runs [action] after a random delay, or never (it was dropped).
  void send(void Function() action, {double loss = 0.3}) {
    if (random.nextDouble() < loss) return;
    _at(now + 5 + random.nextInt(400), action);
  }

  void _at(int time, void Function() action) {
    final key = time * 1000 + (_tick++ % 1000);
    (_pending[key] ??= []).add(action);
  }

  void runUntil(int time) {
    while (_pending.isNotEmpty && _pending.firstKey()! ~/ 1000 <= time) {
      final key = _pending.firstKey()!;
      now = key ~/ 1000;
      for (final a in _pending.remove(key)!) {
        a();
      }
    }
    now = time;
  }
}

class Device {
  Device(this.id);
  final String id;
  SessionState? view;

  void receive(SessionState incoming) {
    final mine = view;
    if (mine == null || incoming.rev > mine.rev) view = incoming;
  }
}

void main() {
  const people = ['host', 'sara', 'ben', 'tia'];

  Command randomCommand(Random r, SessionState hub) {
    switch (r.nextInt(12)) {
      case 0:
        return const Play();
      case 1:
        return const Pause();
      case 2:
        return Seek(r.nextInt(200000));
      case 3:
        return const Next();
      case 4:
        return const Previous();
      case 5 || 6:
        return Add('t${r.nextInt(50)}',
            at: r.nextBool() ? AddAt.end : AddAt.next);
      case 7:
        return hub.queue.isEmpty
            ? const Play()
            : Remove(hub.queue[r.nextInt(hub.queue.length)].uid);
      case 8:
        return hub.queue.isEmpty
            ? const Pause()
            : Move(hub.queue[r.nextInt(hub.queue.length)].uid, r.nextInt(6));
      case 9:
        return Kick(people[1 + r.nextInt(3)]);
      case 10:
        return SetVolume(r.nextInt(101));
      default:
        return Transfer('device${r.nextInt(3)}');
    }
  }

  for (var seed = 0; seed < 60; seed++) {
    test('seed $seed: everyone ends up showing the same session', () {
      final random = Random(seed);
      final net = Net(random);
      var hub = const SessionState(
        members: [
          Member(id: 'host', name: 'Host', role: Role.host),
          Member(id: 'sara', name: 'Sara'),
          Member(id: 'ben', name: 'Ben'),
          Member(id: 'tia', name: 'Tia'),
        ],
      );
      final devices = {for (final p in people) p: Device(p)};

      void broadcast() {
        final snapshot = hub;
        for (final d in devices.values) {
          net.send(() => d.receive(snapshot));
        }
      }

      var lastRev = hub.rev;
      for (var step = 0; step < 150; step++) {
        net.runUntil(step * 100);
        final actor = people[random.nextInt(people.length)];
        final command = randomCommand(random, hub);
        // The command travels to the hub (and may be lost on the way).
        net.send(() {
          final outcome =
              reduce(hub, command, actorId: actor, nowHubMs: net.now);
          if (outcome.ok) {
            hub = outcome.state;
            broadcast();
          }
        });
        // Invariants hold after every single step, not only at the end.
        expect(hub.rev, greaterThanOrEqualTo(lastRev), reason: 'rev went back');
        lastRev = hub.rev;
        if (hub.queue.isNotEmpty) {
          expect(hub.index, inInclusiveRange(0, hub.queue.length - 1));
        }
        expect({for (final e in hub.queue) e.uid}.length, hub.queue.length,
            reason: 'two songs share an id');
        expect(hub.queue.length, lessThanOrEqualTo(maxQueue));
      }

      // The network calms down. The hub keeps repeating its latest state
      // (its heartbeat); one of them gets through to each device.
      net.runUntil(net.now + 5000);
      for (var beat = 0; beat < 20; beat++) {
        final snapshot = hub;
        for (final d in devices.values) {
          net.send(() => d.receive(snapshot), loss: 0.2);
        }
        net.runUntil(net.now + 1000);
      }
      net.runUntil(net.now + 5000);

      for (final d in devices.values) {
        expect(d.view, isNotNull, reason: '${d.id} never heard from the hub');
        expect(d.view!.toJson(), hub.toJson(),
            reason: '${d.id} is showing an old or wrong session');
      }
    });
  }
}
