import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart' show NetworkKind, networkKindProvider;
import '../providers.dart' show downloadedIdsProvider;

/// Whether a library song can be played right now: with a connection every one can, without it only those on the phone (P1-09).
/// Rows of the others are greyed; a tap on one says so (the player does not try it, and does not skip).
final playabilityProvider = Provider<bool Function(String trackId)>((ref) {
  final offline = ref.watch(
      networkKindProvider.select((kind) => kind.value == NetworkKind.none));
  if (!offline) return (_) => true;
  final downloaded = ref.watch(downloadedIdsProvider).value ?? const <String>{};
  return downloaded.contains;
});
