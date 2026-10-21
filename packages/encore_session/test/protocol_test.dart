import 'dart:convert';
import 'dart:math';

import 'package:encore_session/src/protocol.dart';
import 'package:encore_session/src/reducer.dart';
import 'package:test/test.dart';

const host = Member(id: 'host', name: 'Host', role: Role.host);
const sara = Member(id: 'sara', name: 'Sara');

Command sample(Op op) => switch (op) {
      Op.play => const Play(),
      Op.pause => const Pause(),
      Op.seek => const Seek(1234),
      Op.next => const Next(),
      Op.previous => const Previous(),
      Op.setVolume => const SetVolume(30),
      Op.setRepeat => const SetRepeat(Repeat.all),
      Op.add => const Add('t1', at: AddAt.next),
      Op.remove => const Remove(7),
      Op.move => const Move(7, 2),
      Op.transfer => const Transfer('tablet'),
      Op.kick => const Kick('sara'),
      Op.ended => const Ended(3),
      Op.jump => const Jump(5),
    };

void main() {
  group('commands survive the wire', () {
    for (final op in Op.values) {
      test(op.name, () {
        final original = sample(op);
        final wire = jsonDecode(jsonEncode(original.toJson()));
        final back = Command.fromJson(wire);
        expect(back, isNotNull);
        expect(back!.toJson(), original.toJson());
      });
    }
  });

  test('a whole session survives the wire', () {
    var s = const SessionState(members: [host, sara]);
    s = reduce(s, const Add('a'), actorId: 'sara', nowHubMs: 5).state;
    s = reduce(s, const Add('b'), actorId: 'host', nowHubMs: 6).state;
    s = reduce(s, const Play(), actorId: 'host', nowHubMs: 7).state;
    s = reduce(s, const Transfer('tablet'), actorId: 'host', nowHubMs: 8).state;
    final back = SessionState.fromJson(jsonDecode(jsonEncode(s.toJson())));
    expect(back, isNotNull);
    expect(jsonEncode(back!.toJson()), jsonEncode(s.toJson()));
    expect(back.positionAt(1007), s.positionAt(1007));
  });

  group('garbage is refused, never thrown', () {
    final garbage = <Object?>[
      null,
      42,
      'play',
      <Object?>[],
      <String, Object?>{},
      {'op': 'launch'},
      {'op': 7},
      {'op': 'seek'},
      {'op': 'seek', 'posMs': -1},
      {'op': 'seek', 'posMs': 'soon'},
      {'op': 'seek', 'posMs': 99999999999},
      {'op': 'setVolume', 'level': 101},
      {'op': 'setRepeat', 'mode': 'forever'},
      {'op': 'add'},
      {'op': 'add', 'trackId': ''},
      {'op': 'add', 'trackId': 'x' * 500},
      {'op': 'add', 'trackId': 'a', 'at': 'sideways'},
      {'op': 'remove', 'uid': 1.5},
      {'op': 'move', 'uid': 1},
      {'op': 'transfer', 'deviceId': null},
      {'op': 'kick'},
    ];
    for (var i = 0; i < garbage.length; i++) {
      test('command #$i', () {
        expect(Command.fromJson(garbage[i]), isNull);
      });
    }

    test('states with the wrong shape are refused', () {
      final good = const SessionState(members: [host]).toJson();
      expect(SessionState.fromJson(good), isNotNull);
      for (final key in good.keys) {
        // "player" is a free-form id, so only a non-string is nonsense there.
        final broken = {...good, key: key == 'player' ? 42 : 'nonsense'};
        expect(SessionState.fromJson(broken), isNull,
            reason: 'accepted a state whose "$key" is nonsense');
        if (key == 'player') continue; // optional: no speaker chosen yet
        final missing = {...good}..remove(key);
        expect(SessionState.fromJson(missing), isNull,
            reason: 'accepted a state without "$key"');
      }
    });

    test('random damage to a valid message never throws', () {
      final random = Random(7);
      final good = jsonDecode(jsonEncode(
        (const SessionState(
                members: [host, sara],
                queue: [QueueEntry(uid: 1, trackId: 'a', addedBy: 'host')]))
            .toJson(),
      ));
      Object? damage(Object? node, int depth) {
        if (node is Map<String, Object?>) {
          return {
            for (final e in node.entries)
              e.key: random.nextInt(8) == 0
                  ? _junk(random)
                  : damage(e.value, depth + 1)
          };
        }
        if (node is List<Object?>) {
          return [for (final v in node) damage(v, depth + 1)];
        }
        return random.nextInt(8) == 0 ? _junk(random) : node;
      }

      for (var i = 0; i < 500; i++) {
        final broken = damage(good, 0);
        SessionState.fromJson(broken); // must return, not throw
        Command.fromJson(broken);
      }
    });
  });
}

Object? _junk(Random random) => switch (random.nextInt(6)) {
      0 => null,
      1 => random.nextInt(1 << 30) - (1 << 29),
      2 => 'x' * random.nextInt(300),
      3 => <Object?>[random.nextInt(5), null],
      4 => <String, Object?>{'a': random.nextBool()},
      _ => random.nextBool(),
    };
