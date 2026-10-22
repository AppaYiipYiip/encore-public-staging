import 'package:encore/app/providers.dart';
import 'package:encore/features/providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import '../support/test_app.dart';

/// P1-09: without a connection the songs that are not on the phone cannot play: their rows are greyed and say so, the ones that are
/// downloaded look as usual. (The player itself never tries the others and never skips: playback_engine_test.)
void main() {
  setUpAll(loadAppFonts);

  Future<void> open(WidgetTester tester, String location) async {
    final element = tester.element(find.byType(Scaffold).first);
    GoRouter.of(element).go(location);
    await settle(tester);
  }

  testWidgets('offline, an album shows which songs cannot be played',
      (tester) async {
    final app = await pumpApp(tester, overrides: [
      networkKindProvider.overrideWith((ref) => Stream.value(NetworkKind.none)),
      downloadedIdsProvider.overrideWith((ref) => Stream.value({'al1-t2'})),
    ]);
    await open(tester, '/home/album/al1');

    // Five songs, one of them on the phone.
    expect(find.byIcon(Icons.cloud_off_rounded), findsNWidgets(4));
    await closeApp(tester, app.db);
  });

  testWidgets('online, every row looks as usual', (tester) async {
    final app = await pumpApp(tester, overrides: [
      networkKindProvider.overrideWith((ref) => Stream.value(NetworkKind.wifi)),
      downloadedIdsProvider.overrideWith((ref) => Stream.value(<String>{})),
    ]);
    await open(tester, '/home/album/al1');

    expect(find.byIcon(Icons.cloud_off_rounded), findsNothing);
    await closeApp(tester, app.db);
  });

  testWidgets('offline, a search result that is not downloaded is greyed too',
      (tester) async {
    final app = await pumpApp(tester, overrides: [
      networkKindProvider.overrideWith((ref) => Stream.value(NetworkKind.none)),
      downloadedIdsProvider.overrideWith((ref) => Stream.value(<String>{})),
    ]);
    await tester.tap(find.text('Search').last);
    await settle(tester);
    await tester.enterText(find.byType(TextField), 'Opening Kodama');
    await tester.pump(const Duration(milliseconds: 600));
    await settle(tester);

    expect(find.byIcon(Icons.cloud_off_rounded), findsWidgets);
    await closeApp(tester, app.db);
  });
}
