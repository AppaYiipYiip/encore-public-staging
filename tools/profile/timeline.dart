// What is the app doing while it is slow? Records the Dart VM timeline of a PROFILE build for a few
// seconds and says where the time went, per thread (the UI thread builds, the raster thread draws).
//
//   dart tool/profile/timeline.dart ws://127.0.0.1:PORT/TOKEN=/ws SECONDS [out.json]
//
// Start the app (profile build) on the phone or emulator, find the service address in the log
// (`adb logcat -d | findstr "Dart VM service"`), `adb forward tcp:PORT tcp:PORT`, run this, and do the
// slow thing (scroll, open a screen, play) during the SECONDS. Standard library only.
//
// Reading the answer:
//   * "1.ui" rows: BUILD / LAYOUT / PAINT / COMPOSITING are the app's own work; a long BUILD names the
//     widgets that rebuilt (the frames' children, when widget-build tracing is on).
//   * "1.raster" rows: what the GPU thread spent drawing (Impeller/Skia). Long rows with a quiet UI
//     thread mean "too much to draw" (shadows, clips, big images), not "slow Dart code".
//   * "other" rows that are long on the UI thread between frames are work that is not drawing at all.
import 'dart:async';
import 'dart:convert';
import 'dart:io';

Future<void> main(List<String> args) async {
  if (args.length < 2) {
    stderr.writeln(
        'usage: dart tool/profile/timeline.dart WS_URL SECONDS [out.json]');
    exit(64);
  }
  final seconds = int.parse(args[1]);
  final socket = await WebSocket.connect(args[0]);
  var nextId = 0;
  final pending = <int, Completer<Map<String, dynamic>>>{};
  socket.listen((data) {
    final message = jsonDecode(data as String) as Map<String, dynamic>;
    final id = message['id'];
    if (id is int) pending.remove(id)?.complete(message);
  });

  Future<Map<String, dynamic>> call(String method,
      [Map<String, dynamic> params = const {}]) {
    final id = nextId++;
    final reply = Completer<Map<String, dynamic>>();
    pending[id] = reply;
    socket.add(jsonEncode(
        {'jsonrpc': '2.0', 'id': id, 'method': method, 'params': params}));
    return reply.future;
  }

  await call('setVMTimelineFlags', {
    'recordedStreams': ['Dart', 'Embedder', 'GC', 'API']
  });
  await call('clearVMTimeline');
  stdout.writeln('recording for $seconds s ... (do the slow thing now)');
  await Future<void>.delayed(Duration(seconds: seconds));
  final reply = await call('getVMTimeline');
  await socket.close();

  final result = reply['result'] as Map<String, dynamic>;
  final events = (result['traceEvents'] as List).cast<Map<String, dynamic>>();
  if (args.length > 2) File(args[2]).writeAsStringSync(jsonEncode(result));
  _report(events);
}

class _Stat {
  int count = 0;
  double totalMs = 0;
  double maxMs = 0;
  final List<double> all = [];

  void add(double ms) {
    count++;
    totalMs += ms;
    if (ms > maxMs) maxMs = ms;
    all.add(ms);
  }

  double get p95 {
    final sorted = [...all]..sort();
    return sorted[(sorted.length * 0.95).floor().clamp(0, sorted.length - 1)];
  }
}

void _report(List<Map<String, dynamic>> events) {
  // Thread names come from metadata events.
  final names = <String, String>{};
  for (final e in events) {
    if (e['ph'] == 'M' && e['name'] == 'thread_name') {
      names['${e['pid']}/${e['tid']}'] = (e['args'] as Map)['name'] as String;
    }
  }
  // Complete events carry a duration; begin/end pairs are matched per thread.
  final open = <String, List<Map<String, dynamic>>>{};
  final perThread = <String, Map<String, _Stat>>{};
  var firstTs = double.infinity, lastTs = 0.0;

  void record(String thread, String name, double durUs) {
    perThread
        .putIfAbsent(thread, () => {})
        .putIfAbsent(name, _Stat.new)
        .add(durUs / 1000);
  }

  for (final e in events) {
    final ph = e['ph'];
    final ts = (e['ts'] as num?)?.toDouble();
    if (ts != null) {
      if (ts < firstTs) firstTs = ts;
      if (ts > lastTs) lastTs = ts;
    }
    final key = '${e['pid']}/${e['tid']}';
    final thread = names[key] ?? key;
    if (ph == 'X') {
      record(thread, e['name'] as String, (e['dur'] as num).toDouble());
    } else if (ph == 'B') {
      open.putIfAbsent(key, () => []).add(e);
    } else if (ph == 'E') {
      final stack = open[key];
      if (stack != null && stack.isNotEmpty) {
        final b = stack.removeLast();
        record(thread, b['name'] as String,
            (e['ts'] as num).toDouble() - (b['ts'] as num).toDouble());
      }
    }
  }

  final window = (lastTs - firstTs) / 1e6;
  stdout.writeln(
      '\nwindow ${window.toStringAsFixed(1)} s, ${events.length} events\n');
  final interesting = perThread.keys
      .where(
          (t) => t.contains('ui') || t.contains('raster') || t.contains('io'))
      .toList()
    ..sort();
  for (final thread in interesting) {
    final rows = perThread[thread]!.entries.toList()
      ..sort((a, b) => b.value.totalMs.compareTo(a.value.totalMs));
    stdout.writeln('== $thread');
    stdout.writeln(
        '   ${'event'.padRight(44)} ${'count'.padLeft(6)} ${'total ms'.padLeft(9)} ${'p95 ms'.padLeft(8)} ${'max ms'.padLeft(8)}');
    for (final r in rows.take(14)) {
      final s = r.value;
      stdout.writeln(
          '   ${r.key.padRight(44).substring(0, 44)} ${s.count.toString().padLeft(6)} '
          '${s.totalMs.toStringAsFixed(0).padLeft(9)} ${s.p95.toStringAsFixed(1).padLeft(8)} ${s.maxMs.toStringAsFixed(1).padLeft(8)}');
    }
    stdout.writeln('');
  }
}
