import 'package:encore/data/db/app_database.dart';
import 'package:encore/features/jam/jam_providers.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_jam_api.dart';
import '../../support/test_app.dart';

/// AUDIT F50 / D-33: Home's "Jam" chip led to a page that only said "Your server does not have Jam yet". Jam on the Encore server is not built, so a
/// fresh install met that dead end at once. Home offers Jam only where the server has the hub, and the page and the chip read the same answer
/// (`jamApiProvider`), so they cannot disagree.
void main() {
  setUpAll(loadAppFonts);

  Future<AppDatabase> open(WidgetTester tester,
      {required bool hubThere}) async {
    final api = FakeJamApi();
    final app = await pumpApp(tester, overrides: [
      jamApiProvider.overrideWith((ref) async => hubThere ? api : null),
      jamBackoffProvider.overrideWithValue(const [Duration(milliseconds: 1)]),
    ]);
    return app.db;
  }

  testWidgets('a server without Jam gets no way into it from Home',
      (tester) async {
    final db = await open(tester, hubThere: false);

    expect(find.text('Jam'), findsNothing);
    await closeApp(tester, db);
  });

  testWidgets('a server with Jam shows the chip, and it opens the page',
      (tester) async {
    final db = await open(tester, hubThere: true);

    expect(find.text('Jam'), findsOneWidget);
    await tester.tap(find.text('Jam'));
    await settle(tester);
    expect(find.text('Listen together'), findsOneWidget);
    await closeApp(tester, db);
  });

  test('somebody already in a Jam can always get back to it', () {
    expect(jamEntryShown(hubThere: false, inJam: false), isFalse);
    expect(jamEntryShown(hubThere: true, inJam: false), isTrue);
    expect(jamEntryShown(hubThere: true, inJam: true), isTrue);
    expect(jamEntryShown(hubThere: false, inJam: true), isTrue,
        reason:
            'the network moved or the hub blinked: the Jam is still theirs');
  });
}
