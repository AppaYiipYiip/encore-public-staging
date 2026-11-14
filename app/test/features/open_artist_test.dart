import 'dart:async';

import 'package:encore/app/providers.dart';
import 'package:encore/data/catalogue/catalogue_models.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/repos/request_repository.dart';
import 'package:encore/features/catalogue/catalogue_providers.dart';
import 'package:encore/features/common/open_artist.dart';
import 'package:encore/features/requests/request_providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fake_catalogue.dart';
import '../support/test_app.dart';

/// A library lookup that waits for the test (a slow database on a busy phone).
class _GatedMatcher extends LibraryMatcher {
  _GatedMatcher(super.db, super.serverId, this.gate);

  final Completer<void> gate;

  @override
  Future<ArtistRow?> findArtist(String name) async {
    await gate.future;
    return super.findArtist(name);
  }
}

/// N-12 (advisor, 14 Nov 2026): `openArtistByName` read the catalogue provider AFTER its first `await`. From a menu the sheet can be swiped
/// away while the lookup runs; the sheet's `ref` is then dead, the read threw inside the lookup's own try, and the person got a false
/// "Could not find ..." for an artist that exists. Both providers are read before the first `await`, whoever calls.
void main() {
  setUpAll(loadAppFonts);

  testWidgets(
      'a lookup still running when the sheet that asked is swiped away still opens the artist',
      (tester) async {
    final gate = Completer<void>();
    final catalogue = FakeCatalogue(const CatalogueResults(artists: [
      CatalogueArtist(id: '77', name: 'Nobody Special', fans: 1000),
    ]));
    final app = await pumpApp(tester, overrides: [
      catalogueClientProvider.overrideWithValue(catalogue),
      libraryMatcherProvider.overrideWith((ref) => _GatedMatcher(
          ref.watch(databaseProvider),
          ref.watch(activeServerIdProvider).value ?? 1,
          gate)),
    ]);
    final parent = tester.element(find.byType(Scaffold).first);
    WidgetRef? sheetRef;
    BuildContext? sheetContext;
    unawaited(showModalBottomSheet<void>(
      context: parent,
      builder: (_) => Consumer(builder: (context, ref, _) {
        sheetRef = ref;
        sheetContext = context;
        return const SizedBox(height: 120, child: Text('the sheet'));
      }),
    ));
    await settle(tester);
    expect(find.text('the sheet'), findsOneWidget);
    var opened = false;

    final result = openArtistByName(parent, sheetRef!, 'Nobody Special',
        beforeOpen: () => opened = true);
    Navigator.of(sheetContext!).pop(); // swiped away while the lookup runs
    await settle(tester);
    expect(find.text('the sheet'), findsNothing);
    gate.complete();
    final found = await result;
    await settle(tester);

    expect(found, isTrue, reason: 'the artist exists: no false "not found"');
    expect(opened, isTrue);
    expect(find.text('Could not find Nobody Special.'), findsNothing);

    await closeApp(tester, app.db);
  });
}
