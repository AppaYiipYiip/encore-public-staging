/// What is worth a notification, and what to say (ADR-051).
///
/// Two kinds of news, both about artists the person actually plays:
///
/// * **Arrivals** - an album that reached *this server* since the last look
///   (the request pipeline, an import, someone adding music). Local only.
/// * **Releases** - an album the public catalogue lists as released in the
///   last weeks that the server does not have yet. Offers a Request.
///
/// Pure functions: no database, no network, no clock of their own, so every
/// rule is a unit test.
library;

/// An album that appeared on the server.
class AlbumArrival {
  const AlbumArrival({
    required this.albumId,
    required this.albumName,
    required this.artistId,
    required this.artistName,
    required this.createdAtMs,
  });

  final String albumId;
  final String albumName;
  final String artistId;
  final String artistName;

  /// When the server first saw it.
  final int createdAtMs;
}

/// A release listed by the public catalogue.
class ReleaseCandidate {
  const ReleaseCandidate({
    required this.catalogueAlbumId,
    required this.title,
    required this.artistName,
    this.artistKey,
    this.releaseDate,
    this.kind,
  });

  final String catalogueAlbumId;
  final String title;
  final String artistName;

  /// Our own id of the artist this was found for (to count per artist).
  final String? artistKey;

  /// `yyyy-MM-dd` as the catalogue gives it.
  final String? releaseDate;

  /// `album` | `ep` | `single` | `compile`.
  final String? kind;

  DateTime? get releasedOn {
    final d = releaseDate;
    if (d == null) return null;
    final parsed = DateTime.tryParse(d);
    return parsed == null
        ? null
        : DateTime.utc(parsed.year, parsed.month, parsed.day);
  }

  String get noun => switch (kind) {
        'single' => 'single',
        'ep' => 'EP',
        _ => 'album',
      };
}

/// A notification's words and where tapping it goes.
class AlertCopy {
  const AlertCopy({
    required this.title,
    required this.body,
    required this.route,
    required this.ids,
  });

  final String title;
  final String body;

  /// An in-app location (`/home/album/..`).
  final String route;

  /// Everything this notification stands for, so it is never announced again.
  final List<String> ids;
}

/// Arrivals worth announcing: newer than [sinceMs], by an artist the person
/// plays, not announced before. Newest first, at most [max].
List<AlbumArrival> pickArrivals(
  Iterable<AlbumArrival> recent, {
  required Set<String> myArtistIds,
  required int sinceMs,
  required Set<String> notified,
  int max = 12,
}) {
  final out = [
    for (final a in recent)
      if (a.createdAtMs > sinceMs &&
          myArtistIds.contains(a.artistId) &&
          !notified.contains(a.albumId))
        a,
  ]..sort((a, b) => b.createdAtMs.compareTo(a.createdAtMs));
  return out.take(max).toList();
}

/// Releases worth announcing: dated within [window] before [today] (never in
/// the future - a pre-release is announced on its day), not owned, not
/// announced before, one per artist+title. Newest first, at most [max].
List<ReleaseCandidate> pickReleases(
  Iterable<ReleaseCandidate> found, {
  required DateTime today,
  required Set<String> notified,
  required bool Function(ReleaseCandidate) owned,
  Duration window = const Duration(days: 30),
  int max = 8,
}) {
  final day = DateTime.utc(today.year, today.month, today.day);
  final oldest = day.subtract(window);
  final seen = <String>{};
  final out = <ReleaseCandidate>[];
  for (final r in found) {
    final on = r.releasedOn;
    if (on == null || on.isAfter(day) || on.isBefore(oldest)) continue;
    if (notified.contains(r.catalogueAlbumId)) continue;
    final key = '${r.artistName}|${r.title}'.toLowerCase();
    if (!seen.add(key)) continue;
    if (owned(r)) continue;
    out.add(r);
  }
  out.sort((a, b) => b.releasedOn!.compareTo(a.releasedOn!));
  return out.take(max).toList();
}

String _list(List<String> names) {
  if (names.length <= 2) return names.join(' and ');
  return '${names[0]}, ${names[1]} and ${names.length - 2} more';
}

/// Words for [arrivals] (already picked), or `null` for none.
AlertCopy? copyForArrivals(List<AlbumArrival> arrivals) {
  if (arrivals.isEmpty) return null;
  final ids = [for (final a in arrivals) a.albumId];
  final artists = <String, String>{};
  for (final a in arrivals) {
    artists.putIfAbsent(a.artistId, () => a.artistName);
  }
  if (arrivals.length == 1) {
    final a = arrivals.single;
    return AlertCopy(
      title: 'New from ${a.artistName}',
      body: '${a.albumName} is on your server now.',
      route: '/home/album/${Uri.encodeComponent(a.albumId)}',
      ids: ids,
    );
  }
  if (artists.length == 1) {
    final a = arrivals.first;
    return AlertCopy(
      title: 'New from ${a.artistName}',
      body: '${arrivals.length} new albums are on your server.',
      route: '/home/artist/${Uri.encodeComponent(a.artistId)}',
      ids: ids,
    );
  }
  return AlertCopy(
    title: 'New music from artists you play',
    body: '${_list(artists.values.toList())} - on your server now.',
    route: '/home',
    ids: ids,
  );
}

