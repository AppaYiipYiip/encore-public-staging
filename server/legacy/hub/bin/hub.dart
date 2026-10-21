import 'dart:async';
import 'dart:io';

import 'package:encore_hub/encore_hub.dart';

/// The session hub as a program (docs/29, docs/30, ADR-080).
///
/// Settings, all from the environment:
///   NAVIDROME_URL  where the music server is, from here (default http://navidrome:4533)
///   PORT           the port to listen on (default 8703)
///   HUB_BIND       the address to listen on (default 0.0.0.0)
Future<void> main() async {
  final env = Platform.environment;
  final navidrome = Uri.parse(env['NAVIDROME_URL'] ?? 'http://navidrome:4533');
  final port = int.tryParse(env['PORT'] ?? '') ?? 8703;
  final bind = env['HUB_BIND'] ?? '0.0.0.0';

  final clock = Stopwatch()..start();
  final hub = Hub(clock: () => clock.elapsedMilliseconds);
  final server = HubServer(hub: hub, verifier: NavidromeVerifier(navidrome));
  final socket = await server.bind(bind, port);
  stdout.writeln(
      'encore-hub on ${socket.address.address}:${socket.port}, music server $navidrome');

  // Stop cleanly when Docker asks (a session is memory only: nothing to save).
  final stopped = Completer<void>();
  void stop(ProcessSignal signal) {
    stdout.writeln('encore-hub: stopping ($signal)');
    if (!stopped.isCompleted) stopped.complete();
  }

  ProcessSignal.sigterm.watch().listen(stop);
  ProcessSignal.sigint.watch().listen(stop);
  await stopped.future;
  await server.close();
}
