import 'dart:convert';

import 'package:drift/drift.dart';

import '../../core/clock.dart';
import '../../core/logger.dart';
import '../../domain/release_alerts.dart';
import '../../domain/text_match.dart';
import '../catalogue/catalogue_models.dart';
import '../db/app_database.dart';
import '../repos/library_repository.dart';
import '../repos/request_repository.dart'
    show LibraryMatcher, RequestRepository;
import '../sync/sync_state_store.dart';

/// One notification to put in the shade.
class AlertNotification {
  const AlertNotification({
    required this.id,
    required this.title,
    required this.body,
    required this.route,
  });

  /// Stable per kind, so a newer one replaces an unread older one.
  final int id;
  final String title;
  final String body;

  /// Where tapping it goes (an in-app location).
  final String route;
}

/// Shows notifications; the phone implementation is in `app/notifications.dart`.
abstract interface class AlertSink {
  Future<void> show(AlertNotification notification);
}

/// Which alerts the person wants (Settings > Get new music).
class AlertSettings {
  const AlertSettings({
    this.onServer = false,
    this.releases = false,
    this.imports = false,
  });

  /// "Songs of an imported playlist arrived" and "what I requested is
  /// here" - the request pipeline's news.
  final bool imports;

  /// "New on your server from artists you play" - local, free.
  final bool onServer;

  /// "New releases you do not have yet" - asks the public catalogue once a
  /// day about the artists played most.
  final bool releases;
}

/// What one pass did (for logs and tests).
class AlertsReport {
  const AlertsReport({
    this.arrivals = 0,
    this.releases = 0,
    this.imports = 0,
    this.requests = 0,
    this.checkedCatalogue = false,
  });

  final int arrivals;
  final int releases;
  final int imports;
  final int requests;
  final bool checkedCatalogue;
}

/// Decides and posts "new music from artists you play" notifications
/// (ADR-051). Runs after the background sync and is safe to run any time:
/// everything it announces is remembered, and the first run only sets the
/// baseline, so enabling it never floods.
class AlertsService {
  AlertsService({
    required AppDatabase db,
    required int serverId,
    required Clock clock,
    required AlertSink sink,
    CatalogueClient? catalogue,
    Future<List<ImportSnapshot>?> Function()? importSnapshots,
    this.releaseEvery = const Duration(hours: 20),
    this.watchedArtists = 15,
    this.minScore = 5,
  })  : _db = db,
        _serverId = serverId,
        _clock = clock,
        _sink = sink,
        _catalogue = catalogue,
        _importSnapshots = importSnapshots,
        _state = SyncStateStore(db, serverId),
        _repo = LibraryRepository(db, serverId);

  static const _kArrivalsSince = 'alerts.arrivalsSinceMs';
  static const _kArrivalsNotified = 'alerts.notifiedAlbums';
  static const _kReleasesChecked = 'alerts.releasesCheckedAtMs';
  static const _kReleasesNotified = 'alerts.notifiedReleases';
  static const _kCatalogueIds = 'alerts.catalogueArtistIds';
  static const _kImportsSeen = 'alerts.importsSeen';

  static const arrivalsNotificationId = 4101;
  static const releasesNotificationId = 4102;
  static const importsNotificationId = 4103;
  static const requestsNotificationId = 4104;

  final AppDatabase _db;
  final int _serverId;
  final Clock _clock;
  final AlertSink _sink;
  final CatalogueClient? _catalogue;

  /// The download service's imports (`null` result = unreachable / none).
  final Future<List<ImportSnapshot>?> Function()? _importSnapshots;
  final SyncStateStore _state;
  final LibraryRepository _repo;

  /// Minimum time between catalogue checks.
  final Duration releaseEvery;

  /// How many of the most played artists are watched for releases.
  final int watchedArtists;

  /// Play score an artist needs before their news is announced (plays + 3 per
  /// liked song + this phone's history; a liked artist counts 10).
  final int minScore;

  Future<AlertsReport> run({
    required AlertSettings settings,
    bool announce = true,
  }) async {
    var arrivals = 0;
    var releases = 0;
    var imports = 0;
    var requests = 0;
    var checked = false;
    try {
      arrivals = await _arrivals(settings, announce);
    } on Object catch (error) {
      Log.warn('alerts', 'arrival check failed', error);
    }
    try {
      imports = await _imports(settings, announce);
    } on Object catch (error) {
      Log.warn('alerts', 'import check failed', error);
    }
    try {
      requests = await _requests(settings, announce);
    } on Object catch (error) {
      Log.warn('alerts', 'request check failed', error);
    }
    try {
      final result = await _releases(settings, announce);
      releases = result.$1;
      checked = result.$2;
    } on Object catch (error) {
      Log.warn('alerts', 'release check failed', error);
    }
    return AlertsReport(
      arrivals: arrivals,
      releases: releases,
      imports: imports,
      requests: requests,
      checkedCatalogue: checked,
    );
  }

