import 'package:flutter/widgets.dart';
import 'package:go_router/go_router.dart';

import '../data/catalogue/catalogue_models.dart';

/// Route helpers. Detail routes are declared under every tab branch so the
/// bottom navigation and mini-player stay visible (Spotify-style); these
/// helpers pick the branch the user is currently in.
abstract final class Nav {
  static const _branches = {'home', 'search', 'library'};

  /// Opens [location] (one of the tab branches' detail routes). From a page
  /// that is *outside* the tabs (Settings, Import) a push would stack the whole
  /// tab shell a second time and crash the navigator (found on 2026-10-18 by the
  /// Import page's "Open playlist"), so there the page is replaced by it: Back
  /// then goes to Home.
  static void _to(BuildContext c, String Function(String branch) location) {
    final branch = _branch(c);
    if (_inBranch(c)) {
      c.push(location(branch));
    } else {
      c.go(location(branch));
    }
  }

  /// The first part of the current location (`home`, `settings`...), or `null`
  /// when there is no router above [context].
  static String? _segment(BuildContext context) {
    String path;
    try {
      path = GoRouterState.of(context).uri.path;
    } on Object {
      return null;
    }
    return path.split('/').where((s) => s.isNotEmpty).firstOrNull;
  }

  static bool _inBranch(BuildContext context) {
    final seg = _segment(context);
    return seg == null || _branches.contains(seg);
  }

  static String _branch(BuildContext context) {
    final seg = _segment(context);
    return seg != null && _branches.contains(seg) ? seg : 'home';
  }

  static void album(BuildContext c, String id) =>
      c.push('/${_branch(c)}/album/${Uri.encodeComponent(id)}');

  static void playlist(BuildContext c, String id) =>
      _to(c, (b) => '/$b/playlist/${Uri.encodeComponent(id)}');

  /// An imported playlist that may still be arriving: all its songs at once.
  static void importedPlaylist(BuildContext c, String importId) =>
      _to(c, (b) => '/$b/import/${Uri.encodeComponent(importId)}');

  static void artist(BuildContext c, String id) =>
      c.push('/${_branch(c)}/artist/${Uri.encodeComponent(id)}');

  /// A release from the public catalogue (not in the library). [preloaded]
  /// paints the header at once; without it the page fetches the release.
  static void catalogueAlbum(BuildContext c, CatalogueAlbum album) =>
      c.push('/${_branch(c)}/catalogue/album/${Uri.encodeComponent(album.id)}',
          extra: album);

  /// A downloaded release by its id (`cat:<catalogue album id>`), with nothing preloaded: the page fetches it.
  static void catalogueAlbumById(BuildContext c, String releaseId) {
    final id =
        releaseId.startsWith('cat:') ? releaseId.substring(4) : releaseId;
    c.push('/${_branch(c)}/catalogue/album/${Uri.encodeComponent(id)}');
  }

  static void catalogueArtist(BuildContext c, String id,
          {CatalogueArtist? preloaded}) =>
      c.push('/${_branch(c)}/catalogue/artist/${Uri.encodeComponent(id)}',
          extra: preloaded);

  static void genre(BuildContext c, String name) =>
      c.push('/${_branch(c)}/genre/${Uri.encodeComponent(name)}');

  static void liked(BuildContext c) => _to(c, (b) => '/$b/liked');

  static void jam(BuildContext c) => c.push('/${_branch(c)}/jam');

  /// What's new: the bell's page.
  static void news(BuildContext c) => c.push('/${_branch(c)}/news');

  /// A genre of the public catalogue (the Browse grid), by its id.
  static void catalogueGenre(BuildContext c, int id, String name) =>
      c.push('/${_branch(c)}/catalogue/genre/$id', extra: name);

  static void yearInMusic(BuildContext c) => c.push('/${_branch(c)}/year');

  static void downloaded(BuildContext c) => c.push('/${_branch(c)}/downloaded');

  static void settings(BuildContext c) => c.push('/settings');
  static void nowPlaying(BuildContext c) => c.push('/player');
  static void lyrics(BuildContext c) => c.push('/lyrics');
}