/// Words for [releases] (already picked), or `null` for none.
AlertCopy? copyForReleases(List<ReleaseCandidate> releases) {
  if (releases.isEmpty) return null;
  final ids = [for (final r in releases) r.catalogueAlbumId];
  if (releases.length == 1) {
    final r = releases.single;
    return AlertCopy(
      title: '${r.artistName} has new music',
      body: '"${r.title}" (${r.noun}) is out and not on your server yet. '
          'Tap to see it and request it.',
      route: '/home/catalogue/album/${Uri.encodeComponent(r.catalogueAlbumId)}',
      ids: ids,
    );
  }
  final artists = <String>{for (final r in releases) r.artistName}.toList();
  return AlertCopy(
    title: 'New releases from artists you play',
    body: '${_list(artists)} - not on your server yet.',
    // The newest one; its page shows the artist's other releases too.
    route: '/home/catalogue/album/'
        '${Uri.encodeComponent(releases.first.catalogueAlbumId)}',
    ids: ids,
  );
}

// ------------------------------------------------------------------ imports

/// How far an imported playlist has got, as the download service reports it.
class ImportSnapshot {
  const ImportSnapshot({
    required this.name,
    required this.tracks,
    required this.inLibrary,
  });

  final String name;

  /// Songs in the source playlist (0 while it is still being read).
  final int tracks;

  /// Of those, how many the server has.
  final int inLibrary;

  bool get complete => tracks > 0 && inLibrary >= tracks;
}

/// An import that moved enough to mention.
class ImportUpdate {
  const ImportUpdate({
    required this.snapshot,
    required this.gained,
    required this.finished,
  });

  final ImportSnapshot snapshot;
  final int gained;
  final bool finished;
}

/// Imports worth a mention: finished since the last look, or gained at least
/// [minGain] songs (and a tenth of the playlist, so a 2,000-song import does
/// not ping for every album). [seen] maps a name to the `inLibrary` count last
/// announced; a name not in it is only recorded, never announced - the first
/// look is the baseline.
List<ImportUpdate> pickImportUpdates(
  Iterable<ImportSnapshot> current, {
  required Map<String, int> seen,
  int minGain = 5,
}) {
  final out = <ImportUpdate>[];
  for (final s in current) {
    final before = seen[s.name];
    if (before == null) continue;
    final gained = s.inLibrary - before;
    if (gained <= 0) continue;
    final wasComplete = s.tracks > 0 && before >= s.tracks;
    final finished = s.complete && !wasComplete;
    final enough = gained >= minGain && gained * 10 >= s.tracks;
    if (finished || enough) {
      out.add(ImportUpdate(snapshot: s, gained: gained, finished: finished));
    }
  }
  return out;
}

/// Words for [updates], or `null` for none. Tapping opens the import page.
AlertCopy? copyForImports(List<ImportUpdate> updates) {
  if (updates.isEmpty) return null;
  final ids = [for (final u in updates) 'import:${u.snapshot.name}'];
  if (updates.length == 1) {
    final u = updates.single;
    final s = u.snapshot;
    return AlertCopy(
      title:
          u.finished ? '"${s.name}" is complete' : '"${s.name}" is filling up',
      body: u.finished
          ? (s.tracks == 1
              ? 'The song is on your server now.'
              : 'All ${s.tracks} songs are on your server now.')
          : '${u.gained} more ${u.gained == 1 ? 'song' : 'songs'} arrived '
              '- ${s.inLibrary} of ${s.tracks} are on your server.',
      route: '/settings/import',
      ids: ids,
    );
  }
  final names = [for (final u in updates) u.snapshot.name];
  return AlertCopy(
    title: 'Your imports are filling up',
    body: '${_list(names)} - more songs arrived.',
    route: '/settings/import',
    ids: ids,
  );
}

// ----------------------------------------------------------------- requests

/// Something the person asked for (Request button, "ask by name") that has
/// reached the library.
class RequestArrival {
  const RequestArrival({
    required this.artist,
    this.album,
    required this.route,
  });

  final String artist;

  /// `null` for "everything by this artist".
  final String? album;

  /// Where it can be opened.
  final String route;

  String get title => album ?? artist;
}

/// Words for [arrivals], or `null` for none.
AlertCopy? copyForRequests(List<RequestArrival> arrivals) {
  if (arrivals.isEmpty) return null;
  final ids = [
    for (final a in arrivals) 'request:${a.artist}|${a.album ?? ''}',
  ];
  if (arrivals.length == 1) {
    final a = arrivals.single;
    return AlertCopy(
      title: 'Your request arrived',
      body: a.album == null
          ? '${a.artist} is in your library now.'
          : '"${a.album}" by ${a.artist} is in your library now.',
      route: a.route,
      ids: ids,
    );
  }
  return AlertCopy(
    title: '${arrivals.length} requests arrived',
    body:
        '${_list([for (final a in arrivals) a.title])} - in your library now.',
    route: '/library',
    ids: ids,
  );
}