  /// The person looked at the app: nothing that arrived so far needs a
  /// notification any more.
  Future<void> markSeen() async {
    await _state.setInt(_kArrivalsSince, _clock.now().millisecondsSinceEpoch);
  }

  // ------------------------------------------------------------- arrivals

  Future<int> _arrivals(AlertSettings settings, bool announce) async {
    final now = _clock.now().millisecondsSinceEpoch;
    final since = await _state.getInt(_kArrivalsSince);
    // First look: remember "now" and say nothing about the past.
    await _state.setInt(_kArrivalsSince, now);
    if (since == null || !settings.onServer) return 0;

    final rows = await (_db.select(_db.albums)
          ..where((a) =>
              a.serverId.equals(_serverId) &
              a.deletedAtMs.isNull() &
              a.artistId.isNotNull() &
              a.createdAtMs.isBiggerThanValue(since))
          ..orderBy([(a) => OrderingTerm.desc(a.createdAtMs)])
          ..limit(300))
        .get();
    if (rows.isEmpty) return 0;

    final top = await _repo.topArtists(limit: 100, minScore: minScore);
    final notified = await _readSet(_kArrivalsNotified);
    final picked = pickArrivals(
      [
        for (final a in rows)
          AlbumArrival(
            albumId: a.id,
            albumName: a.name,
            artistId: a.artistId!,
            artistName: a.artist ?? 'Unknown artist',
            createdAtMs: a.createdAtMs ?? now,
          ),
      ],
      myArtistIds: {for (final t in top) t.id},
      sinceMs: since,
      notified: notified,
    );
    final copy = copyForArrivals(picked);
    if (copy == null) return 0;
    if (announce) {
      await _sink.show(AlertNotification(
        id: arrivalsNotificationId,
        title: copy.title,
        body: copy.body,
        route: copy.route,
      ));
    }
    await _writeSet(_kArrivalsNotified, {...notified, ...copy.ids});
    return picked.length;
  }

  // ------------------------------------------------------------- requests

  /// Requests (Request button, "ask by name") that reached the library.
  /// Resolving also marks them, so the app's own check finds nothing left to
  /// announce when it is opened.
  Future<int> _requests(AlertSettings settings, bool announce) async {
    if (!settings.imports) return 0;
    final arrived = await RequestRepository(_db, _serverId, clock: _clock)
        .resolveAgainstLibrary();
    if (arrived.isEmpty) return 0;

    final matcher = LibraryMatcher(_db, _serverId);
    final arrivals = <RequestArrival>[];
    for (final r in arrived) {
      var route = '/library';
      if (r.album != null) {
        final album = await matcher.findAlbum(r.artist, r.album!);
        if (album != null) {
          route = '/home/album/${Uri.encodeComponent(album.id)}';
        }
      } else {
        final artist = await matcher.findArtist(r.artist);
        if (artist != null) {
          route = '/home/artist/${Uri.encodeComponent(artist.id)}';
        }
      }
      arrivals
          .add(RequestArrival(artist: r.artist, album: r.album, route: route));
    }
    final copy = copyForRequests(arrivals);
    if (copy != null && announce) {
      await _sink.show(AlertNotification(
        id: requestsNotificationId,
        title: copy.title,
        body: copy.body,
        route: copy.route,
      ));
    }
    return arrivals.length;
  }

  // -------------------------------------------------------------- imports

  Future<int> _imports(AlertSettings settings, bool announce) async {
    final source = _importSnapshots;
    if (!settings.imports || source == null) return 0;
    final current = await source();
    if (current == null) return 0; // unreachable: look again next time

    final seen = {
      for (final e in (await _readMap(_kImportsSeen)).entries)
        e.key: int.tryParse(e.value) ?? 0,
    };
    final updates = pickImportUpdates(current, seen: seen);
    final copy = copyForImports(updates);
    if (copy != null && announce) {
      await _sink.show(AlertNotification(
        id: importsNotificationId,
        title: copy.title,
        body: copy.body,
        route: copy.route,
      ));
    }
    // Remember where every import stands; a name seen for the first time is
    // only recorded.
    await _writeMap(_kImportsSeen, {
      for (final s in current) s.name: '${s.inLibrary}',
    });
    return updates.length;
  }

