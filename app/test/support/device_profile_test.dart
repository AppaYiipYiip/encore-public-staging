import 'package:encore/features/common/encore_sheet.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'device_profile.dart';

/// The check for "nothing tappable under the navigation buttons" must itself be trusted: it has to notice the old behaviour (a plain
/// bottom sheet whose last row reaches the bottom edge of the screen) and accept the sheet the app uses now.
void main() {
  Future<void> openSheet(WidgetTester tester, {required bool encore}) async {
    applyProfile(tester, DeviceProfile.threeButtons);
    final content = Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        for (var i = 0; i < 4; i++)
          ListTile(title: Text('Row $i'), onTap: () {}),
      ],
    );
    await tester.pumpWidget(MaterialApp(
      home: Builder(
        builder: (context) => Scaffold(
          body: Center(
            child: ElevatedButton(
              onPressed: () => encore
                  ? showEncoreSheet<void>(
                      context: context, builder: (_) => content)
                  : showModalBottomSheet<void>(
                      context: context, builder: (_) => content),
              child: const Text('open'),
            ),
          ),
        ),
      ),
    ));
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
  }

  testWidgets(
      'a plain bottom sheet puts its last row under the three buttons: noticed',
      (tester) async {
    final semantics = tester.ensureSemantics();
    await openSheet(tester, encore: false);

    expect(
        tappablesUnderSystemBar(tester, DeviceProfile.threeButtons.bottomInset),
        isNotEmpty);
    semantics.dispose();
  });

  testWidgets('the app\'s sheet keeps every row above them', (tester) async {
    final semantics = tester.ensureSemantics();
    await openSheet(tester, encore: true);

    expect(
        tappablesUnderSystemBar(tester, DeviceProfile.threeButtons.bottomInset),
        isEmpty);
    semantics.dispose();
  });
}
