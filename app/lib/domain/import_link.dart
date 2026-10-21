/// Recognising what a pasted or shared text is when someone wants to bring
/// music over from Spotify or YouTube (ADR-050).
///
/// The download service accepts a Spotify artist link (everything by that
/// artist) or a playlist link (Spotify or YouTube Music; it becomes a playlist
/// and the songs the server lacks are requested). Anything else is explained
/// instead of sent, so a person never waits on a request that cannot work.
library;

enum ImportKind {
  spotifyArtist,
  spotifyPlaylist,
  spotifyAlbum,
  spotifyTrack,
  youtubeMusicPlaylist,
  youtubeMusicArtist,
  youtubePlaylist,
  youtubeVideo,
  unknown,
}

class ImportLink {
  const ImportLink._(this.kind, this.url, this.id);

  final ImportKind kind;

  /// Clean address without tracking parameters (`?si=...`).
  final String url;

  /// Spotify id / YouTube list or channel id.
  final String id;

  /// A playlist link is turned into a playlist (and can be named).
  bool get isPlaylist =>
      kind == ImportKind.spotifyPlaylist ||
      kind == ImportKind.youtubeMusicPlaylist ||
      kind == ImportKind.youtubePlaylist;

  bool get isArtist =>
      kind == ImportKind.spotifyArtist || kind == ImportKind.youtubeMusicArtist;

  /// Can be sent to the download service.
  bool get isSupported => isPlaylist || isArtist;

  /// Its songs can be read into a list (a playlist or a Spotify album).
  bool get isReadable => isPlaylist || kind == ImportKind.spotifyAlbum;

  String get sourceName => switch (kind) {
        ImportKind.spotifyArtist ||
        ImportKind.spotifyPlaylist ||
        ImportKind.spotifyAlbum ||
        ImportKind.spotifyTrack =>
          'Spotify',
        ImportKind.youtubeMusicPlaylist ||
        ImportKind.youtubeMusicArtist =>
          'YouTube Music',
        ImportKind.youtubePlaylist || ImportKind.youtubeVideo => 'YouTube',
        ImportKind.unknown => 'this link',
      };

  /// Why the link cannot be imported, for the page to show; `null` when it can.
  String? get problem => switch (kind) {
        ImportKind.spotifyAlbum =>
          'That is a single album. Search for it by name and tap Request - '
              'or paste the artist or a playlist.',
        ImportKind.spotifyTrack ||
        ImportKind.youtubeVideo =>
          'That is one song. Search for it by name and tap Request - or '
              'paste a playlist or an artist.',
        ImportKind.unknown =>
          'That does not look like a Spotify or YouTube Music playlist or '
              'artist link.',
        _ => null,
      };

  @override
  String toString() => 'ImportLink($kind, $url)';

  // Everything up to whitespace or a quote / angle bracket.
  static final _urlRx =
      RegExp('https?://[^\\s<>"\\x27]+', caseSensitive: false);
  static final _uriRx =
      RegExp(r'spotify:(artist|playlist|album|track):([A-Za-z0-9]+)');
  static final _spotifyPathRx =
      RegExp(r'^/(?:intl-[a-z]{2,5}(?:-[a-z]+)?/)?(?:embed/)?'
          r'(artist|playlist|album|track)/([A-Za-z0-9]+)');

  /// The first importable link in [text] (a "Share" sheet delivers a sentence
  /// with the address inside), or the first link of any kind so the page can
  /// say what is wrong with it. `null` when there is no link at all.
  static ImportLink? parse(String text) {
    final all = parseAll(text);
    return all.isEmpty ? null : all.first;
  }

  /// Every distinct link in [text], importable ones first (in the order they
  /// were written). Lets several be pasted at once: Spotify's desktop app
  /// copies one link per line for a selection of playlists.
  static List<ImportLink> parseAll(String text) {
    final trimmed = text.trim();
    if (trimmed.isEmpty) return const [];
    final candidates = <String>[
      for (final m in _uriRx.allMatches(trimmed))
        'https://open.spotify.com/${m.group(1)}/${m.group(2)}',
      for (final m in _urlRx.allMatches(trimmed))
        m.group(0)!.replaceAll(RegExp(r'[).,;!?]+$'), ''),
    ];
    final seen = <String>{};
    final links = <ImportLink>[];
    for (final raw in candidates) {
      final link = _fromUrl(raw);
      if (link == null || !seen.add(link.url)) continue;
      links.add(link);
    }
    return [
      ...links.where((l) => l.isSupported),
      ...links.where((l) => !l.isSupported),
    ];
  }

  static ImportLink? _fromUrl(String raw) {
    final uri = Uri.tryParse(raw);
    if (uri == null || !uri.hasAuthority) return null;
    final host = uri.host.toLowerCase();

    if (host == 'open.spotify.com' || host == 'play.spotify.com') {
      final m = _spotifyPathRx.firstMatch(uri.path);
      if (m == null) return ImportLink._(ImportKind.unknown, raw, '');
      final type = m.group(1)!;
      final id = m.group(2)!;
      return ImportLink._(
        switch (type) {
          'artist' => ImportKind.spotifyArtist,
          'playlist' => ImportKind.spotifyPlaylist,
          'album' => ImportKind.spotifyAlbum,
          _ => ImportKind.spotifyTrack,
        },
        'https://open.spotify.com/$type/$id',
        id,
      );
    }

    final isYoutube = host == 'youtube.com' ||
        host == 'www.youtube.com' ||
        host == 'm.youtube.com' ||
        host == 'music.youtube.com' ||
        host == 'youtu.be';
    if (isYoutube) {
      final music = host == 'music.youtube.com';
      final list = uri.queryParameters['list'];
      // A song opened from inside a playlist (`/watch?v=..&list=..`) is that playlist.
      if ((uri.path == '/playlist' || uri.path == '/watch') &&
          list != null &&
          list.isNotEmpty) {
        return ImportLink._(
          music ? ImportKind.youtubeMusicPlaylist : ImportKind.youtubePlaylist,
          'https://${music ? 'music' : 'www'}.youtube.com/playlist?list=$list',
          list,
        );
      }
      final channel =
          RegExp(r'^/(?:channel|browse)/([A-Za-z0-9_-]+)').firstMatch(uri.path);
      if (music && channel != null) {
        return ImportLink._(
          ImportKind.youtubeMusicArtist,
          'https://music.youtube.com/channel/${channel.group(1)}',
          channel.group(1)!,
        );
      }
      if (host == 'youtu.be' || uri.path == '/watch') {
        return ImportLink._(ImportKind.youtubeVideo, raw, '');
      }
      return ImportLink._(ImportKind.unknown, raw, '');
    }

    return ImportLink._(ImportKind.unknown, raw, '');
  }
}
