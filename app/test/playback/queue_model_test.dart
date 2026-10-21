import 'dart:math';

import 'package:encore/playback/queue_model.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/factories.dart';

List<String> ids(Iterable<QueueItem> items) => [for (final i in items) i.id];

void main() {
  late QueueModel q;

  setUp(() {
    q = QueueModel(random: Random(42));
  });

  group('basics', () {
    test('starts empty', () {
      expect(q.isEmpty, isTrue);
      expect(q.current, isNull);
      expect(q.hasNext, isFalse);
      expect(q.hasPrevious, isFalse);
      expect(q.skipNext(), isFalse);
      expect(q.skipPrevious(), isFalse);
    });

    test('replace positions on the start index', () {
      q.replace(queueItems(5), startIndex: 2);
      expect(q.current!.id, 't3');
      expect(ids(q.upNext), ['t4', 't5']);
      expect(q.cursor, 2);
    });

    test('start index is clamped', () {
      q.replace(queueItems(3), startIndex: 99);
      expect(q.current!.id, 't3');
      q.replace(queueItems(3), startIndex: -4);
      expect(q.current!.id, 't1');
    });

    test('walks forward and stops at the end with repeat off', () {
      q.replace(queueItems(3));
      expect(q.skipNext(), isTrue);
      expect(q.skipNext(), isTrue);
      expect(q.current!.id, 't3');
      expect(q.hasNext, isFalse);
      expect(q.skipNext(), isFalse);
      expect(q.current!.id, 't3', reason: 'stays on the last track');
    });

    test('previous walks back and stops at the start', () {
      q.replace(queueItems(3), startIndex: 2);
      expect(q.skipPrevious(), isTrue);
      expect(q.skipPrevious(), isTrue);
      expect(q.skipPrevious(), isFalse);
      expect(q.current!.id, 't1');
    });
  });

  group('repeat', () {
    test('repeat all wraps forward and backward', () {
      q
        ..replace(queueItems(3), startIndex: 2)
        ..setRepeat(QueueRepeat.all);
      expect(q.hasNext, isTrue);
      expect(q.peekNext!.id, 't1');
      expect(q.skipNext(), isTrue);
      expect(q.current!.id, 't1');
      expect(q.hasPrevious, isTrue);
      expect(q.skipPrevious(), isTrue);
      expect(q.current!.id, 't3');
    });

    test('repeat one repeats on auto-advance but not on manual skip', () {
      q
        ..replace(queueItems(3))
        ..setRepeat(QueueRepeat.one);
      expect(q.advanceAuto(), isTrue);
      expect(q.current!.id, 't1', reason: 'finishing repeats the track');
      expect(q.skipNext(), isTrue);
      expect(q.current!.id, 't2', reason: 'pressing next moves on');
    });

    test('auto-advance at the end with repeat off reports "finished"', () {
      q.replace(queueItems(2), startIndex: 1);
      expect(q.advanceAuto(), isFalse);
    });

    test('a single-track queue with repeat all still has no previous', () {
      q
        ..replace(queueItems(1))
        ..setRepeat(QueueRepeat.all);
      expect(q.hasPrevious, isFalse);
    });
  });

  group('shuffle', () {
    test('keeps the current track first and plays every track once', () {
      q.replace(queueItems(20), startIndex: 7, shuffle: true);
      expect(q.current!.id, 't8');
      expect(q.cursor, 0);
      final played = <String>[q.current!.id];
      while (q.skipNext()) {
        played.add(q.current!.id);
      }
      expect(played.length, 20);
      expect(played.toSet().length, 20, reason: 'no duplicates, none missing');
    });

    test('turning shuffle off restores the arranged order at the same track',
        () {
      q.replace(queueItems(10), startIndex: 3);
      q.setShuffle(true);
      q.skipNext();
      q.skipNext();
      final now = q.current!.id;
      q.setShuffle(false);
      expect(q.current!.id, now);
      expect(ids(q.ordered), ids(queueItems(10)));
    });

    test('turning shuffle on mid-queue keeps what is playing', () {
      q.replace(queueItems(10), startIndex: 4);
      q.setShuffle(true);
      expect(q.current!.id, 't5');
      expect(q.ordered.length, 10);
    });

    test('is deterministic for a seeded random', () {
      final a = QueueModel(random: Random(7))
        ..replace(queueItems(30), shuffle: true);
      final b = QueueModel(random: Random(7))
        ..replace(queueItems(30), shuffle: true);
      expect(ids(a.ordered), ids(b.ordered));
    });
  });

  group('editing', () {
    test('addToEnd appends', () {
      q.replace(queueItems(2));
      q.addToEnd(QueueItem(uid: 99, id: 'x', title: 'X'));
      expect(ids(q.ordered), ['t1', 't2', 'x']);
      expect(q.current!.id, 't1');
    });

    test('addToEnd on an empty queue starts it', () {
      q.addToEnd(QueueItem(uid: 99, id: 'x', title: 'X'));
      expect(q.current!.id, 'x');
    });

    test('playNext inserts right after the current track', () {
      q.replace(queueItems(4), startIndex: 1);
      q.playNext(QueueItem(uid: 99, id: 'x', title: 'X'));
      expect(ids(q.upNext), ['x', 't3', 't4']);
      expect(q.current!.id, 't2');
    });

    test('playNext twice puts the latest first', () {
      q.replace(queueItems(3));
      q.playNext(QueueItem(uid: 90, id: 'a', title: 'A'));
      q.playNext(QueueItem(uid: 91, id: 'b', title: 'B'));
      expect(ids(q.upNext), ['b', 'a', 't2', 't3']);
    });

    test('playNext while shuffled still plays it next', () {
      q.replace(queueItems(6), startIndex: 0, shuffle: true);
      q.playNext(QueueItem(uid: 99, id: 'x', title: 'X'));
      expect(q.upNext.first.id, 'x');
      q.setShuffle(false);
      expect(q.ordered.map((e) => e.id), contains('x'));
    });

    test('the same track can be queued twice', () {
      q.replace(queueItems(2));
      q.addToEnd(QueueItem(uid: 50, id: 't1', title: 'Song 1'));
      expect(q.ordered.where((e) => e.id == 't1').length, 2);
      expect(q.ordered.map((e) => e.uid).toSet().length, 3);
    });

    test('removing an earlier entry keeps the current track current', () {
      q.replace(queueItems(5), startIndex: 3);
      final wasCurrent = q.removeAt(0);
      expect(wasCurrent, isFalse);
      expect(q.current!.id, 't4');
      expect(q.cursor, 2);
    });

    test('removing a later entry does not move the cursor', () {
      q.replace(queueItems(5), startIndex: 1);
      expect(q.removeAt(3), isFalse);
      expect(q.current!.id, 't2');
      expect(ids(q.upNext), ['t3', 't5']);
    });

    test('removing the current entry slides the next one in', () {
      q.replace(queueItems(4), startIndex: 1);
      expect(q.removeAt(1), isTrue);
      expect(q.current!.id, 't3');
    });

    test('removing the current last entry falls back to the new last', () {
      q.replace(queueItems(3), startIndex: 2);
      expect(q.removeAt(2), isTrue);
      expect(q.current!.id, 't2');
    });

    test('removing the only entry empties the queue', () {
      q.replace(queueItems(1));
      expect(q.removeAt(0), isTrue);
      expect(q.isEmpty, isTrue);
      expect(q.current, isNull);
    });

    test('move reorders and follows the current track', () {
      q.replace(queueItems(5), startIndex: 1);
      q.move(3, 0); // t4 to the front
      expect(ids(q.ordered), ['t4', 't1', 't2', 't3', 't5']);
      expect(q.current!.id, 't2');
      expect(q.cursor, 2);
    });

    test('move survives shuffle toggling (arrangement is kept)', () {
      q.replace(queueItems(4));
      q.move(3, 1); // t1 t4 t2 t3
      q.setShuffle(true);
      q.setShuffle(false);
      expect(ids(q.ordered), ['t1', 't4', 't2', 't3']);
    });

    test('clearUpNext keeps only history and the current track', () {
      q.replace(queueItems(6), startIndex: 2);
      q.clearUpNext();
      expect(ids(q.ordered), ['t1', 't2', 't3']);
      expect(q.current!.id, 't3');
      expect(q.hasNext, isFalse);
    });

    test('jumpTo validates the index', () {
      q.replace(queueItems(3));
      expect(q.jumpTo(2), isTrue);
      expect(q.current!.id, 't3');
      expect(q.jumpTo(3), isFalse);
      expect(q.jumpTo(-1), isFalse);
      expect(q.current!.id, 't3');
    });
  });

  group('persistence', () {
    final tracks = {
      for (var i = 1; i <= 6; i++) 't$i': trackRow('t$i'),
    };

    test('round trip keeps order, cursor, shuffle and repeat', () {
      q
        ..replace(queueItems(6), startIndex: 2, shuffle: true)
        ..setRepeat(QueueRepeat.all)
        ..skipNext();
      final saved = q.toJson();
      final before = ids(q.ordered);
      final current = q.current!.id;

      final restored = QueueModel()..restore(saved, tracks);
      expect(ids(restored.ordered), before);
      expect(restored.current!.id, current);
      expect(restored.shuffle, isTrue);
      expect(restored.repeat, QueueRepeat.all);
    });

    test('tracks deleted from the library are dropped', () {
      q.replace(queueItems(5), startIndex: 2);
      final saved = q.toJson();
      final partial = Map.of(tracks)..remove('t2');
      final restored = QueueModel()..restore(saved, partial);
      expect(ids(restored.ordered), ['t1', 't3', 't4', 't5']);
      expect(restored.current!.id, 't3');
    });

    test('losing the current track lands on the next survivor', () {
      q.replace(queueItems(5), startIndex: 2);
      final saved = q.toJson();
      final partial = Map.of(tracks)..remove('t3');
      final restored = QueueModel()..restore(saved, partial);
      expect(restored.current!.id, 't4');
    });

    test('an empty or garbage snapshot restores to an empty queue', () {
      final restored = QueueModel()..restore(const {}, tracks);
      expect(restored.isEmpty, isTrue);
      expect(restored.current, isNull);
    });
  });
}
