import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:drift/native.dart';
import 'package:encore/core/clock.dart';
import 'package:encore/data/alerts/alerts_service.dart';
import 'package:encore/data/catalogue/catalogue_models.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/domain/release_alerts.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_catalogue.dart';

class _Sink implements AlertSink {
  final List<AlertNotification> shown = [];

  @override
  Future<void> show(AlertNotification notification) async =>
      shown.add(notification);
}

/// ADR-051: notifications are about artists the person plays, never repeat,
/// and enabling them never floods.
void main() {
  late AppDatabase db;
  late int serverId;
  late FakeClock clock;
  late _Sink sink;
  late FakeCatalogue catalogue;
  List<ImportSnapshot>? imports;

  const all = AlertSettings();

  AlertsService service({bool withCatalogue = true}) => AlertsService(
        db: db,
        serverId: serverId,
        clock: clock,
        sink: sink,
        catalogue: withCatalogue ? catalogue : null,
        importSnapshots: () async => imports,
      );

  setUp(() async {
    db = AppDatabase(NativeDatabase.memory());
    serverId = await db.into(db.servers).insert(ServersCompanion.insert(
          name: 'Home',
          username: 'marwa',
          endpointsJson: '[]',
          createdAtMs: 0,
        ));
    clock = FakeClock(DateTime.utc(2026, 10, 15, 12));
    sink = _Sink();
    catalogue = FakeCatalogue();
    imports = null;

    // A played artist (score 40) and one nobody plays.
    await db.into(db.artists).insert(ArtistsCompanion.insert(
        serverId: serverId, id: 'ar-alcest', name: 'Alcest'));
    await db.into(db.artists).insert(ArtistsCompanion.insert(
        serverId: serverId, id: 'ar-other', name: 'Strangers'));
    await db.into(db.tracks).insert(TracksCompanion.insert(
          serverId: serverId,
          id: 't-alcest',
          title: 'Old song',
          artistId: const Value('ar-alcest'),
          playCount: const Value(40),
        ));
    await db.into(db.tracks).insert(TracksCompanion.insert(
          serverId: serverId,
          id: 't-other',
          title: 'Someone else\'s',
          artistId: const Value('ar-other'),
          playCount: const Value(0),
        ));
  });

  tearDown(() => db.close());

  Future<void> addAlbum(String id, String artistId, String artist,
      {String? name, DateTime? created}) async {
    await db.into(db.albums).insert(AlbumsCompanion.insert(
          serverId: serverId,
          id: id,
          name: name ?? 'Album $id',
          artistId: Value(artistId),
          artist: Value(artist),
          createdAtMs: Value((created ?? clock.now()).millisecondsSinceEpoch),
        ));
  }

  group('arrivals', () {
    test('the first look only sets the baseline', () async {
      await addAlbum('old', 'ar-alcest', 'Alcest');

      final report = await service().run(settings: all);

      expect(report.arrivals, 0);
      expect(sink.shown, isEmpty);
    });

    test('an album by an artist I play is announced once', () async {
      await service().run(settings: all); // baseline
      clock.advance(const Duration(hours: 3));
      await addAlbum('fresh', 'ar-alcest', 'Alcest', name: 'Les Chants');

      final first = await service().run(settings: all);
      final second = await service().run(settings: all);

      expect(first.arrivals, 1);
      expect(sink.shown.single.title, 'New from Alcest');
      expect(sink.shown.single.body, 'Les Chants is on your server now.');
      expect(sink.shown.single.route, '/home/album/fresh');
      expect(second.arrivals, 0);
      expect(sink.shown.length, 1);
    });

    test('an album by an artist nobody here plays is ignored', () async {
      await service().run(settings: all);
      clock.advance(const Duration(hours: 3));
      await addAlbum('noise', 'ar-other', 'Strangers');

      final report = await service().run(settings: all);

      expect(report.arrivals, 0);
      expect(sink.shown, isEmpty);
    });

    test('switched off: nothing shown, and turning it on later is quiet',
        () async {
      await service().run(settings: all);
      clock.advance(const Duration(hours: 3));
      await addAlbum('missed', 'ar-alcest', 'Alcest');

      await service().run(settings: const AlertSettings(onServer: false));
      clock.advance(const Duration(hours: 1));
      await service().run(settings: all);

      expect(sink.shown, isEmpty);
    });

    test('markSeen: what arrived while the app was open is not announced',
        () async {
      await service().run(settings: all);
      clock.advance(const Duration(hours: 3));
      await addAlbum('seen', 'ar-alcest', 'Alcest');
      await service().markSeen();

      await service().run(settings: all);

      expect(sink.shown, isEmpty);
    });

    test('announce: false records without notifying', () async {
      await service().run(settings: all);
      clock.advance(const Duration(hours: 3));
      await addAlbum('quiet', 'ar-alcest', 'Alcest');

      await service().run(settings: all, announce: false);
      await service().run(settings: all);

      expect(sink.shown, isEmpty);
    });
  });

  group('releases', () {
    CatalogueAlbum release(String id, String title, String date) =>
        CatalogueAlbum(
          id: id,
          title: title,
          artistName: 'Alcest',
          artistId: 'dz-1',
          releaseDate: date,
          recordType: 'album',
        );

    setUp(() {
      catalogue.results = const CatalogueResults(
        artists: [CatalogueArtist(id: 'dz-1', name: 'Alcest')],
      );
    });

    test('the first check learns what is out without announcing it', () async {
      catalogue.albumsByArtist['dz-1'] = [
        release('r1', 'Already Out', '2026-10-01'),
      ];

      final report = await service().run(settings: all);

      expect(report.checkedCatalogue, isTrue);
      expect(report.releases, 0);
      expect(sink.shown, isEmpty);
    });

    test('a later release is announced with a way to request it', () async {
      catalogue.albumsByArtist['dz-1'] = [];
      await service().run(settings: all); // first check
      clock.advance(const Duration(hours: 21));
      catalogue.albumsByArtist['dz-1'] = [
        release('r2', 'Kodama', '2026-10-15'),
      ];

      final report = await service().run(settings: all);

      expect(report.releases, 1);
      final n = sink.shown.single;
      expect(n.title, 'Alcest has new music');
      expect(n.body, contains('Kodama'));
      expect(n.route, '/home/catalogue/album/r2');
    });

    test('an album the server already has is not announced', () async {
      catalogue.albumsByArtist['dz-1'] = [];
      await service().run(settings: all);
      clock.advance(const Duration(hours: 21));
      await addAlbum('have', 'ar-alcest', 'Alcest', name: 'Kodama');
      catalogue.albumsByArtist['dz-1'] = [
        release('r2', 'Kodama', '2026-10-15'),
      ];

      final report = await service().run(settings: all);

      expect(report.releases, 0);
      expect(sink.shown.where((n) => n.id == 4102), isEmpty);
    });

    test('asks the catalogue at most once a day', () async {
      catalogue.albumsByArtist['dz-1'] = [];
      await service().run(settings: all);
      final lookups = catalogue.lookups.length;
      clock.advance(const Duration(hours: 2));

      final report = await service().run(settings: all);

      expect(report.checkedCatalogue, isFalse);
      expect(catalogue.lookups.length, lookups);
    });

    test('an unreachable catalogue is retried, not recorded as checked',
        () async {
      catalogue.results = CatalogueResults.empty;

      final first = await service().run(settings: all);
      catalogue.results = const CatalogueResults(
        artists: [CatalogueArtist(id: 'dz-1', name: 'Alcest')],
      );
      catalogue.albumsByArtist['dz-1'] = [
        release('r1', 'Out', '2026-10-01'),
      ];
      final second = await service().run(settings: all);

      expect(first.checkedCatalogue, isFalse);
      expect(second.checkedCatalogue, isTrue);
    });

    test('off: the catalogue is never asked', () async {
      await service().run(settings: const AlertSettings(releases: false));

      expect(catalogue.lookups, isEmpty);
      expect(catalogue.queries, isEmpty);
    });
  });

  group('requests', () {
    test('a request that reached the library is announced and resolved',
        () async {
      await db.into(db.requests).insert(RequestsCompanion.insert(
            serverId: serverId,
            kind: 'album',
            title: 'Kodama',
            artist: 'Alcest',
            album: const Value('Kodama'),
            state: 'requested',
            createdAtMs: 0,
            updatedAtMs: 0,
          ));
      await addAlbum('al-kodama', 'ar-alcest', 'Alcest', name: 'Kodama');

      final report = await service().run(settings: all);

      expect(report.requests, 1);
      final n = sink.shown.firstWhere((n) => n.id == 4104);
      expect(n.title, 'Your request arrived');
      expect(n.body, '"Kodama" by Alcest is in your library now.');
      expect(n.route, '/home/album/al-kodama');

      final again = await service().run(settings: all);
      expect(again.requests, 0, reason: 'announced once');
    });

    test('with the switch off the request is left for the app to resolve',
        () async {
      await db.into(db.requests).insert(RequestsCompanion.insert(
            serverId: serverId,
            kind: 'artist',
            title: 'Alcest',
            artist: 'Alcest',
            state: 'requested',
            createdAtMs: 0,
            updatedAtMs: 0,
          ));
      await addAlbum('al1', 'ar-alcest', 'Alcest');

      final report =
          await service().run(settings: const AlertSettings(imports: false));

      expect(report.requests, 0);
      final row = await db.select(db.requests).getSingle();
      expect(row.state, 'requested');
    });
  });

  group('imports', () {
    test('first look records, later progress is announced', () async {
      imports = [
        const ImportSnapshot(name: 'Road trip', tracks: 50, inLibrary: 20),
      ];
      await service().run(settings: all);
      expect(sink.shown, isEmpty);

      imports = [
        const ImportSnapshot(name: 'Road trip', tracks: 50, inLibrary: 32),
      ];
      final report = await service().run(settings: all);

      expect(report.imports, 1);
      expect(sink.shown.single.title, '"Road trip" is filling up');
      expect(sink.shown.single.route, '/settings/import');
    });

    test('finishing is announced as complete', () async {
      imports = [
        const ImportSnapshot(name: 'Road trip', tracks: 50, inLibrary: 47),
      ];
      await service().run(settings: all);
      imports = [
        const ImportSnapshot(name: 'Road trip', tracks: 50, inLibrary: 50),
      ];

      await service().run(settings: all);

      expect(sink.shown.single.title, '"Road trip" is complete');
    });

    test('a portal that cannot be reached changes nothing', () async {
      imports = [
        const ImportSnapshot(name: 'Road trip', tracks: 50, inLibrary: 20),
      ];
      await service().run(settings: all);
      imports = null;

      final report = await service().run(settings: all);

      expect(report.imports, 0);
      expect(sink.shown, isEmpty);
    });
  });
}
