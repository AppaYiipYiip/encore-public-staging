import 'dart:async';
import 'dart:io';

import 'package:vm_service/vm_service.dart';
import 'package:vm_service/vm_service_io.dart';

/// Samples the Dart CPU profile of every isolate for N seconds and prints the
/// hottest functions (exclusive and inclusive ticks).
Future<void> main(List<String> args) async {
  final uri = args[0];
  final seconds = args.length > 1 ? int.parse(args[1]) : 10;
  final top = args.length > 2 ? int.parse(args[2]) : 25;

  final service = await vmServiceConnectUri(uri);
  try {
    final r = await service.setFlag('profiler', 'true');
    stdout.writeln('setFlag(profiler=true): ${r.type}');
  } on Object catch (e) {
    stdout.writeln('setFlag failed: $e');
  }
  final vm = await service.getVM();
  final isolates = vm.isolates ?? const <IsolateRef>[];
  stdout.writeln('isolates: ${[for (final i in isolates) '${i.name}']}');

  for (final iso in isolates) {
    try {
      await service.clearCpuSamples(iso.id!);
    } on Object catch (_) {}
  }
  final start = (await service.getVMTimelineMicros()).timestamp!;
  await Future<void>.delayed(Duration(seconds: seconds));

  for (final iso in isolates) {
    final CpuSamples samples;
    try {
      samples = await service.getCpuSamples(iso.id!, start, seconds * 1000000);
    } on Object catch (e) {
      stdout.writeln('--- ${iso.name}: $e');
      continue;
    }
    final period = samples.samplePeriod ?? 0;
    final count = samples.sampleCount ?? 0;
    stdout.writeln('--- isolate ${iso.name}: $count samples '
        '(period ${period}us => ${(count * period / 1e6).toStringAsFixed(2)} '
        's busy over ${seconds}s)');
    final fns = samples.functions ?? const <ProfileFunction>[];
    String name(ProfileFunction f) {
      final fn = f.function;
      final n = fn is FuncRef
          ? '${fn.owner is ClassRef ? '${(fn.owner as ClassRef).name}.' : ''}${fn.name}'
          : '${(fn as NativeFunction).name}';
      return '$n  ${f.resolvedUrl ?? ''}';
    }

    final byExclusive = [
      ...fns
    ]..sort((a, b) => (b.exclusiveTicks ?? 0).compareTo(a.exclusiveTicks ?? 0));
    stdout.writeln('top by EXCLUSIVE ticks:');
    for (final f in byExclusive.take(top)) {
      stdout.writeln('  ${f.exclusiveTicks}\t${name(f)}');
    }
    final byInclusive = [
      ...fns
    ]..sort((a, b) => (b.inclusiveTicks ?? 0).compareTo(a.inclusiveTicks ?? 0));
    stdout.writeln('top by INCLUSIVE ticks:');
    for (final f in byInclusive.take(top)) {
      stdout.writeln('  ${f.inclusiveTicks}\t${name(f)}');
    }
  }
  await service.dispose();
  exit(0);
}
