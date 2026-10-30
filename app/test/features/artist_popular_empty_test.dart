import 'package:encore/data/catalogue/catalogue_models.dart';
import 'package:encore/design/theme.dart';
import 'package:encore/design/tokens.dart';
import 'package:encore/features/catalogue/artist_sections.dart';
import 'package:encore/features/catalogue/catalogue_providers.dart';
import 'package:encore/features/instant/instant_controller.dart';
import 'package:encore/features/providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/test_app.dart';

/// A small artist has no "popular songs" in the catalogue. The catalogue ANSWERED: that is not "The music catalogue could not be reached"
/// (AUDIT F25, found on a real artist with 4 fans). A real failure still says so, with Try again.
void main() {
  setUpAll(loadAppFonts);

  const artist = CatalogueArtist(id: '411679632', name: 'Beach House');

  Future<void> pumpPopular(
    WidgetTester tester,
    Future<List<CatalogueTrack>> Function() top,
  ) async {
    tester.view.physicalSize = const Size(390, 844) * 3;
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          catalogueArtistTopProvider(artist.id).overrideWith((ref) => top()),
          playbackFacadeProvider.overrideWithValue(FakePlaybackFacade()),
          instantAvailableProvider.overrideWithValue(true),
        ],
        child: MaterialApp(
          theme: buildEncoreTheme(EncoreColors.dark(),
              brightness: Brightness.dark),
          home: const Scaffold(
            body: CustomScrollView(slivers: [
              ArtistPopularSection(artist: artist, sourceId: 'artist:1'),
            ]),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  testWidgets(
      'an artist with no popular songs is told so, not that the catalogue could not be reached',
      (tester) async {
    await pumpPopular(tester, () async => const <CatalogueTrack>[]);

    expect(find.text('No popular songs yet'), findsOneWidget);
    expect(find.textContaining('could not be reached'), findsNothing);
    expect(find.text('Try again'), findsNothing);
  });

  testWidgets('a catalogue that really cannot be reached still says so',
      (tester) async {
    await pumpPopular(tester, () async => throw StateError('no route'));

    expect(find.text('Nothing to show right now'), findsOneWidget);
    expect(
        find.text('The music catalogue could not be reached.'), findsOneWidget);
    expect(find.text('Try again'), findsOneWidget);
  });
}
