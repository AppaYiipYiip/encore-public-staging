import 'dart:async';
import 'dart:io';

import 'package:vm_service/vm_service.dart';
import 'package:vm_service/vm_service_io.dart';

/// Allocation *rate* by class over N seconds on the main isolate: a hot
/// timer / stream loop shows up as thousands of tiny objects per second.
Future<void> main(List<String> args) async {
  final uri = args[0];
  final seconds = args.length > 1 ? int.parse(args[1]) : 10;
  final top = args.length > 2 ? int.parse(args[2]) : 30;

  final service = await vmServiceConnectUri(uri);
  final vm = await service.getVM();
  final main = vm.isolates!
      .firstWhere((i) => i.name == 'main', orElse: () => vm.isolates!.first);
  await service.getAllocationProfile(main.id!, reset: true);
  await Future<void>.delayed(Duration(seconds: seconds));
  final profile = await service.getAllocationProfile(main.id!);
  final rows = [...?profile.members]..sort((a, b) =>
      (b.instancesAccumulated ?? 0).compareTo(a.instancesAccumulated ?? 0));
  stdout.writeln('allocations on main isolate over ${seconds}s '
      '(instances accumulated, per second):');
  for (final m in rows.take(top)) {
    final n = m.instancesAccumulated ?? 0;
    if (n == 0) break;
    stdout.writeln('  ${(n / seconds).toStringAsFixed(0).padLeft(7)}/s  '
        '${m.classRef?.name}  ${m.classRef?.library?.uri ?? ''}');
  }
  await service.dispose();
  exit(0);
}
