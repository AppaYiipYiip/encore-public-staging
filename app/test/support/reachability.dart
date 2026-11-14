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
