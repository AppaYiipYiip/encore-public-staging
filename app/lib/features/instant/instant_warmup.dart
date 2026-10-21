import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../catalogue/catalogue_providers.dart';
import 'instant_controller.dart';

/// Gets the first song of an album page ready before it is tapped (ADR-060):
/// the service looks it up while the person is still reading the page, so the
/// tap starts at once instead of after the lookup. Watched by the page; ends
/// with it.
final albumWarmupProvider =
    FutureProvider.autoDispose.family<void, String>((ref, albumId) async {
  if (!ref.watch(instantAvailableProvider)) return;
  final tracks = await ref.watch(catalogueAlbumTracksProvider(albumId).future);
  if (tracks.isEmpty) return;
  await ref.read(instantControllerProvider.notifier).prepare(tracks.first);
});

/// The same for an artist page's first "Popular" song.
final artistWarmupProvider =
    FutureProvider.autoDispose.family<void, String>((ref, artistId) async {
  if (!ref.watch(instantAvailableProvider)) return;
  final tracks = await ref.watch(catalogueArtistTopProvider(artistId).future);
  if (tracks.isEmpty) return;
  await ref.read(instantControllerProvider.notifier).prepare(tracks.first);
});
