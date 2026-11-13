import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/navigation.dart';
import '../../core/logger.dart';
import '../../data/catalogue/catalogue_models.dart';
import '../catalogue/catalogue_providers.dart';
import '../requests/request_providers.dart' show catalogueClientProvider;

/// Opens the page of an artist known only by name: the library's own artist
/// of that name if there is one, else the best known artist of that name in
/// the public catalogue. Every artist name in the player can be tapped
/// ("i still cant press the artist name", docs/39 F11), whatever the song came
/// from. Returns `true` when a page opened; says so when nobody was found.
///
/// [beforeOpen] runs just before the page opens (the player closes itself). [replace]: the page that is open is replaced by the artist's, and
/// [quiet]: nobody found is not said in a snack bar (the caller says it on its own page).
Future<bool> openArtistByName(
  BuildContext context,
  WidgetRef ref,
  String name, {
  VoidCallback? beforeOpen,
  bool replace = false,
  bool quiet = false,
}) async {
  final messenger = ScaffoldMessenger.maybeOf(context);
  final wanted = name.trim();
  if (wanted.isEmpty) return false;
  final mine = await ref.read(libraryMatcherProvider)?.findArtist(wanted);
  if (!context.mounted) return false;
  if (mine != null) {
    beforeOpen?.call();
    Nav.artist(context, mine.id, replace: replace);
    return true;
  }

  CatalogueArtist? found;
  try {
    final results = await ref.read(catalogueClientProvider).search(wanted);
    final ranked = rankNamesakes(wanted, results.artists);
    found = ranked.isEmpty ? null : ranked.first;
  } on Object catch (error) {
    Log.warn('artist', 'lookup by name failed', error);
  }
  if (!context.mounted) return false;
  if (found == null) {
    if (!quiet) {
      messenger
        ?..hideCurrentSnackBar()
        ..showSnackBar(SnackBar(content: Text('Could not find $wanted.')));
    }
    return false;
  }
  beforeOpen?.call();
  Nav.catalogueArtist(context, found.id, preloaded: found, replace: replace);
  return true;
}
