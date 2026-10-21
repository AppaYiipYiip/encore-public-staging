import 'dart:async';

import 'package:encore/data/catalogue/catalogue_models.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/features/detail/album_gap.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import '../support/test_app.dart';

/// The album page of an album the library holds only part of (B39): it says
/// "2 of 5 songs" and lists the rest as songs to play, instead of looking
/// complete.
void main() {
  setUpAll(loadAppFonts);

  const missing = [
    CatalogueTrack(
      id: 'c1',
      title: 'Pigs on the Wing 1',
      artistName: 'Alcest',
      albumTitle: 'Kodama',
      trackNumber: 1,
    ),
    CatalogueTrack(
      id: 'c2',
      title: 'Pigs on the Wing 2',
      artistName: 'Alcest',
      albumTitle: 'Kodama',
      trackNumber: 6,
    ),
  ];

  Future<AppDatabase> open(WidgetTester tester, AlbumGap? gap) async {
    final app = await pumpApp(tester, size: const Size(390, 1800), overrides: [
      albumGapProvider('al1').overrideWith((ref) async => gap),
    ]);
    final element = tester.element(find.byType(Scaffold).first);
    unawaited(GoRouter.of(element).push<void>('/library/album/al1'));
    await settle(tester);
    return app.db;
  }

  testWidgets('says how much of the album is here and lists the rest',
      (tester) async {
    final db = await open(
        tester, const AlbumGap(total: 7, ownedCount: 5, missing: missing));

    expect(find.textContaining('5 of 7 songs'), findsOneWidget);
    expect(find.text('Not in your library'), findsOneWidget);
    expect(find.text('Pigs on the Wing 1'), findsOneWidget);
    expect(find.text('Pigs on the Wing 2'), findsOneWidget);
    await closeApp(tester, db);
  });

  testWidgets('an album that is whole looks as it always did', (tester) async {
    final db = await open(tester, null);

    expect(find.textContaining('5 songs'), findsOneWidget);
    expect(find.textContaining(' of '), findsNothing);
    expect(find.text('Not in your library'), findsNothing);
    await closeApp(tester, db);
  });
}
