import 'package:encore/data/catalogue/catalogue_models.dart';
import 'package:encore/design/theme.dart';
import 'package:encore/design/tokens.dart';
import 'package:encore/features/catalogue/catalogue_widgets.dart';
import 'package:encore/features/instant/instant_play.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/test_app.dart';

/// A song that could not be fetched says why, in full: the owner's screenshot
/// (B42) showed "YouTube is not answering the server right no..." cut off at
/// the edge, which hides the one thing that tells a person whether to try again.
void main() {
  setUpAll(loadAppFonts);

  const track = CatalogueTrack(
    id: 't1',
    title: 'Know My Name',
    artistName: 'League of Legends',
    albumTitle: 'Know My Name',
    duration: Duration(minutes: 3, seconds: 32),
    trackNumber: 1,
  );

  Future<RenderParagraph> subtitleOf(
    WidgetTester tester,
    String text, {
    InstantStatus? status,
  }) async {
    tester.view.physicalSize = const Size(390, 844) * 3;
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      MaterialApp(
        theme:
            buildEncoreTheme(EncoreColors.dark(), brightness: Brightness.dark),
        home: Scaffold(
          body: CatalogueTrackTile(
            track: track,
            isCurrent: false,
            isPlaying: false,
            number: 1,
            status: status,
          ),
        ),
      ),
    );
    return tester.renderObject<RenderParagraph>(find.text(text));
  }

  testWidgets('the whole reason is readable', (tester) async {
    const reason =
        'YouTube is not answering the server right now. Try again later.';

    final paragraph = await subtitleOf(
      tester,
      reason,
      status: const InstantStatus.failed(reason, error: 'blocked'),
    );

    expect(paragraph.didExceedMaxLines, isFalse,
        reason: 'the sentence must fit on the lines the row allows');
  });

  testWidgets('an ordinary row stays on one line', (tester) async {
    final paragraph = await subtitleOf(tester, 'League of Legends');

    expect(paragraph.maxLines, 1);
  });
}
