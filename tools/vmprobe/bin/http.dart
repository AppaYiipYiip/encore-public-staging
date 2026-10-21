import 'dart:async';
import 'dart:io';

import 'package:vm_service/vm_service.dart';
import 'package:vm_service/vm_service_io.dart';

/// Lists the HTTP requests the main isolate makes over N seconds (method +
/// path, query values hidden) so idle network chatter is visible.
Future<void> main(List<String> args) async {
  final uri = args[0];
  final seconds = args.length > 1 ? int.parse(args[1]) : 15;

  final service = await vmServiceConnectUri(uri);
  final vm = await service.getVM();
  final main = vm.isolates!
      .firstWhere((i) => i.name == 'main', orElse: () => vm.isolates!.first);
  await service.httpEnableTimelineLogging(main.id!, true);
  final startedAt = DateTime.now();
  await Future<void>.delayed(Duration(seconds: seconds));
  final profile = await service.getHttpProfile(main.id!,
      updatedSince: startedAt.subtract(const Duration(seconds: 1)));
  stdout.writeln('${profile.requests.length} requests in ${seconds}s');
  final counts = <String, int>{};
  for (final r in profile.requests) {
    final key = '${r.method} ${r.uri.scheme}://${r.uri.host}:${r.uri.port}'
        '${r.uri.path}';
    counts[key] = (counts[key] ?? 0) + 1;
  }
  final sorted = counts.entries.toList()
    ..sort((a, b) => b.value.compareTo(a.value));
  for (final e in sorted.take(25)) {
    stdout.writeln('  ${e.value.toString().padLeft(5)}  ${e.key}');
  }
  await service.dispose();
  exit(0);
}