  // ------------------------------------------------------------- releases

  Future<(int, bool)> _releases(AlertSettings settings, bool announce) async {
    final catalogue = _catalogue;
    if (!settings.releases || catalogue == null) return (0, false);
    final now = _clock.now();
    final last = await _state.getInt(_kReleasesChecked);
    if (last != null &&
        now.millisecondsSinceEpoch - last < releaseEvery.inMilliseconds) {
      return (0, false);
    }

    final top =
        await _repo.topArtists(limit: watchedArtists, minScore: minScore);
    if (top.isEmpty) {
      await _state.setInt(_kReleasesChecked, now.millisecondsSinceEpoch);
      return (0, false);
    }

    final ids = await _readMap(_kCatalogueIds);
    final found = <ReleaseCandidate>[];
    var reached = false;
    for (final artist in top) {
      var catalogueId = ids[artist.id];
      if (catalogueId == null) {
        final results = await catalogue.search(artist.name, limit: 1);
        // Nothing at all: offline or the catalogue is down - ask again next
        // time instead of remembering "not found".
        if (results.isEmpty) continue;
        reached = true;
        final want = normalizeForMatch(artist.name);
        CatalogueArtist? hit;
        for (final c in results.artists) {
          if (normalizeForMatch(c.name) == want) {
            hit = c;
            break;
          }
        }
        // '' = the catalogue answered but has no such artist; not asked again.
        catalogueId = hit?.id ?? '';
        ids[artist.id] = catalogueId;
      }
      if (catalogueId.isEmpty) continue;
      final albums = await catalogue.artistAlbums(catalogueId,
          artistName: artist.name, limit: 25);
      reached = reached || albums.isNotEmpty;
      for (final a in albums) {
        found.add(ReleaseCandidate(
          catalogueAlbumId: a.id,
          title: a.title,
          artistName: a.artistName,
          artistKey: artist.id,
          releaseDate: a.releaseDate,
          kind: a.recordType,
        ));
      }
    }
    await _writeMap(_kCatalogueIds, ids);
    // Offline or the catalogue is down: try again at the next opportunity.
    if (!reached) return (0, false);

    final matcher = LibraryMatcher(_db, _serverId);
    final notified = await _readSet(_kReleasesNotified);
    final owned = <String>{};
    for (final r in found) {
      if (await matcher.hasAlbum(r.artistName, r.title)) {
        owned.add(r.catalogueAlbumId);
      }
    }
    final picked = pickReleases(
      found,
      today: now,
      notified: notified,
      owned: (r) => owned.contains(r.catalogueAlbumId),
    );
    await _state.setInt(_kReleasesChecked, now.millisecondsSinceEpoch);

    // The very first check only learns what is already out.
    final firstTime = last == null;
    final copy = copyForReleases(picked);
    if (copy != null && announce && !firstTime) {
      await _sink.show(AlertNotification(
        id: releasesNotificationId,
        title: copy.title,
        body: copy.body,
        route: copy.route,
      ));
    }
    if (copy != null) {
      await _writeSet(_kReleasesNotified, {...notified, ...copy.ids});
    }
    return (firstTime ? 0 : picked.length, true);
  }

  // -------------------------------------------------------------- storage

  Future<Set<String>> _readSet(String key) async {
    final raw = await _state.get(key);
    if (raw == null) return <String>{};
    try {
      final decoded = jsonDecode(raw);
      if (decoded is List) return {for (final v in decoded) '$v'};
    } on FormatException {
      // Rewritten below.
    }
    return <String>{};
  }

  /// Keeps the most recent [cap] ids so the record cannot grow without end.
  Future<void> _writeSet(String key, Set<String> value, {int cap = 400}) {
    final list = value.toList();
    final kept = list.length > cap ? list.sublist(list.length - cap) : list;
    return _state.set(key, jsonEncode(kept));
  }

  Future<Map<String, String>> _readMap(String key) async {
    final raw = await _state.get(key);
    if (raw == null) return <String, String>{};
    try {
      final decoded = jsonDecode(raw);
      if (decoded is Map) {
        return {for (final e in decoded.entries) '${e.key}': '${e.value}'};
      }
    } on FormatException {
      // Rewritten below.
    }
    return <String, String>{};
  }

  Future<void> _writeMap(String key, Map<String, String> value) =>
      _state.set(key, jsonEncode(value));
}
