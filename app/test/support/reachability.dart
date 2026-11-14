import 'package:encore/app/connection.dart';

/// The one state of "can I reach my server" held at a value, for tests of a reader that is not about how the state is made (the rows, the words,
/// the download lines): `serverReachabilityProvider.overrideWith(() => FixedReachability(ServerReachability.serverAway))`. A test of the state
/// itself overrides its raw facts instead (`networkKindProvider`, `serverFindingProvider`, `networkValidationProvider`).
class FixedReachability extends ServerReachabilityNotifier {
  FixedReachability(this.value);

  final ServerReachability value;

  @override
  ServerReachability build() => value;
}

/// The same, with the value read each time the provider is built (so a test that flips it and invalidates the provider sees the change).
class ReachabilityFrom extends ServerReachabilityNotifier {
  ReachabilityFrom(this.pick);

  final ServerReachability Function() pick;

  @override
  ServerReachability build() => pick();
}
