import 'package:drift/native.dart';
import 'package:encore/core/clock.dart';
import 'package:encore/data/catalogue/catalogue_models.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/repos/cover_fallback_repository.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_catalogue.dart';

CatalogueAlbum album(String artist, String title, {String? cover = 'u'}) =>
    CatalogueAlbum(
      id: '$artist$title',
      title: title,
      artistName: artist,
      coverUrl: cover == null ? null : 'https://img/$cover.jpg',
    );

void main() {
  late AppDatabase db;
  late FakeClock clock;
  late FakeCatalogue catalogue;
  late CoverFallbackRepository repo;

  setUp(() async {
    db = AppDatabase(NativeDatabase.memory());
    clock = FakeClock(DateTime.utc(2026, 10, 15));
    final serverId = await db.into(db.servers).insert(ServersCompanion.insert(
        name: 'T', username: 'u', endpointsJson: '[]', createdAtMs: 0));
    catalogue = FakeCatalogue.withAlbums(
        [album('Opeth', 'Ghost Reveries', cover: 'gr')]);
    repo = CoverFallbackRepository(
      db: db,
      serverId: serverId,
      catalogue: catalogue,
      clock: clock,
      spacing: Duration.zero,
    );
  });

  tearDown(() => db.close());

  test('finds the cover of the exact album', () async {
    expect(await repo.urlFor('Opeth', 'Ghost Reveries'), 'https://img/gr.jpg');
  });

  test('matching ignores case, accents and edition suffixes', () async {
    expect(await repo.urlFor('OPETH', 'ghost reveries (Remastered)'),
        'https://img/gr.jpg');
  });

  test('a hit is remembered: no second lookup', () async {
    await repo.urlFor('Opeth', 'Ghost Reveries');
    await repo.urlFor('Opeth', 'Ghost Reveries');
    expect(catalogue.searches, 1);
  });

  test('concurrent requests for the same album share one lookup', () async {
    final results = await Future.wait([
      repo.urlFor('Opeth', 'Ghost Reveries'),
      repo.urlFor('Opeth', 'Ghost Reveries'),
      repo.urlFor('Opeth', 'Ghost Reveries'),
    ]);
    expect(results.toSet().length, 1);
    expect(catalogue.searches, 1);
  });

  test('a different artist is never accepted', () async {
    catalogue.albums = [album('Tribute Band', 'Ghost Reveries', cover: 'x')];
    expect(await repo.urlFor('Opeth', 'Ghost Reveries'), isNull);
  });

  test('same artist, unrelated title is rejected', () async {
    catalogue.albums = [album('Opeth', 'Blackwater Park', cover: 'bp')];
    expect(await repo.urlFor('Opeth', 'Ghost Reveries'), isNull);
  });

  test('same artist with a longer edition title is accepted', () async {
    catalogue.albums = [
      album('Opeth', 'Ghost Reveries (Legacy Edition Box)', cover: 'ed'),
    ];
    expect(await repo.urlFor('Opeth', 'Ghost Reveries'), 'https://img/ed.jpg');
  });

  test('"not found" is remembered for a week, then retried', () async {
    catalogue.albums = [];
    expect(await repo.urlFor('Nobody', 'Nothing'), isNull);
    expect(await repo.urlFor('Nobody', 'Nothing'), isNull);
    expect(catalogue.searches, 1);

    clock.advance(const Duration(days: 8));
    catalogue.albums = [album('Nobody', 'Nothing', cover: 'n')];
    expect(await repo.urlFor('Nobody', 'Nothing'), 'https://img/n.jpg');
    expect(catalogue.searches, 2);
  });

  test('albums without artwork in the catalogue are skipped', () async {
    catalogue.albums = [album('Opeth', 'Ghost Reveries', cover: null)];
    expect(await repo.urlFor('Opeth', 'Ghost Reveries'), isNull);
  });

  test('empty names do nothing', () async {
    expect(await repo.urlFor('', ''), isNull);
    expect(catalogue.searches, 0);
  });
}
