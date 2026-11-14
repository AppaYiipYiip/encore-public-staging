import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/connection.dart';
import '../../data/repos/downloads_repository.dart' show PinTargetType;
import '../providers.dart' show downloadedIdsProvider, onPhoneProvider;

/// Why the server cannot be reached, in the strip's own two causes (docs/31 CN-1 and CN-4b, D-45 amended).
enum AwayCause {
  /// No network at all, or a network on which Android found no internet (4G with no data, a Wi-Fi with a sign-in page): the person is
  /// offline, and "connect" is the way out.
  noInternet,

  /// Internet is found and the server alone does not answer (or another one does, CN-11: the person's own is not there either).
  serverSilent,
}

/// [AwayCause] while the server is away (`serverReachabilityProvider.isAway`), `null` while it is not: the question every page asks when it must
/// say in words WHY it cannot do something (Search offline, P1-16). A plain read of the one state (P1-17): no network and no internet are "connect", the server
/// silent or another one answering is "your server". The same rule picks the strip's sentence and the player's "Not downloaded. Connect to play
/// it.", so on one screen they cannot disagree.
final awayCauseProvider = Provider<AwayCause?>((ref) {
  return switch (ref.watch(serverReachabilityProvider)) {
    ServerReachability.noNetwork ||
    ServerReachability.noInternet =>
      AwayCause.noInternet,
    ServerReachability.serverAway ||
    ServerReachability.wrongServer =>
      AwayCause.serverSilent,
    ServerReachability.ok || ServerReachability.unknown => null,
  };
});

/// Whether a library song can be played right now: while the server is there every one can, while it is away only those on the phone (P1-09).
/// Rows of the others are greyed and say "Not downloaded"; a tap on one says so (the player does not try it, and does not skip).
final playabilityProvider = Provider<bool Function(String trackId)>((ref) {
  if (!ref.watch(serverReachabilityProvider).isAway) return (_) => true;
  final downloaded = ref.watch(downloadedIdsProvider).value ?? const <String>{};
  return downloaded.contains;
});

/// Whether an album or a playlist cannot be played now (S-10, S-14: it is grey and says "Not downloaded" in words): the server is away and
/// none of its songs is on the phone. A thing partly on the phone keeps its colour: it plays. Read from [onPhoneProvider], the same
/// downloaded songs [playabilityProvider] reads, so a row, a card and a Library entry cannot disagree. Unknown yet counts as playable: a
/// moment of colour is better than a wrong grey.
final notDownloadedNowProvider =
    Provider.autoDispose.family<bool, (PinTargetType, String)>((ref, target) {
  if (!ref.watch(serverReachabilityProvider).isAway) return false;
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

/// The words under a catalogue song the server already knows it cannot get (N-13, S-12, S-18, S-19): the same grey as [kNotDownloadedWords], other
/// words, because the cause is not the connection. Offline always wins: while the server is away the row says [kNotDownloadedWords] or nothing.
const String kNotAvailableWords = 'Not available on your server';
