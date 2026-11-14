import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/connection.dart';
import '../../app/providers.dart' show NetworkKind, networkKindProvider;
import '../../data/repos/downloads_repository.dart' show PinTargetType;
import '../providers.dart' show downloadedIdsProvider, onPhoneProvider;

/// Whether the phone cannot fetch anything from the person's server **right now**: it has no network, or its server does not answer (or
/// another one does). This is the LASTING state: it holds for as long as the outage does and goes by itself when the connection is back.
/// It is not the strip's state: the strip says an outage once, for a few seconds, and then goes (D-45), so a look that followed the strip
/// would vanish with it, which was R2-F5 ("no sign of being offline"). The server's silence counts after the grace of
/// [connectionProblemProvider] (a blink of the network is not news); having no network at all counts at once (P1-09).
final serverAwayProvider = Provider<bool>((ref) {
  final noNetwork = ref.watch(
      networkKindProvider.select((kind) => kind.value == NetworkKind.none));
  if (noNetwork) return true;
  final problem = ref.watch(connectionProblemProvider);
  return problem == ConnectionProblem.offline || problem.serverIsAway;
});

/// Why the server cannot be reached, in the strip's own two causes (docs/31 CN-1 and CN-4b, D-45 amended).
enum AwayCause {
  /// No network at all, or a network on which Android found no internet (4G with no data, a Wi-Fi with a sign-in page): the person is
  /// offline, and "connect" is the way out.
  noInternet,

  /// Internet is found and the server alone does not answer (or another one does, CN-11: the person's own is not there either).
  serverSilent,
}

/// [AwayCause] while the server is away ([serverAwayProvider]), `null` while it is not: the question every page asks when it must say in
/// words WHY it cannot do something (Search offline, P1-16). It reads the strip's own facts and nothing new: the same lasting state, the
/// same Android answer ([phoneHasInternetProvider]) and the same rule as the strip's sentence and the player's "Not downloaded. Connect to
/// play it." (`playback_engine.dart`, `_notDownloadedWords`), so on one screen they cannot disagree.
///
/// **Debt (P1-17, audit B-17):** the rule "no internet found is 'connect', a silent server with internet is 'your server'" is still written
/// three times (the strip, the player, here). P1-17's one reachability state replaces all three; this provider then becomes a read of it.
final awayCauseProvider = Provider<AwayCause?>((ref) {
  if (!ref.watch(serverAwayProvider)) return null;
  final noNetwork = ref.watch(
      networkKindProvider.select((kind) => kind.value == NetworkKind.none));
  final problem = ref.watch(connectionProblemProvider);
  if (noNetwork || problem == ConnectionProblem.offline) {
    return AwayCause.noInternet;
  }
  // Another server answering at the address is not an outage of the internet: the phone is online (the strip says so in its own words).
  if (problem == ConnectionProblem.anotherServer) return AwayCause.serverSilent;
  return (ref.watch(phoneHasInternetProvider).value ?? true)
      ? AwayCause.serverSilent
      : AwayCause.noInternet;
});

/// Whether a library song can be played right now: while the server is there every one can, while it is away only those on the phone (P1-09).
/// Rows of the others are greyed and say "Not downloaded"; a tap on one says so (the player does not try it, and does not skip).
final playabilityProvider = Provider<bool Function(String trackId)>((ref) {
  if (!ref.watch(serverAwayProvider)) return (_) => true;
  final downloaded = ref.watch(downloadedIdsProvider).value ?? const <String>{};
  return downloaded.contains;
});

/// Whether an album or a playlist cannot be played now (S-10, S-14: it is grey and says "Not downloaded" in words): the server is away and
/// none of its songs is on the phone. A thing partly on the phone keeps its colour: it plays. Read from [onPhoneProvider], the same
/// downloaded songs [playabilityProvider] reads, so a row, a card and a Library entry cannot disagree. Unknown yet counts as playable: a
/// moment of colour is better than a wrong grey.
final notDownloadedNowProvider =
    Provider.autoDispose.family<bool, (PinTargetType, String)>((ref, target) {
  if (!ref.watch(serverAwayProvider)) return false;
  final held = ref.watch(onPhoneProvider).value;
  if (held == null) return false;
  return switch (target.$1) {
    PinTargetType.album => !held.albums.contains(target.$2),
    PinTargetType.playlist => !held.playlists.contains(target.$2),
    _ => false,
  };
});

/// The words under a thing that cannot be played now (S-10, S-14, S-17, S-18).
const String kNotDownloadedWords = 'Not downloaded';
