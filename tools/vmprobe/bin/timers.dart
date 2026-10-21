import 'dart:async';
import 'dart:io';

import 'package:vm_service/vm_service.dart';
import 'package:vm_service/vm_service_io.dart';

/// Lists the live `Timer` objects of the main isolate with their interval and
/// the function they will call - the quickest way to find a timer storm.
Future<void> main(List<String> args) async {
  final uri = args[0];
  final service = await vmServiceConnectUri(uri);
  final vm = await service.getVM();
  final main = vm.isolates!
      .firstWhere((i) => i.name == 'main', orElse: () => vm.isolates!.first);
  final isolateId = main.id!;

  final classes = await service.getClassList(isolateId);
  final timerClasses = [
    for (final c in classes.classes ?? const <ClassRef>[])
      if ((c.name ?? '').contains('Timer')) c,
  ];
  stdout.writeln('timer classes: '
      '${[for (final c in timerClasses) '${c.name}@${c.library?.uri}']}');

  for (final c in timerClasses) {
    if (c.name != '_Timer' &&
        c.name != '_SimpleTimer' &&
        c.name != '_PeriodicTimer') {
      continue;
    }
    final inst = await service.getInstances(isolateId, c.id!, 400);
    stdout.writeln('--- ${c.name}: ${inst.totalCount} live instances');
    final summary = <String, int>{};
    for (final ref in inst.instances ?? const <ObjRef>[]) {
      final obj = await service.getObject(isolateId, ref.id!);
      if (obj is! Instance) continue;
      String? ms;
      String? cb;
      for (final f in obj.fields ?? const <BoundField>[]) {
        final name = f.decl?.name;
        final v = f.value;
        if (name == '_milliSeconds' ||
            name == '_period' ||
            name == '_interval') {
          ms = v is InstanceRef ? v.valueAsString : '$v';
        }
        if (name == '_callback' && v is InstanceRef) {
          final closure = await service.getObject(isolateId, v.id!);
          if (closure is Instance && closure.closureFunction != null) {
            final fn = closure.closureFunction!;
            final owner = fn.owner;
            String ownerName = '';
            if (owner is FuncRef) {
              ownerName = '${owner.name}/';
              final o2 = owner.owner;
              if (o2 is ClassRef) ownerName = '${o2.name}.$ownerName';
              if (o2 is LibraryRef) ownerName = '${o2.uri}::$ownerName';
            } else if (owner is ClassRef) {
              ownerName = '${owner.name}.';
              ownerName = '${owner.library?.uri}::$ownerName';
            } else if (owner is LibraryRef) {
              ownerName = '${owner.uri}::';
            }
            cb = '$ownerName${fn.name}';
          }
        }
      }
      final key = 'interval=${ms}ms  ->  $cb';
      summary[key] = (summary[key] ?? 0) + 1;
    }
    final rows = summary.entries.toList()
      ..sort((a, b) => b.value.compareTo(a.value));
    for (final e in rows) {
      stdout.writeln('  ${e.value.toString().padLeft(4)} x  ${e.key}');
    }
  }
  await service.dispose();
  exit(0);
}
