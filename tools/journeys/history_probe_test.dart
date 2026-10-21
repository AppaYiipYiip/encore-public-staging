// Reads a person's real play history with the app's own client and prints what it found. Not part of the normal suite
// (it needs the real server): run it by hand,
//
//   ENCORE_LOGIN=../encore-tester-login.txt flutter test tool/journeys/history_probe_test.dart
//
// The password comes from the login file and is never printed.
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:encore/data/api/opensubsonic/opensubsonic_client.dart'
    show SubsonicCredentials;
import 'package:encore/data/navidrome/play_history_client.dart';

void main() {
  test('the real play history of one person', () async {
    final path = Platform.environment['ENCORE_LOGIN'];
    if (path == null) return;
    final fields = <String, String>{};
    for (final line in File(path).readAsLinesSync()) {
      final m =
          RegExp(r'^(address|user|password):\s*(.*)$').firstMatch(line.trim());
      if (m != null) fields[m.group(1)!] = m.group(2)!;
    }
    final client = PlayHistoryClient(
      dio: Dio(),
      baseUrl: () => Uri.parse(fields['address']!),
      credentials: SubsonicCredentials(
          username: fields['user']!, password: fields['password']!),
    );
    final watch = Stopwatch()..start();
    final result = await client.fetchAll(
        progress: (done, total) => stdout.writeln('  $done of $total'));
    final listens = result.valueOrNull;
    stdout.writeln(listens == null
        ? 'failed: ${result.failureOrNull?.message}'
        : '${listens.length} plays in ${watch.elapsedMilliseconds} ms');
    for (final l in (listens ?? []).take(5)) {
      stdout.writeln('  ${l.at.toIso8601String()}  ${l.trackId}');
    }
    expect(listens, isNotNull);
  });
}
