import 'dart:ui' show Color;

import 'package:drift/drift.dart' show BooleanExpressionOperators, Value;
import 'package:drift/native.dart';
import 'package:encore/app/providers.dart';
import 'package:encore/core/cover_sizes.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/features/common/artwork_color.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/test_app.dart';

void main() {
  late AppDatabase db;
  late int serverId;
  late List<({String url, String cacheKey})> extracted;
  Color? swatch;

  ProviderContainer container() => ProviderContainer(
        retry: (_, __) => null,
        overrides: [
          databaseProvider.overrideWithValue(db),
          activeServerIdProvider.overrideWith((ref) => Stream.value(serverId)),
          coverArtResolverProvider
              .overrideWithValue(CoverArtResolver(serverId: serverId)),
          swatchExtractorProvider.overrideWithValue((url, cacheKey) async {
            extracted.add((url: url, cacheKey: cacheKey));
            return swatch;
          }),
        ],
      );

  /// Riverpod 3 pauses providers nobody listens to, so a bare `read` of an
  /// auto-dispose provider never completes; listening keeps it alive.
  Future<Color?> swatchOf(ProviderContainer c, ArtworkKey key) {
    c.listen(artworkSwatchProvider(key), (_, __) {});
    return c.read(artworkSwatchProvider(key).future);
  }

  setUp(() async {
    db = AppDatabase(NativeDatabase.memory());
    serverId = await Seed.library(db);
    extracted = [];
    swatch = const Color(0xFF336699);
  });

  tearDown(() => db.close());

  Future<int?> storedColor(String albumId) async {
    final row = await (db.select(db.albums)
          ..where((a) => a.serverId.equals(serverId) & a.id.equals(albumId)))
        .getSingle();
    return row.dominantColor;
  }

  test('a cover is analysed once, remembered on the album and reused',
      () async {
    final c = container();
    addTearDown(c.dispose);
    const key = (albumId: 'al3', coverArtId: 'mf-song-1');

    final first = await swatchOf(c, key);
    expect(first, const Color(0xFF336699));
    expect(extracted, hasLength(1));
    expect(extracted.single.cacheKey,
        CoverSize.key(serverId, 'mf-song-1', CoverSize.small),
        reason: 'same cache entry the cover widgets use, no new download');

    await pumpEventQueue();
    expect(await storedColor('al3'), const Color(0xFF336699).toARGB32());

    // A new session (fresh container): read back from the database.
    final c2 = container();
    addTearDown(c2.dispose);
    final second = await swatchOf(c2, key);
    expect(second, const Color(0xFF336699));
    expect(extracted, hasLength(1), reason: 'no second analysis');
  });

  test('a colour already on the album needs no image at all', () async {
    await (db.update(db.albums)..where((a) => a.id.equals('al1')))
        .write(const AlbumsCompanion(dominantColor: Value(0xFFAA3355)));
    final c = container();
    addTearDown(c.dispose);

    final result = await swatchOf(c, (albumId: 'al1', coverArtId: null));
    expect(result, const Color(0xFFAA3355));
    expect(extracted, isEmpty);
  });

  test('an unreadable cover yields null and stores nothing', () async {
    swatch = null;
    final c = container();
    addTearDown(c.dispose);

    final result = await swatchOf(c, (albumId: 'al2', coverArtId: null));
    expect(result, isNull);
    expect(await storedColor('al2'), isNull);
  });

  test('an item without any cover is simply colourless', () async {
    final c = container();
    addTearDown(c.dispose);
    final result = await swatchOf(c, (albumId: null, coverArtId: null));
    expect(result, isNull);
    expect(extracted, isEmpty);
  });

  test('a cover without an album row is analysed but cannot be stored',
      () async {
    final c = container();
    addTearDown(c.dispose);
    final result = await swatchOf(c, (albumId: null, coverArtId: 'pl-cover'));
    expect(result, const Color(0xFF336699));
    expect(extracted, hasLength(1));
  });
}
