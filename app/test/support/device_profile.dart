import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'package:flutter_test/flutter_test.dart';

/// A kind of phone the app must work on (docs/07 section 4): its screen, the height of the system bar at the bottom (three
/// navigation buttons are 48 dp, the gesture bar 24 dp) and the text size the person chose.
class DeviceProfile {
  const DeviceProfile(this.name, this.size,
      {this.bottomInset = 0, this.textScale = 1});

  final String name;
  final Size size;

  /// Height of the system bar at the bottom of the screen, in dp.
  final double bottomInset;
  final double textScale;

  @override
  String toString() => name;

  /// A common phone with the three navigation buttons: the case that hid the last row of sheets.
  static const threeButtons =
      DeviceProfile('3-button navigation', Size(360, 800), bottomInset: 48);

  /// A phone with the gesture bar.
  static const gesture =
      DeviceProfile('gesture navigation', Size(390, 844), bottomInset: 24);

  /// A small, old phone with the three buttons and the largest text size.
  static const smallBigText = DeviceProfile(
      'small phone, 3 buttons, text 2x', Size(360, 640),
      bottomInset: 48, textScale: 2);

  static const all = [threeButtons, gesture, smallBigText];
}

/// Makes the test screen this kind of phone. Call before `pumpApp`, which keeps the size; the inset is applied here and stays.
void applyProfile(WidgetTester tester, DeviceProfile profile) {
  tester.view.physicalSize = profile.size * 3;
  tester.view.devicePixelRatio = 3;
  final inset = FakeViewPadding(bottom: profile.bottomInset * 3);
  tester.view.padding = inset;
  tester.view.viewPadding = inset;
  tester.platformDispatcher.textScaleFactorTestValue = profile.textScale;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  addTearDown(tester.view.resetPadding);
  addTearDown(tester.view.resetViewPadding);
  addTearDown(tester.platformDispatcher.clearAllTestValues);
}

/// What the person can tap that lies, even partly, under the system bar at the bottom of the screen (the three navigation buttons):
/// it can be seen, but a tap there goes to the system. Empty means everything tappable is reachable. Needs semantics
/// (`tester.ensureSemantics()`).
///
/// The modal barrier and a scrim cover the whole screen on purpose and are not counted.
List<String> tappablesUnderSystemBar(WidgetTester tester, double insetDp) {
  final owner = tester.binding.renderViews.first.owner?.semanticsOwner;
  final root = owner?.rootSemanticsNode;
  if (root == null) {
    fail('no semantics tree: call tester.ensureSemantics() first');
  }
  final dpr = tester.view.devicePixelRatio;
  final screenHeight = tester.view.physicalSize.height / dpr;
  final limit = screenHeight - insetDp;
  final found = <String>[];

  void walk(SemanticsNode node, Matrix4 parent) {
    final transform = parent.clone();
    if (node.transform != null) transform.multiply(node.transform!);
    final data = node.getSemanticsData();
    final hidden = data.flagsCollection.isHidden;
    if (!hidden) {
      if (data.hasAction(SemanticsAction.tap)) {
        final rect = MatrixUtils.transformRect(transform, node.rect);
        final height = rect.height / dpr;
        final bottom = rect.bottom / dpr;
        final coversScreen = height >= screenHeight * 0.8;
        if (!coversScreen && bottom > limit + 1) {
          final label = data.label.isEmpty ? '(no label)' : data.label;
          found.add(
              '"$label" ends at ${bottom.toStringAsFixed(0)} dp, the system bar starts at ${limit.toStringAsFixed(0)} dp');
        }
      }
      node.visitChildren((child) {
        walk(child, transform);
        return true;
      });
    }
  }

  walk(root, Matrix4.identity());
  return found;
}

/// Scrolls every vertical list on the screen to its end: a list that runs under the system bar while it is scrolled is normal (the
/// screen is edge to edge), but at its end the last row must rest above the bar, and that is what is checked.
Future<void> scrollEverythingToTheEnd(WidgetTester tester) async {
  for (var pass = 0; pass < 3; pass++) {
    for (final element in find.byType(Scrollable).evaluate().toList()) {
      final state = tester
          .state<ScrollableState>(find.byElementPredicate((e) => e == element));
      if (state.position.axis != Axis.vertical) continue;
      state.position.jumpTo(state.position.maxScrollExtent);
    }
    await tester.pump(const Duration(milliseconds: 50));
  }
}

/// Everything tappable is reachable on [profile]: lists are at their end and nothing lies under the bottom system bar.
Future<void> expectReachable(
    WidgetTester tester, DeviceProfile profile, String what) async {
  expect(tester.takeException(), isNull, reason: '$what on ${profile.name}');
  await scrollEverythingToTheEnd(tester);
  expect(tester.takeException(), isNull,
      reason: '$what at the end of its list on ${profile.name}');
  expect(tappablesUnderSystemBar(tester, profile.bottomInset), isEmpty,
      reason: '$what on ${profile.name}');
}
